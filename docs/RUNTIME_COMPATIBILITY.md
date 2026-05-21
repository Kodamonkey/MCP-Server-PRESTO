# Runtime compatibility

The PRESTO MCP server is a **typed, sandboxed provider of PRESTO capabilities**.
Whether a given tool actually works depends on the configured Docker image —
not every PRESTO image ships every routine, and some ship a script without the
internal Python module it imports.

This document explains how the server reasons about that, and records the
known issues for the pinned image.

## Configured image

| Setting | Default |
|---------|---------|
| `PRESTO_IMAGE` | `alex88ridolfi/presto5:png` |

The server never runs PRESTO on the host. Every invocation — and every
capability probe — happens inside this image.

## How readiness is determined

`src/presto_mcp/runtime_checks.py` runs **lightweight, one-off Docker probes**
against the configured image:

- `which <binary>` — is a binary / script on `PATH`?
- `python3 -c "import importlib.util; find_spec('<module>')"` — is a Python
  module importable?
- `<binary> -h` — does a binary advertise a particular flag?

Probes never run real PRESTO work. Results are cached in-process per image tag
for ~15 minutes, so a session pays the cost once.

Each probe yields a `RuntimeCheck` with a status:

| Status | Meaning |
|--------|---------|
| `OK` | dependency present |
| `ERROR` | dependency definitively absent — the tool will fail if invoked |
| `UNKNOWN` | probe was inconclusive (e.g. Docker timeout) — **fail-open**, never blocks |
| `WARN` | present but with a caveat |

A tool's `ToolReadiness` is the worst status across its dependencies.
`blocking` is `True` only for `ERROR`.

## Checking readiness yourself

Run the diagnostic tool:

```text
presto.validate_environment(include_tool_readiness=true)
```

The result's `runtime_compatibility` field carries:

- `capabilities` — every probed binary and python module;
- `tool_readiness` — per-tool `OK` / `WARN` / `ERROR` / `UNKNOWN` + remediation.

The CI workflow `.github/workflows/runtime-compatibility.yml`
(`workflow_dispatch`) produces the same data as downloadable
`runtime_compatibility.json` + `tool_readiness.md` artifacts.

## Probed binaries

`rfifind`, `DDplan.py`, `prepdata`, `prepsubband`, `realfft`, `accelsearch`,
`single_pulse_search.py`, `rrattrap.py`, `make_spd.py`, `plot_spd.py`,
`waterfaller.py`, `prepfold`, `get_TOAs.py`, `zapbirds`, `simple_zapbirds.py`,
`stacksearch.py`, `readfile`, `psrfits2fil.py`, `downsample_filterbank.py`,
`fb_truncate.py`, `rfifind_stats.py`, `weights_to_ignorechan.py`,
`makezaplist.py`, `sum_profiles.py`, `search_bin`.

`compare_periods` and `binary_info` need only the importable Python module
`presto.parfile` — they are no-Docker utility tools (see below).

## Probed Python modules

`presto.singlepulse`, `presto.waterfaller`, `presto.psrfits`,
`presto.parfile`.

## Known issues

### `presto.waterfaller` Python interpreter

At startup the server probes ``PRESTO_IMAGE`` for ``python3`` then ``python``
(``which`` inside a one-off container) and caches the result for
``presto.waterfaller``. Override with ``PRESTO_PYTHON_BIN=python`` or
``PRESTO_PYTHON_BIN=python3`` if auto-detection is wrong. The headless wrapper
resolves ``waterfaller.py`` via ``which waterfaller.py`` or common install paths.

### `rrattrap.py` present, `presto.singlepulse` not importable

The confirmed, motivating case. Some PRESTO images install `rrattrap.py` on
`PATH` but the Python runtime cannot `import presto.singlepulse`, which
`rrattrap.py` needs. `presto.rrattrap` runs a readiness preflight and, when
this happens, fails fast with a controlled `DockerInvocationError` naming the
script, the missing module and `presto.validate_environment` — instead of a
confusing traceback. The tool is **not removed**; it becomes available again
the moment a compatible image is configured.

### Image-dependent search routines

`stacksearch.py`, `simple_zapbirds.py` and the `accelsearch -wmax` jerk-search
flag are **not present in every PRESTO build**. The corresponding tools probe
the image first:

- `presto.stacksearch` / `presto.simple_zapbirds` — readiness preflight; a
  controlled error if the script is absent.
- `presto.accelsearch` — `wmax` / `sigma` / `ncpus` are checked against
  `accelsearch -h`; a requested-but-unsupported flag raises a clear error
  rather than being silently dropped.
- `presto.ddplan` — `write_dedisp_script` (`-w`) is checked against
  `DDplan.py -h` before use.

### No-Docker utility tools

`presto.compare_periods`, `presto.binary_info` and
`presto.compile_candidate_report_pdf` do not run PRESTO at all — they parse
`.par` files / assemble PDFs locally. They depend only on the MCP server's own
Python environment, never on the PRESTO image.

## Tool status taxonomy

| Status | Meaning |
|--------|---------|
| `stable` | known good against mainline PRESTO; covered by `FakeDockerBackend` tests |
| `experimental` | wired + tested in isolation; awaiting verification against the image |
| `image-dependent` | correctness depends on image contents; readiness-gated |
| `advanced` | wide parameter space; conservative defaults shipped |
| `utility` | no Docker, no PRESTO execution (filesystem / parsing only) |
