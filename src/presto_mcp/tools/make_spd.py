"""``presto.make_spd`` — wrap ``make_spd.py`` (single-pulse diagnostic).

Reads a ``groups.txt`` (from prior rrattrap run) plus a raw
filterbank/PSRFITS file (under ``DATA_DIR``) plus one or more
``.singlepulse`` files (from prior single_pulse_search run) and writes
``<basename>_DM<dm>_<t>_RANK.spd`` files into its working directory.

Optional rfifind ``.mask`` (under ``DATA_DIR``) can be passed via
``mask_file`` and the ``mask=True`` flag.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..errors import PathSecurityError
from ..executor import ExtraInput, RunSpec, execute
from ..models import MakeSpdResult, ToolRunResult
from ..parsers import make_spd_parser
from ..path_security import resolve_run_artifact
from ..policies import check_makespd_input_count, check_output_prefix

log = logging.getLogger("presto_mcp.tools.make_spd")


def run_make_spd(
    raw_file: str,
    groups_file: str,
    singlepulse_files: list[str],
    *,
    backend: BackendProtocol,
    mask_file: str | None = None,
    output_prefix: str | None = None,
    apply_mask: bool = False,
    settings: Settings | None = None,
    background: bool = False,
) -> ToolRunResult[MakeSpdResult]:
    """``make_spd.py --groupsfile groups.txt [--mask --maskfile <mask>] -o <prefix> /data/raw <sp>...``.

    * ``raw_file``: relative to ``DATA_DIR``.
    * ``groups_file``: ``<run_id>/artifacts/<file>.txt`` relative to ``RUNS_DIR``.
    * ``singlepulse_files``: list of ``<run_id>/artifacts/<file>.singlepulse``.
    * ``mask_file`` (optional): relative to ``DATA_DIR``.
    """
    s = settings or get_settings()
    check_makespd_input_count(len(singlepulse_files))
    prefix = check_output_prefix(output_prefix) if output_prefix else "spd"

    host_groups = resolve_run_artifact(groups_file, s.runs_dir)
    if host_groups.suffix not in (".txt", ".groups"):
        raise PathSecurityError(
            f"make_spd groups_file expected .txt/.groups; got {host_groups.name}"
        )
    groups_name = host_groups.name

    host_sp: list[Path] = []
    sp_names: list[str] = []
    for rel in singlepulse_files:
        host = resolve_run_artifact(rel, s.runs_dir)
        if host.suffix != ".singlepulse":
            raise PathSecurityError(
                f"make_spd expects .singlepulse files; got {host.name}"
            )
        host_sp.append(host)
        sp_names.append(host.name)

    if len(set(sp_names)) != len(sp_names):
        raise PathSecurityError(
            "make_spd singlepulse inputs must have unique filenames after staging"
        )
    if groups_name in set(sp_names):
        raise PathSecurityError(
            "groups_file name collides with a singlepulse filename"
        )

    extras_list: list[ExtraInput] = [ExtraInput(path=raw_file, root="data")]
    if mask_file is not None:
        extras_list.append(ExtraInput(path=mask_file, root="data"))
    extras = tuple(extras_list)

    def hook(run_dir: Path, _extras: tuple[Path, ...]) -> None:
        dst_dir = run_dir / "artifacts"
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(host_groups, dst_dir / groups_name)
        for host in host_sp:
            shutil.copy2(host, dst_dir / host.name)

    def argv_builder(
        _container_input: str, extra_paths: tuple[str, ...], _run_dir: Path
    ) -> list[str]:
        raw_container = extra_paths[0]
        argv = [
            "make_spd.py",
            "--groupsfile", groups_name,
            "--noplot",
            "-o", prefix,
        ]
        if mask_file is not None:
            mask_container = extra_paths[1]
            argv += ["--maskfile", mask_container]
            if apply_mask:
                argv.append("--mask")
        argv.append(raw_container)
        argv += sp_names
        return argv

    def parser(stdout: str, run_dir: Path) -> MakeSpdResult:
        return make_spd_parser.parse(
            stdout,
            run_dir,
            raw_file=raw_file,
            groups_file=groups_file,
            input_singlepulse_files=tuple(singlepulse_files),
            mask_file=mask_file,
        )

    inputs_extra: dict[str, str] = {
        "raw_file": raw_file,
        "groups_file": groups_file,
        "output_prefix": prefix,
        "sp_count": str(len(singlepulse_files)),
    }
    if mask_file is not None:
        inputs_extra["mask_file"] = mask_file
        inputs_extra["apply_mask"] = "true" if apply_mask else "false"

    spec = RunSpec[MakeSpdResult](
        tool_name="make_spd",
        input_file=None,
        inputs_extra=inputs_extra,
        container_input_path="",
        presto_argv_builder=argv_builder,
        parser=parser,
        timeout_s=s.default_timeout_s,
        cpus=s.default_cpus,
        memory_mb=s.default_memory_mb,
        extra_inputs=extras,
        pre_invocation_hook=hook,
        container_workdir="/outputs/artifacts",
    )
    return execute(spec, s, backend, background=background)
