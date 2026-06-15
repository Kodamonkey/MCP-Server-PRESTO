"""Unit tests for the ``docker stats`` resource sampler + parsers.

The parsers are pure; the sampler aggregation is exercised by calling
``_sample_once`` directly with a monkeypatched ``subprocess.run`` (no threads,
deterministic).
"""

from __future__ import annotations

import subprocess

import pytest

from presto_mcp import docker_backend as db
from presto_mcp.docker_backend import parse_stats_line


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("123.4MiB / 8GiB|45.20%", (123.4, 45.2)),
        ("1.5GiB / 8GiB|12.00%", (1536.0, 12.0)),
        ("512KiB / 8GiB|0.00%", (0.5, 0.0)),
        ("0B / 8GiB|0.00%", (0.0, 0.0)),
        ("-- / --|--", (None, None)),
        ("garbage-no-pipe", (None, None)),
        ("|", (None, None)),
    ],
)
def test_parse_stats_line(line: str, expected: tuple[float | None, float | None]) -> None:
    mem, cpu = parse_stats_line(line)
    exp_mem, exp_cpu = expected
    if exp_mem is None:
        assert mem is None
    else:
        assert mem == pytest.approx(exp_mem, rel=1e-3)
    assert cpu == exp_cpu


def test_parse_stats_line_multicore_cpu_over_100() -> None:
    _, cpu = parse_stats_line("200MiB / 8GiB|342.50%")
    assert cpu == 342.5


def test_empty_sampler_summary_has_no_metrics() -> None:
    sampler = db._ResourceSampler("docker", "c")
    s = sampler.summary()
    assert s == {
        "peak_memory_mb": None,
        "cpu_percent_peak": None,
        "cpu_percent_avg": None,
        "resource_samples": 0,
    }


def test_sampler_aggregates_peak_and_average(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = db._ResourceSampler("docker", "c")
    outputs = iter(["100MiB / 8GiB|10.00%", "250MiB / 8GiB|30.00%"])

    def fake_run(argv, **_kw):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(argv, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(db.subprocess, "run", fake_run)
    sampler._sample_once()
    sampler._sample_once()

    s = sampler.summary()
    assert s["peak_memory_mb"] == 250.0
    assert s["cpu_percent_peak"] == 30.0
    assert s["cpu_percent_avg"] == 20.0
    assert s["resource_samples"] == 2


def test_sampler_ignores_nonzero_returncode(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = db._ResourceSampler("docker", "c")

    def fake_run(argv, **_kw):  # type: ignore[no-untyped-def]
        # Container already gone → docker stats errors out.
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="No such container")

    monkeypatch.setattr(db.subprocess, "run", fake_run)
    sampler._sample_once()
    assert sampler.summary()["resource_samples"] == 0


def test_sampler_swallows_subprocess_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    sampler = db._ResourceSampler("docker", "c")

    def boom(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="docker stats", timeout=5)

    monkeypatch.setattr(db.subprocess, "run", boom)
    sampler._sample_once()  # must not raise
    assert sampler.summary()["resource_samples"] == 0
