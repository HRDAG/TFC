#!/usr/bin/env -S /usr/local/bin/uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# Author: PB and Claude
# Date: 2026-05-29
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# scripts/progress-windows.py
#
# Read the tfcs-monitor replication-progress JSONL time series and report
# network convergence over nested time windows (default 6/12/24/48h), so
# you can see whether sole-copy burn-down is accelerating or stalling.
#
# Stats are emitted MAXIMALLY DISAGGREGATED: every per-org holder bucket,
# every anchor counter, every puller<-source flow is shown raw. Aggregation
# (cluster totals, per-anchor inbound) is a column sum the reader does; the
# script never pre-aggregates and throws away detail.
#
# Two correctness rules:
#   - Rates are over the ACTUAL elapsed time between the chosen boundary
#     snapshots (snapshots land ~every 30 min, not exactly on the window),
#     not the nominal window. Both are reported.
#   - STOCKS (holder-bucket counts, sole_holder_count, copies_count) are
#     levels: window delta = end - start. FLOWS (cumulative pull counters:
#     succeeded/bytes/failed/attempts) reset to 0 when an agent restarts, so
#     a naive end-start undercounts across a restart. Flows are integrated
#     piecewise over every intra-window snapshot pair (sum of positive
#     steps); a negative step is treated as a counter reset and flagged.
#
# Usage:
#   ./progress-windows.py                          # all orgs, 6/12/24/48h
#   ./progress-windows.py --org ii                 # one org
#   ./progress-windows.py --windows 6,24,72        # custom windows (hours)
#   ./progress-windows.py --input /path/to.jsonl   # alternate source
#   ./progress-windows.py --json                   # machine-readable

from __future__ import annotations

import argparse
import bisect
import json
import sys
from pathlib import Path

DEFAULT_INPUT = "/var/log/tfcs/replication-progress.jsonl"
DEFAULT_WINDOWS = "6,12,24,48"
BUCKETS = ["1", "2", "3", "4", "5+"]
FLOW_COUNTERS = ["total_succeeded", "total_bytes_pulled", "total_failed", "total_attempts"]


def load_snapshots(path: Path) -> list[dict]:
    snaps = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                snaps.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # tolerate a torn final line
    snaps.sort(key=lambda s: s["ts"])
    return snaps


def fmt_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1024.0 or unit == "PB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024.0
    return f"{n:.1f}PB"


def fmt_signed(n: int | float, *, as_bytes: bool = False) -> str:
    if as_bytes:
        sign = "+" if n >= 0 else "-"
        return f"{sign}{fmt_bytes(abs(n))}"
    return f"{n:+d}" if isinstance(n, int) else f"{n:+.2f}"


def window_start(snaps: list[dict], end_ts: int, hours: float) -> tuple[int, bool]:
    """Index of the first snapshot at/after (end_ts - hours). Returns
    (start_idx, clamped) where clamped=True means the window is older than
    the data, so we fell back to the earliest snapshot."""
    target = end_ts - hours * 3600
    ts_list = [s["ts"] for s in snaps]
    idx = bisect.bisect_left(ts_list, target)
    if idx >= len(snaps):
        idx = len(snaps) - 1
    clamped = snaps[idx]["ts"] > target  # earliest snapshot is later than target
    if idx == 0 and snaps[0]["ts"] > target:
        clamped = True
    return idx, clamped


def integrate_flow(window_snaps: list[dict], puller: str, source: str, counter: str) -> tuple[int, bool]:
    """Sum positive per-step deltas of one cumulative counter over the
    window, skipping snapshots where the puller<-source is absent. Returns
    (total, reset_seen)."""
    total = 0
    reset = False
    prev = None
    for s in window_snaps:
        pull = (s.get("pullers") or {}).get(puller)
        if not pull:
            prev = None  # gap / unreachable: don't bridge across it
            continue
        src = pull.get(source)
        if not src:
            prev = None
            continue
        cur = src.get(counter, 0)
        if prev is not None:
            step = cur - prev
            if step >= 0:
                total += step
            else:
                reset = True  # counter went backwards => agent restart
        prev = cur
    return total, reset


def compute(snaps: list[dict], windows: list[float], org_filter: str | None) -> dict:
    end = snaps[-1]
    end_ts = end["ts"]
    orgs = [o for o in end.get("orgs", {}) if (org_filter is None or o == org_filter)]
    pullers = sorted(end.get("pullers", {}).keys())
    anchors = sorted(end.get("anchors", {}).keys())

    out: dict = {
        "generated_ts_iso": end.get("ts_iso"),
        "source_snapshots": len(snaps),
        "span_hours": round((end_ts - snaps[0]["ts"]) / 3600, 1),
        "windows": {},
    }

    for W in windows:
        start_idx, clamped = window_start(snaps, end_ts, W)
        start = snaps[start_idx]
        window_snaps = snaps[start_idx:]
        elapsed_h = (end_ts - start["ts"]) / 3600 or 1e-9
        wrec: dict = {
            "nominal_hours": W,
            "elapsed_hours": round(elapsed_h, 2),
            "clamped": clamped,
            "orgs": {},
            "anchors": {},
            "pull_flows": {},
        }

        # --- orgs: stocks (total_commits + every holder bucket) ---
        for org in orgs:
            e = end["orgs"].get(org, {})
            s = start["orgs"].get(org, {})
            ed, sd = e.get("holders_distribution", {}), s.get("holders_distribution", {})
            buckets = {}
            for b in BUCKETS:
                ev, sv = int(ed.get(b, 0)), int(sd.get(b, 0))
                buckets[b] = {"now": ev, "delta": ev - sv, "rate_h": round((ev - sv) / elapsed_h, 2)}
            et, st = int(e.get("total_commits", 0)), int(s.get("total_commits", 0))
            net_sole = buckets["1"]["delta"]
            new_commits = et - st
            wrec["orgs"][org] = {
                "total_commits": {"now": et, "delta": new_commits, "rate_h": round(new_commits / elapsed_h, 2)},
                "buckets": buckets,
                # sole_exits = commits that left holders=1 (promotions + sole tombstones),
                # under the flow identity new_commits enter as sole: exits = new - net_sole.
                "sole_exits_est": new_commits - net_sole,
            }

        # --- anchors: stocks + restart flag ---
        for a in anchors:
            e = end["anchors"].get(a, {})
            s = start["anchors"].get(a, {})
            uptime = e.get("uptime_seconds")
            restarted = uptime is not None and uptime < (end_ts - start["ts"])
            arec = {"restarted_in_window": restarted, "active_claims_now": e.get("active_claims")}
            for k in ("sole_holder_count", "copies_count"):
                ev, sv = e.get(k), s.get(k)
                if ev is None or sv is None:
                    arec[k] = {"now": ev, "delta": None, "rate_h": None}
                else:
                    arec[k] = {"now": ev, "delta": ev - sv, "rate_h": round((ev - sv) / elapsed_h, 2)}
            wrec["anchors"][a] = arec

        # --- pull flows: integrated per puller<-source ---
        for p in pullers:
            srcs = (end.get("pullers") or {}).get(p) or {}
            for src in sorted(srcs.keys()):
                key = f"{p} <- {src}"
                flow = {}
                any_reset = False
                for c in FLOW_COUNTERS:
                    total, reset = integrate_flow(window_snaps, p, src, c)
                    any_reset = any_reset or reset
                    flow[c] = {"total": total, "rate_h": round(total / elapsed_h, 2)}
                flow["mbps_now"] = srcs[src].get("agg_mbps")
                flow["counter_reset_in_window"] = any_reset
                if any(flow[c]["total"] for c in FLOW_COUNTERS) or flow["mbps_now"]:
                    wrec["pull_flows"][key] = flow

        out["windows"][f"{int(W)}h" if W == int(W) else f"{W}h"] = wrec

    return out


def render(result: dict, windows: list[float]) -> str:
    wkeys = [f"{int(W)}h" if W == int(W) else f"{W}h" for W in windows]
    L = []
    L.append(f"Network progress  |  generated {result['generated_ts_iso']}  |  "
             f"{result['source_snapshots']} snapshots / {result['span_hours']}h span")
    # note any clamped windows
    clamped = [k for k in wkeys if result["windows"][k]["clamped"]]
    if clamped:
        L.append(f"  ! windows wider than data, clamped to earliest snapshot: {', '.join(clamped)}")
    L.append("  (elapsed h per window: " + ", ".join(
        f"{k}={result['windows'][k]['elapsed_hours']}" for k in wkeys) + ")")

    # orgs
    org_names = list(result["windows"][wkeys[0]]["orgs"].keys())
    for org in org_names:
        L.append("")
        L.append(f"ORG {org}")
        rows = [("total_commits (new)", "total_commits"),
                ("holders=1  SOLE", "b1"), ("holders=2", "b2"), ("holders=3", "b3"),
                ("holders=4", "b4"), ("holders=5+", "b5"), ("sole_exits (est)", "exits")]
        hdr = f"  {'metric':<20} {'now':>8} " + " ".join(f"{k+'(Δ,/h)':>16}" for k in wkeys)
        L.append(hdr)
        for label, kind in rows:
            now = ""
            cells = []
            for k in wkeys:
                o = result["windows"][k]["orgs"][org]
                if kind == "total_commits":
                    now = o["total_commits"]["now"]
                    d, r = o["total_commits"]["delta"], o["total_commits"]["rate_h"]
                elif kind == "exits":
                    now = ""
                    d, r = o["sole_exits_est"], o["sole_exits_est"] / (result["windows"][k]["elapsed_hours"] or 1)
                    r = round(r, 2)
                else:
                    b = {"b1": "1", "b2": "2", "b3": "3", "b4": "4", "b5": "5+"}[kind]
                    now = o["buckets"][b]["now"]
                    d, r = o["buckets"][b]["delta"], o["buckets"][b]["rate_h"]
                cells.append(f"{fmt_signed(d)},{r:+.1f}/h".rjust(16))
            L.append(f"  {label:<20} {str(now):>8} " + " ".join(cells))

    # anchors
    anames = list(result["windows"][wkeys[0]]["anchors"].keys())
    L.append("")
    L.append("ANCHORS")
    for a in anames:
        for k in ("sole_holder_count", "copies_count"):
            cells = []
            now = ""
            for wk in wkeys:
                ar = result["windows"][wk]["anchors"][a][k]
                now = ar["now"]
                if ar["delta"] is None:
                    cells.append("n/a".rjust(16))
                else:
                    cells.append(f"{ar['delta']:+d},{ar['rate_h']:+.1f}/h".rjust(16))
            restarted = any(result["windows"][wk]["anchors"][a]["restarted_in_window"] for wk in wkeys)
            flag = "  [restart in window]" if restarted and k == "sole_holder_count" else ""
            L.append(f"  {a:<16} {k:<18} {str(now):>8} " + " ".join(cells) + flag)

    # pull flows (window totals, longest window for context)
    L.append("")
    L.append(f"PULL FLOWS (puller <- source; integrated totals over each window)")
    flow_keys = sorted({fk for wk in wkeys for fk in result["windows"][wk]["pull_flows"].keys()})
    for fk in flow_keys:
        cells = []
        for wk in wkeys:
            fr = result["windows"][wk]["pull_flows"].get(fk)
            if not fr:
                cells.append("-".rjust(20))
                continue
            succ = fr["total_succeeded"]["total"]
            byts = fr["total_bytes_pulled"]["total"]
            rst = "!" if fr["counter_reset_in_window"] else ""
            cells.append(f"{succ:>4} pulls {fmt_bytes(byts):>8}{rst}".rjust(20))
        L.append(f"  {fk:<30} " + " ".join(cells))
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="tfcs network-progress windowed analyzer")
    ap.add_argument("--input", default=DEFAULT_INPUT, help=f"JSONL series (default {DEFAULT_INPUT})")
    ap.add_argument("--windows", default=DEFAULT_WINDOWS, help=f"comma hours (default {DEFAULT_WINDOWS})")
    ap.add_argument("--org", default=None, help="filter to one org (e.g. ii, km0)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"error: input not found: {path}", file=sys.stderr)
        return 2
    snaps = load_snapshots(path)
    if len(snaps) < 2:
        print(f"error: need >=2 snapshots, got {len(snaps)}", file=sys.stderr)
        return 2

    windows = sorted(float(w) for w in args.windows.split(",") if w.strip())
    result = compute(snaps, windows, args.org)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render(result, windows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
