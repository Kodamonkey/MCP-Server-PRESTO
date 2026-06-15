"""Generate a tiny, spec-valid SIGPROC filterbank (.fil) for tests.

PRESTO's ``readfile`` reads the SIGPROC header, so a minimal-but-correct header
plus a few bytes of sample data is enough to exercise the real read path without
shipping a large telescope capture. No external dependency — just ``struct``.

SIGPROC header wire format: a sequence of length-prefixed ASCII keyword strings.
``HEADER_START`` / ``HEADER_END`` are bare markers; every other keyword is
followed by a value whose type is fixed by the keyword (int32, double, or — for
``source_name`` — another length-prefixed string).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FilterbankParams:
    """Parameters baked into the generated header (also the assertion source)."""

    source_name: str = "FAKE_TEST_PSR"
    telescope_id: int = 4  # Parkes, per SIGPROC's telescope table
    machine_id: int = 0
    nchans: int = 8
    nbits: int = 8
    nifs: int = 1
    nsamples: int = 64
    tsamp: float = 0.000064  # seconds (64 us)
    tstart: float = 58000.5  # MJD
    fch1: float = 1500.0  # MHz (first/highest channel)
    foff: float = -1.0  # MHz per channel (negative = descending)
    src_raj: float = 53200.0  # HHMMSS.s
    src_dej: float = 330500.0  # DDMMSS.s


DEFAULT_PARAMS = FilterbankParams()


def _sstr(s: str) -> bytes:
    raw = s.encode("ascii")
    return struct.pack("<i", len(raw)) + raw


def _sint(key: str, value: int) -> bytes:
    return _sstr(key) + struct.pack("<i", value)


def _sdouble(key: str, value: float) -> bytes:
    return _sstr(key) + struct.pack("<d", value)


def build_header(p: FilterbankParams) -> bytes:
    """Serialize a SIGPROC filterbank header for ``p``."""
    return b"".join(
        [
            _sstr("HEADER_START"),
            _sint("telescope_id", p.telescope_id),
            _sint("machine_id", p.machine_id),
            _sint("data_type", 1),  # 1 = filterbank
            _sstr("source_name") + _sstr(p.source_name),
            _sdouble("src_raj", p.src_raj),
            _sdouble("src_dej", p.src_dej),
            _sdouble("tstart", p.tstart),
            _sdouble("tsamp", p.tsamp),
            _sint("nbits", p.nbits),
            _sint("nchans", p.nchans),
            _sint("nifs", p.nifs),
            _sdouble("fch1", p.fch1),
            _sdouble("foff", p.foff),
            _sstr("HEADER_END"),
        ]
    )


def write_filterbank(path: Path, params: FilterbankParams = DEFAULT_PARAMS) -> Path:
    """Write a complete tiny filterbank file at ``path`` and return it.

    Only ``nbits=8`` is supported (one byte per sample). Sample data is a
    deterministic ramp so the file is reproducible byte-for-byte.
    """
    if params.nbits != 8:
        raise ValueError("write_filterbank only supports nbits=8")
    header = build_header(params)
    n = params.nchans * params.nsamples * params.nifs
    data = bytes((i % 251) for i in range(n))  # deterministic, non-trivial
    path.write_bytes(header + data)
    return path


# -- header reader (verification only) ----------------------------------------


def _read_sstr(buf: bytes, pos: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<i", buf, pos)
    pos += 4
    text = buf[pos : pos + length].decode("ascii")
    return text, pos + length


# Keyword → value reader: 'i' int32, 'd' double, 's' length-prefixed string.
_VALUE_KIND: dict[str, str] = {
    "telescope_id": "i",
    "machine_id": "i",
    "data_type": "i",
    "barycentric": "i",
    "pulsarcentric": "i",
    "nbits": "i",
    "nchans": "i",
    "nifs": "i",
    "nsamples": "i",
    "source_name": "s",
    "rawdatafile": "s",
    "src_raj": "d",
    "src_dej": "d",
    "az_start": "d",
    "za_start": "d",
    "tstart": "d",
    "tsamp": "d",
    "fch1": "d",
    "foff": "d",
}


def read_header(path: Path) -> dict[str, object]:
    """Parse a SIGPROC header back into a dict (round-trip verification)."""
    buf = path.read_bytes()
    pos = 0
    first, pos = _read_sstr(buf, pos)
    if first != "HEADER_START":
        raise ValueError(f"not a SIGPROC filterbank: {first!r}")
    fields: dict[str, object] = {}
    while True:
        key, pos = _read_sstr(buf, pos)
        if key == "HEADER_END":
            break
        kind = _VALUE_KIND.get(key)
        if kind == "i":
            (val_i,) = struct.unpack_from("<i", buf, pos)
            pos += 4
            fields[key] = val_i
        elif kind == "d":
            (val_d,) = struct.unpack_from("<d", buf, pos)
            pos += 8
            fields[key] = val_d
        elif kind == "s":
            val_s, pos = _read_sstr(buf, pos)
            fields[key] = val_s
        else:
            raise ValueError(f"unknown header keyword: {key!r}")
    fields["_header_bytes"] = pos
    fields["_data_bytes"] = len(buf) - pos
    return fields
