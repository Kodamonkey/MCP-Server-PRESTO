"""``presto.fourier_fold`` — wrap ``fourier_fold.py`` (experimental).

Fold from ``.fft`` complex amplitudes at a known (period or frequency, optional
DM). Useful for inspecting a specific candidate without a full temporal fold.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..executor import RunSpec, execute
from ..models import FourierFoldProfileSummary, FourierFoldResult, ToolRunResult
from ..policies import check_dm, check_fourier_fold_period_or_freq

log = logging.getLogger("presto_mcp.tools.fourier_fold")


def run_fourier_fold(
    fft_file: str,
    *,
    backend: BackendProtocol,
    period_seconds: float | None = None,
    frequency_hz: float | None = None,
    dm: float | None = None,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[FourierFoldResult]:
    """``fourier_fold.py [-p <period_s> | -f <freq_hz>] [-dm <dm>] <fft>``.

    Exactly one of ``period_seconds`` or ``frequency_hz`` must be supplied.
    ``fft_file`` is ``<run_id>/artifacts/<file>.fft`` under ``RUNS_DIR``.
    """
    s = settings or get_settings()
    period, freq = check_fourier_fold_period_or_freq(period_seconds, frequency_hz)
    d = check_dm(dm) if dm is not None else None

    def argv_builder(
        container_input: str, _extras: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        argv = ["fourier_fold.py"]
        if period is not None:
            argv += ["-p", str(period)]
        else:
            argv += ["-f", str(freq)]
        if d is not None:
            argv += ["-dm", str(d)]
        argv.append(container_input)
        return argv

    def parser(_stdout: str, run_dir: Path) -> FourierFoldResult:
        artifacts_dir = run_dir / "artifacts"
        profile: str | None = None
        plot: str | None = None
        notes: list[str] = []
        if artifacts_dir.is_dir():
            profs = sorted(
                p.name for p in artifacts_dir.glob("*.prof")
            ) + sorted(p.name for p in artifacts_dir.glob("*.profile"))
            plots = sorted(
                p.name for p in artifacts_dir.glob("*.png")
            ) + sorted(p.name for p in artifacts_dir.glob("*.ps"))
            if profs:
                profile = profs[0]
            if plots:
                plot = plots[0]
        if profile is None and plot is None:
            notes.append("no profile/plot artifact produced; check stderr")
        summary = FourierFoldProfileSummary(
            period_s=period, frequency_hz=freq, dm=d
        )
        return FourierFoldResult(
            fft_file=fft_file,
            profile_file=profile,
            plot_file=plot,
            summary=summary,
            notes=notes,
        )

    inputs_extra: dict[str, str] = {"fft_file": fft_file}
    if period is not None:
        inputs_extra["period_seconds"] = str(period)
    if freq is not None:
        inputs_extra["frequency_hz"] = str(freq)
    if d is not None:
        inputs_extra["dm"] = str(d)

    spec = RunSpec[FourierFoldResult](
        tool_name="fourier_fold",
        input_file=fft_file,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        input_root="runs",
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
