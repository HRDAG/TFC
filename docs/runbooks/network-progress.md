<!--
Author: PB and Claude
Date: 2026-05-29
License: (c) HRDAG, 2026, GPL-2 or newer

---
docs/runbooks/network-progress.md
-->

# Runbook: network progress over rolling windows

**Question this answers:** is the cluster *converging* — and is convergence
**accelerating or stalling**? Concretely: how fast is sole-copy burn-down
per org, accounting for new commits arriving, and is the network actually
moving bytes to make it happen.

Use it when you want a fast read on replication health without eyeballing
raw snapshots, after a release that was meant to unstick replication, or
when deciding whether a backlog will clear on its own.

The most important number is **per-org sole-copy burn-down** (`holders=1`),
read against **new ingest** (`total_commits` Δ) so you don't mistake "no new
sole copies arriving" for "existing sole copies getting promoted."

---

## Quick start

```bash
# on scott (the data lives there), as any user — the series is world-readable
./scripts/progress-windows.py                      # all orgs, 6/12/24/48h
./scripts/progress-windows.py --org ii             # just the ii backlog
./scripts/progress-windows.py --windows 6,24,72    # custom windows (hours)
./scripts/progress-windows.py --json | jq .        # machine-readable
```

Run it from a checkout of this repo on scott, or copy just the script over
(`scp scripts/progress-windows.py scott:/tmp/`) — it is stdlib-only, so
plain `python3 progress-windows.py` works without `uv`.

---

## Data source

`progress-windows.py` reads a JSONL **time series**, one snapshot per line,
produced by the collector (`tfcs-monitor`, see [Operational notes](#operational-notes)):

- **Current path:** `scott:/var/log/tfcs/replication-progress.jsonl`
  (world-readable, `0664`). *Planned:* `scott:/var/lib/tfcs-monitor/` — see
  Operational notes.
- **Cadence:** one snapshot every 30 min.
- **Completeness:** verify before trusting a window —
  ```bash
  wc -l /var/log/tfcs/replication-progress.jsonl    # ~48/day
  ```
  As of 2026-05-29 the series was continuous over ~14.6 days (median gap
  exactly 1800 s, worst gap one missed run). Windows up to ~48h have dense
  coverage. A window wider than the data is **clamped to the earliest
  snapshot and flagged** in the output.

Each snapshot already aggregates cluster-wide state (anchor counters,
per-puller pull stats, per-org holder distribution from scott's DB), so the
analyzer needs **no SSH** — everything for the three core metrics is in the
series. For finer detail than 30-min snapshots can give, see
[Going deeper](#going-deeper-via-ssh).

---

## Reading the output

Worked example (real, 2026-05-29):

```
Network progress  |  generated 2026-05-29T17:00:01Z  |  705 snapshots / 352.2h span
  (elapsed h per window: 6h=6.0, 12h=12.0, 24h=24.0, 48h=48.0)

ORG ii
  metric                    now         6h(Δ,/h)        12h(Δ,/h)        24h(Δ,/h)        48h(Δ,/h)
  total_commits (new)     15193        +0,+0.0/h        +0,+0.0/h        +0,+0.0/h        +0,+0.0/h
  holders=1  SOLE         10914       -47,-7.8/h       -98,-8.2/h      -146,-6.1/h      -325,-6.8/h
  holders=2                   0        -1,-0.2/h        -1,-0.1/h        -1,-0.0/h      -100,-2.1/h
  holders=3                2709       +23,+3.8/h       +56,+4.7/h       +79,+3.3/h      +278,+5.8/h
  holders=4                1567       +25,+4.2/h       +43,+3.6/h       +68,+2.8/h      +147,+3.1/h
  holders=5+                  3        +0,+0.0/h        +0,+0.0/h        +0,+0.0/h        +0,+0.0/h
  sole_exits (est)                    +47,+7.8/h       +98,+8.2/h      +146,+6.1/h      +325,+6.8/h
```

How to read it, line by line:

- **`total_commits (new)` Δ** — gross commit-count change for the org
  (ingest minus tombstone/revoke removals). Here `+0` across all windows:
  **no new ingest**, so everything below is pure replication catch-up.
- **`holders=1 SOLE`** — the headline. `10914` commits exist on exactly one
  node. Burning down at `−7.8/h` (last 6h) vs `−6.1/h` (last 24h): the
  **recent rate is faster than the daily average → convergence is
  accelerating.** A 6h rate *slower* than the 48h rate would mean stalling.
- **`holders=2..5+`** — where the sole copies *went*. Over 48h the buckets
  net to zero (1:−325, 2:−100, 3:+278, 4:+147) against `total_commits` Δ=0:
  commits climbed the ladder 1,2 → 3,4. This conservation check is your
  sanity test that the numbers are coherent.
- **`sole_exits (est)`** — commits that left `holders=1` (promotions +
  sole-commit tombstones, lumped). Equals `new_commits − Δholders=1`. With
  no new ingest it equals the burn-down; with ingest it separates
  "promoted" from "newly arrived as sole." See the [caveat](#caveats) on the
  identity.

```
ANCHORS
  ant.hrdag.net    sole_holder_count         0        +0,+0.0/h  ...  [restart in window]
  ida.hrdag.net    sole_holder_count     10914       -47,-7.8/h  ...  [restart in window]
  ida.hrdag.net    copies_count          15380        +0,+0.0/h  ...
```

- **`sole_holder_count`** is the anchor's own count of commits only it holds
  — should track the org's `holders=1` (it does: −325 == ii bucket-1).
  Divergence here vs the org bucket means a metadata-convergence lag.
- **`copies_count`** flat while sole burns down = the anchor keeps its
  copies; *other* nodes are gaining them. That's healthy replication.
- **`[restart in window]`** — the agent's `uptime_seconds` is less than the
  widest window's span, so a restart happened somewhere in the lookback.
  Treat that anchor's flow counters with the reset caveat below.

```
PULL FLOWS (puller <- source; integrated totals over each window)
  ben.hrdag.net <- ida.hrdag.net     5 pulls    5.1GB     8 pulls    8.1GB   13 pulls   13.2GB!   49 pulls   49.7GB!
```

- Per `puller <- source`: completed pulls and bytes moved **in the window**.
  This is the "is the network actually working" view — burn-down with zero
  pull flow would mean the metadata moved but the bytes didn't.
- **`!`** = a cumulative counter reset (agent restart) inside that window.
  The total is still correct (integrated piecewise across the reset), but
  it tells you the raw counters aren't a clean end−start.

**Aggregate by summing columns** — the script deliberately does not
pre-aggregate. Cluster-wide pull rate = sum the flow rows; inbound to one
anchor = sum the `<- ida` rows; etc.

---

## Going deeper via SSH

The 30-min HTTP snapshot gives *counts and rates*. When you need to know
**which** commits, **why** a pull failed, or **sub-30-min** timing, the
snapshot can't help and you go to node logs. What each adds:

| You want | Where | Roughly |
|---|---|---|
| Which commits got promoted / pulled, and when | `<node>:/var/log/tfcs/tfcs.log` (INFO) | `grep -E "pull (done|complete)" tfcs.log` |
| Why pulls fail (claim contention, source down, ENOSPC) | same, plus `journalctl -u tfcs-agent` (WARN+) | `journalctl -u tfcs-agent -p warning --since "6h ago"` |
| Verify outcomes (full/quick, merkle/par2 failures) | `scott:/var/log/tfcs/tfcs.log` | `grep "signal verify" tfcs.log` |
| Per-transfer rsync throughput / stalls | `<node>:/var/log/tfcs/tfcs.log` (rsync_progress) | `grep -i "rsync\|stall" tfcs.log` |
| New-ingest events (separate true ingest from `total_commits` Δ) | anchor `:/var/log/tfcs/tfcs.log` | `grep "ingest:" tfcs.log` |

For a heavier, log-derived view across nodes (per-commit copy counts over
time, framed by data-safety levels), the existing
`tfcs/scripts/safety-report.py` (a.k.a. throughput-report) SSHes every node
and reconstructs events from logs — slower, but ground-truth when the
snapshot series isn't enough.

SSH keys for fleet access live under `~/.ssh/ephemeral/` (see
`safety-report.py` for the per-node key convention).

---

## Caveats

- **`sole_exits` identity.** It assumes new commits enter as `holders=1` on
  the anchor (true for originated commits). Revokes/tombstones also lower
  `total_commits` and can lower `holders=1` without a promotion, so
  `sole_exits` lumps promotions with sole-tombstones. When `total_commits` Δ
  is non-zero, read `sole_exits` as an estimate, and cross-check with the
  per-bucket Δs (a real promotion shows up as growth in 2/3/4).
- **Counter resets.** Pull flow counters are cumulative and reset on agent
  restart. The analyzer integrates positive per-step deltas, so totals
  survive a restart, but a restart *during a gap* (puller unreachable across
  the reset) can still undercount. The `!` marker and `[restart in window]`
  flag tell you when to be skeptical.
- **Rates are over actual elapsed time**, not the nominal window — the
  header prints the real elapsed hours per window. Usually within a snapshot
  of nominal; matters only near a gap.
- **Stocks vs flows.** Holder buckets and anchor counts are levels
  (end−start). Pull counters are flows (integrated). Don't compare a level Δ
  to a flow total directly.

---

## Operational notes

- **Collector:** `tfcs-monitor` (this repo) snapshots the cluster every
  30 min. Source of truth is `TFC/scripts/`; installed on scott to
  `/usr/local/bin/tfcs-monitor`, run as `tfcs`, **permanently** (not a
  temporary watcher).
- **Planned data path:** `/var/lib/tfcs-monitor/replication-progress.jsonl`
  (FHS: it's data, not a log). Note `/var/lib/tfcs` itself is the `tfcs`
  user's *home directory* (holds `.ssh`, `.sigstore`) — monitor data goes in
  a *sibling* `tfcs-monitor` dir so "world-readable" never touches the
  service-account home. Until that migration lands, the source path is
  `/var/log/tfcs/replication-progress.jsonl` (already world-readable).
- **This tool is single-machine** (scott only) and intentionally **not**
  ansible-managed — install it with `make install` from this repo.
