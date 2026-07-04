# Author: PB and cx-tfc
# Date: 2026-07-04
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# docs/dashboard-roadmap.md

# Dashboard Roadmap

## Version sequence

`v0.1.0` is the existing two-dashboard baseline. Do not move the tag; treat later fixes as normal post-`0.1.0` work.

`v0.2.0` is the first integrated operations dashboard: `tfcs-tui` remains the primary app, and fleet health becomes an in-app view rather than a separate operator surface.

`0.2.x` is the tuning and OOB-health sequence after the first integration lands. It should refine thresholds, reduce noisy warning states, and add per-server out-of-band health notes without blocking the initial integration.

## Phase 1: post-0.1 cleanup

- Use `http://scott.hrdag.net:9090` as the fleet dashboard Prometheus endpoint so the app runs from any tailnet-connected machine without an SSH tunnel.
- Keep rendered local agent files out of the public repo with `.gitignore` entries for `CLAUDE.md` and `AGENTS.md`.
- Leave `pyproject.toml` at `0.1.0` through this cleanup phase; bump it when the integrated app lands.

## Phase 2: integrated dashboard for 0.2.0

- Make `tfcs-tui` the primary operations dashboard.
- Add a `Fleet` tab backed by the existing `tfcs_fleet_tui` config, Prometheus fetchers, model, and `FleetTable`.
- Keep `tfcs-fleet-tui` as a compatibility entrypoint during the transition unless there is a clear reason to remove it.
- Update package and README language from "cluster dashboard" toward a broader TFC operations dashboard once the integrated view exists.

## Phase 3: collapse redundant views

- Fold latency into the traffic view as a mode, detail, or secondary display; then retire the standalone `Latency` tab.
- Keep heartbeat data initially, but demote the full matrix to a detail/debug view once node-level freshness warnings carry the operational signal.
- Retire the heartbeat tab only after the summarized view catches the failures we care about.

## Phase 4: 0.2.x tuning

- Tune freshness, warning, and critical thresholds against live behavior instead of preserving rough constants.
- Make the bad state easier to scan: sort or highlight by operational severity, distinguish stale from missing, and avoid noisy yellow states.
- Add an OOB health note for each server. Start with config-backed notes, display them compactly in the fleet row, and replace the manual source later if server-documentation or a live endpoint becomes authoritative.
