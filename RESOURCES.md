# MCP resources

All resources are read-only. Path-traversal is rejected; large or binary
artifacts are not inlined. Each handler validates the `run_id` shape and
re-anchors the resolved path under `PRESTO_RUNS_DIR` /
`PRESTO_DATA_DIR`.

## Per-run resources (existing)

| URI                                                  | MIME               | Returns                                                        |
|------------------------------------------------------|--------------------|----------------------------------------------------------------|
| `presto://runs/{run_id}/manifest`                    | `application/json` | The full `RunManifest` JSON for one run.                       |
| `presto://runs/{run_id}/stdout`                      | `text/plain`       | Captured stdout for one run.                                   |
| `presto://runs/{run_id}/stderr`                      | `text/plain`       | Captured stderr for one run.                                   |
| `presto://runs/{run_id}/artifacts/{filename}`        | `text/*` or JSON   | Small text artifact inline; large/binary → JSON descriptor.    |

The artifact handler refuses any `filename` containing `/`, `\`, or `..`.
Files larger than 1 MiB return a JSON descriptor with `host_path` rather
than the bytes.

## Navigation resources (new)

| URI                                                  | MIME               | Returns                                                        |
|------------------------------------------------------|--------------------|----------------------------------------------------------------|
| `presto://data`                                      | `application/json` | `ListDataFilesResult` — relative paths under `PRESTO_DATA_DIR`.|
| `presto://runs`                                      | `application/json` | `{count, runs: [RunSummary]}` — newest first.                  |
| `presto://runs/{run_id}/summary`                     | `application/json` | `RunStructuredSummary` — counts + suggested next tools.        |
| `presto://runs/{run_id}/artifacts`                   | `application/json` | `InspectArtifactsResult` — artifact index, no contents.        |

### `presto://data`

Backed by `tools.list_data_files.run_list_data_files`. Returns paths
relative to `PRESTO_DATA_DIR`. Never absolute. Hidden files excluded.

### `presto://runs`

Backed by `tools.list_runs.list_runs`. Each entry is a `RunSummary`
(`run_id`, `tool`, `status`, `started_at`, `duration_s`, `exit_code`,
`manifest_uri`).

### `presto://runs/{run_id}/summary`

Backed by `tools.summarize_run.summarize_run`. Groups artifacts by
`ArtifactType` (rfi / time_series / fft / accel_candidates /
single_pulse / spd / plots / fold / timing / other) and suggests the next
PRESTO tool to call given the artifact set.

### `presto://runs/{run_id}/artifacts`

Backed by `tools.summarize_run.inspect_artifacts`. One row per artifact
file with size, mtime, classified type, the per-file resource URI, and an
`is_inline_readable` hint for clients picking what to fetch next.

## Boundary

- No binary artifact is ever inlined into a JSON resource — fetch the
  per-file URI for that.
- `presto://data` and `presto://runs/{run_id}/summary` are bounded in
  size; for very large run directories the per-tool default limit applies.
