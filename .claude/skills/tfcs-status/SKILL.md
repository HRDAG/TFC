---
name: tfcs-status
description: Run the TFC replication-progress analyzer on scott and produce a cluster convergence report — per-org sole-copy burn-down, ETA, accelerating-vs-stalling, and pull flows. Trigger on "tfcs status", "network progress", "replication report", "how's the cluster converging", "is replication catching up", "run the progress report".
---

# tfcs-status

Produce a **convergence report** from the tfcs-monitor snapshot series on
scott. Convergence only — no infra/timer/health reporting.

## Run

Always fetch fresh and run on scott (the series lives there):

```
ssh scott 'cd ~/projects/TFC && git pull --ff-only -q && ./scripts/progress-windows.py ARGS'
```

Map the request to `ARGS`:
- a single org → `--org ii` (hrdag, ida-anchored) or `--org km0` (datacivica, ant-anchored)
- explicit windows → `--windows 6,24` (hours); omit for the default `6,12,24,48`
- raw numbers → add `--json`

## Report shape

From the output, write a tight report in this order:

1. **Verdict** — one line: converging vs stalling, and ingest-driven vs pure
   catch-up. `total_commits` Δ=0 across windows ⇒ no new ingest, every change
   is promotion.
2. **Per org** — `holders=1` (SOLE) burn-down rate; **accel vs stall** =
   compare the recent 6/12h rate to the 48h average (recent faster ⇒
   accelerating); **ETA** = `sole_now ÷ recent_rate`; **conservation check**
   = the bucket Δs sum to `total_commits` Δ (sanity).
3. **Anchors** — seeding (`copies_count` flat while `sole_holder_count`
   drains) vs gaining; confirm `sole_holder_count` Δ matches the org's
   `holders=1` Δ.
4. **Pull flows** — top pullers per source and total volume moved from each
   anchor.
5. **Watch-item / lever** — the slowest-draining backlog and what would
   speed it (usually puller bandwidth on the anchor).
6. **Caveats** — trust reset-free recent windows most; `!` = a cumulative
   counter reset across an agent restart; `[restart in window]` = anchor
   restarted in the lookback; `clamped` = window older than the data span.

**Headline metric is per-org `holders=1` burn-down.** For deeper
interpretation and SSH drill-down into node logs, see
`docs/runbooks/network-progress.md`.

## Boundary

Read-only. This skill runs `git pull` + the analyzer over SSH and reads
state. It NEVER runs `par2 repair`, deletes, re-pulls, or mutates cluster
state.
