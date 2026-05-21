"""In-memory fake of :class:`presto_mcp.docker_backend.DockerBackend`.

Replaces the real backend in unit/integration tests. Honors the
``BackendProtocol`` shape so call sites are interchangeable.

Behaviors:

* Returns canned stdout/stderr/exit_code keyed by tool-name OR by a custom hook.
* Capability probes (``which X``, ``python3 -c "import ..."``, ``X -h``) collide
  under plain tool-name keying, so they are matched first against
  ``probe_responses`` using a composite key: ``which:<name>`` / ``module:<name>``
  / ``help:<name>``.
* Optionally drops a file (or set of files) into ``run_dir/artifacts`` to
  simulate PRESTO writing outputs at ``/outputs/...`` inside the container.
* Records every invocation for assertion.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from presto_mcp.models import BackendResult, DockerInvocation, RunStatus


def probe_key(post_image_argv: tuple[str, ...]) -> str | None:
    """Map a probe argv (everything after the image) to a composite probe key.

    Returns ``which:<name>`` / ``module:<name>`` / ``help:<name>`` or None when
    the argv is not a recognised runtime-capability probe.
    """
    if len(post_image_argv) == 2 and post_image_argv[0] == "which":
        return f"which:{post_image_argv[1]}"
    if len(post_image_argv) == 2 and post_image_argv[1] == "-h":
        return f"help:{post_image_argv[0]}"
    if (
        len(post_image_argv) >= 3
        and post_image_argv[0] == "python3"
        and post_image_argv[1] == "-c"
    ):
        m = re.search(r"find_spec\(['\"]([^'\"]+)['\"]\)", post_image_argv[2])
        if m:
            return f"module:{m.group(1)}"
    return None


@dataclass
class FakeBackendCall:
    invocation: DockerInvocation
    timeout_s: int


@dataclass
class FakeResponse:
    """Canned response for one PRESTO tool."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    status: RunStatus = RunStatus.SUCCESS
    error: str | None = None
    # Files dropped into <run_dir>/artifacts/ to mimic --mount /outputs writes.
    artifacts: dict[str, bytes] = field(default_factory=dict)
    # If set, called with (invocation, run_dir) for advanced setup.
    side_effect: Callable[[DockerInvocation, Path], None] | None = None


class FakeDockerBackend:
    """Drop-in BackendProtocol implementation. No subprocess, no network."""

    def __init__(
        self,
        responses: dict[str, FakeResponse] | None = None,
        probe_responses: dict[str, FakeResponse] | None = None,
    ) -> None:
        self.responses: dict[str, FakeResponse] = responses or {}
        self.probe_responses: dict[str, FakeResponse] = probe_responses or {}
        self.calls: list[FakeBackendCall] = []
        self.digest: str | None = "sha256:fakedigest1234567890"

    def set_response(self, tool: str, response: FakeResponse) -> None:
        self.responses[tool] = response

    def set_probe_response(self, key: str, response: FakeResponse) -> None:
        """Set a capability-probe response. ``key`` is which:/module:/help:<name>."""
        self.probe_responses[key] = response

    def run(self, invocation: DockerInvocation, timeout_s: int) -> BackendResult:
        self.calls.append(FakeBackendCall(invocation=invocation, timeout_s=timeout_s))
        # The presto binary is the first argv element after the image.
        # invocation.argv = ["docker","run","--rm",...,"<image>","<presto_binary>",...]
        image_idx = invocation.argv.index(invocation.image)
        tool = invocation.argv[image_idx + 1]
        post_image = tuple(invocation.argv[image_idx + 1 :])

        # Capability probes win over plain tool-name keying.
        pkey = probe_key(post_image)
        if pkey is not None and pkey in self.probe_responses:
            resp = self.probe_responses[pkey]
        else:
            resp = self.responses.get(tool, FakeResponse())

        # Find run_dir from the second --mount (the rw one).
        run_dir: Path | None = None
        for el in invocation.argv:
            if el.startswith("type=bind,") and ",dst=/outputs" in el and ",readonly" not in el:
                src = el.split(",", 2)[1]
                if src.startswith("src="):
                    run_dir = Path(src[len("src="):])
                break

        if run_dir is not None:
            artifacts_dir = run_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            for name, data in resp.artifacts.items():
                (artifacts_dir / name).write_bytes(data)
            if resp.side_effect:
                resp.side_effect(invocation, run_dir)

        # Tiny non-zero duration so durations look real.
        return BackendResult(
            status=resp.status,
            exit_code=resp.exit_code,
            stdout=resp.stdout,
            stderr=resp.stderr,
            duration_s=time.monotonic() % 1.0 + 0.01,
            error=resp.error,
        )

    def inspect_image_digest(self, image: str) -> str | None:  # noqa: ARG002
        return self.digest
