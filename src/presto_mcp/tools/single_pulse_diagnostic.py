"""``presto.single_pulse_diagnostic`` — canonical PRESTO single-pulse workflow.

Chains the four PRESTO stages that produce a canonical single-pulse
diagnostic for a candidate, in order:

  1. ``single_pulse_search`` — scan ``.dat`` files for single-pulse events
  2. ``rrattrap``           — group co-located events into RRAT candidates
  3. ``make_spd``           — extract the canonical ``.spd`` per group
  4. ``plot_spd``           — render the diagnostic PNG for each ``.spd``

The workflow short-circuits on the first failing stage: a partial result is
returned with the stages run so far, so the caller can inspect intermediate
``run_id``s without losing observability.

This is intentionally an orchestration layer only. Each underlying tool
runs as a separate PRESTO invocation (its own ``run_id``, manifest, logs)
— the workflow is composed, not collapsed.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import Settings, get_settings
from ..docker_backend import BackendProtocol
from ..models import (
    RunStatus,
    SinglePulseDiagnosticResult,
    SinglePulseDiagnosticStage,
    ToolRunResult,
)
from .make_spd import run_make_spd
from .plot_spd import run_plot_spd
from .rrattrap import run_rrattrap
from .single_pulse_search import run_single_pulse_search

log = logging.getLogger("presto_mcp.tools.single_pulse_diagnostic")


def _stage(
    stage_name: str,
    result: ToolRunResult[object],
) -> SinglePulseDiagnosticStage:
    return SinglePulseDiagnosticStage(
        stage=stage_name,  # type: ignore[arg-type]
        run_id=result.run_id,
        status=result.status,
        error=result.error,
    )


def run_single_pulse_diagnostic(
    *,
    dat_files: list[str],
    inf_file: str,
    raw_file: str,
    backend: BackendProtocol,
    mask_file: str | None = None,
    apply_mask: bool = False,
    threshold: float = 5.0,
    max_width_s: float = 0.1,
    min_group: int | None = None,
    use_dm_plan: bool = False,
    just_waterfall: bool = False,
    max_spd_plots: int = 10,
    settings: Settings | None = None,
) -> tuple[SinglePulseDiagnosticResult, RunStatus]:
    """Run the canonical PRESTO single-pulse diagnostic chain end-to-end.

    Stages 1–4 run in order against a single :class:`BackendProtocol`. The
    workflow returns ``(result, overall_status)`` where ``overall_status`` is
    ``SUCCESS`` only when every stage succeeded; otherwise the status of the
    first failing stage is returned and downstream stages are skipped.

    Parameters
    ----------
    dat_files:
        ``<run_id>/artifacts/<file>.dat`` paths from prepdata / prepsubband.
    inf_file:
        ``<run_id>/artifacts/<file>.inf`` matching the dat files.
    raw_file:
        Original observation, either relative to ``DATA_DIR`` or
        ``<run_id>/artifacts/<file>`` (auto-detected).
    mask_file:
        Optional rfifind ``.mask`` (data or run artifact). Required when
        ``apply_mask`` is true.
    apply_mask:
        Forwarded to ``make_spd`` ``--mask``.
    threshold, max_width_s:
        ``single_pulse_search`` parameters.
    min_group, use_dm_plan:
        ``rrattrap`` parameters.
    just_waterfall:
        Forwarded to ``plot_spd`` ``--just-waterfall``.
    max_spd_plots:
        Cap on how many ``.spd`` files to plot (each is its own PRESTO
        invocation). Prevents runaway plotting on dense groupings.
    """
    s = settings or get_settings()
    result = SinglePulseDiagnosticResult()
    stages = result.stages

    # 1. single_pulse_search
    sps = run_single_pulse_search(
        dat_files,
        backend=backend,
        threshold=threshold,
        max_width_s=max_width_s,
        settings=s,
    )
    stages.append(_stage("single_pulse_search", sps))
    if sps.status != RunStatus.SUCCESS or sps.result is None:
        return result, sps.status
    sp_run = sps.run_id
    sp_rel = [
        f"{sp_run}/artifacts/{Path(name).name}" for name in sps.result.singlepulse_files
    ]
    result.singlepulse_files = sp_rel

    # 2. rrattrap
    rrat = run_rrattrap(
        sp_rel,
        inf_file,
        backend=backend,
        min_group=min_group,
        use_dm_plan=use_dm_plan,
        settings=s,
    )
    stages.append(_stage("rrattrap", rrat))
    if rrat.status != RunStatus.SUCCESS or rrat.result is None:
        return result, rrat.status
    if not rrat.result.groups_file:
        return result, RunStatus.FAILED
    groups_rel = f"{rrat.run_id}/artifacts/{Path(rrat.result.groups_file).name}"
    result.groups_file = groups_rel

    # 3. make_spd
    spd = run_make_spd(
        raw_file,
        groups_rel,
        sp_rel,
        backend=backend,
        mask_file=mask_file,
        apply_mask=apply_mask,
        settings=s,
    )
    stages.append(_stage("make_spd", spd))
    if spd.status != RunStatus.SUCCESS or spd.result is None:
        return result, spd.status
    spd_rel = [
        f"{spd.run_id}/artifacts/{Path(name).name}" for name in spd.result.spd_files
    ]
    result.spd_files = spd_rel
    if not spd_rel:
        # make_spd ran but produced no .spd — nothing to plot
        return result, RunStatus.SUCCESS

    # 4. plot_spd — one invocation per .spd file (capped by max_spd_plots)
    overall = RunStatus.SUCCESS
    for spd_path in spd_rel[: max(0, int(max_spd_plots))]:
        plot = run_plot_spd(
            spd_path,
            backend=backend,
            singlepulse_files=sp_rel,
            just_waterfall=just_waterfall,
            settings=s,
        )
        stages.append(_stage("plot_spd", plot))
        if plot.status == RunStatus.SUCCESS and plot.result is not None and plot.result.png_file:
            result.plot_pngs.append(
                f"{plot.run_id}/artifacts/{Path(plot.result.png_file).name}"
            )
        elif plot.status != RunStatus.SUCCESS and overall == RunStatus.SUCCESS:
            overall = plot.status

    return result, overall


__all__ = ["run_single_pulse_diagnostic"]
