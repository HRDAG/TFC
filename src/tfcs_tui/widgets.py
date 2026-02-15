# Author: PB and Claude
# Date: 2026-02-14
# License: (c) HRDAG, 2025, GPL-2 or newer
#
# ---
# src/tfcs_tui/widgets.py

"""Dashboard widgets for window 1."""

from __future__ import annotations

import humanize
from rich.text import Text
from textual.widgets import DataTable, Static

from tfcs_tui.data import fmt_bytes, fmt_uptime, short


# ---------------------------------------------------------------------------
# Replication histogram
# ---------------------------------------------------------------------------

class ReplicationChart(Static):
    """Horizontal bar chart of replication distribution."""

    DEFAULT_CSS = """
    ReplicationChart {
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._prev_bins: dict[int, int] = {}

    def refresh_data(
        self, repl: dict[int, int], target_copies: int,
    ) -> None:
        # Always show 1,2,3,4+ bins (no 0 - there are no 0-copy commits)
        bins = {1: 0, 2: 0, 3: 0, 4: 0}
        for copies, count in repl.items():
            if copies == 0:
                continue  # Skip 0-copy commits
            elif copies < 4:
                bins[copies] = count
            else:
                bins[4] += count

        total = sum(bins.values())
        if total == 0:
            self.update(Text("replication: no data", style="dim"))
            return

        max_count = max(bins.values())
        bar_width = 40
        lines = []

        title = f"replication ({total} commits, target: {target_copies} copies)"
        lines.append(Text(f"  {title}", style="bold"))

        for copies in [1, 2, 3, 4]:
            count = bins[copies]
            if copies == 4:
                label = "4+ copies"
            elif copies == 1:
                label = "1 copy"
            else:
                label = f"{copies} copies"
            filled = int(count / max_count * bar_width) if max_count else 0
            bar_str = "\u2588" * filled

            # Color scheme: 1=red, 2=orange, 3=yellow, 4+=green
            if copies == 1:
                style = "red"
            elif copies == 2:
                style = "bright_yellow"  # orange-ish
            elif copies == 3:
                style = "yellow"
            else:
                style = "green"

            # Change indicator
            prev_count = self._prev_bins.get(copies, count)
            if count > prev_count:
                indicator = Text(" ↑", style="green")
            elif count < prev_count:
                indicator = Text(" ↓", style="red")
            else:
                indicator = Text("")

            line = Text()
            line.append(f"{label:>10}  ", style="")
            line.append(bar_str, style=style)
            line.append(f"  {count:>5}")
            line.append(indicator)
            lines.append(line)

        group = Text("\n").join(lines)
        self.update(group)

        # Save current bins for next refresh comparison
        self._prev_bins = bins.copy()


# ---------------------------------------------------------------------------
# Transfers table
# ---------------------------------------------------------------------------

class TransfersTable(DataTable):
    """Scrollable table of active transfers from node claims."""

    DEFAULT_CSS = """
    TransfersTable {
        height: 1fr;
        min-height: 5;
    }
    """

    def on_mount(self) -> None:
        self.add_column("Source", width=10, key="source")
        self.add_column("", width=2, key="arrow")
        self.add_column("Dest", width=10, key="dest")
        self.add_column("Rate", width=10, key="rate")
        self.add_column("Commit", width=10, key="commit")
        self.add_column("Progress", width=14, key="progress")
        self.cursor_type = "row"
        self.zebra_stripes = True

    def refresh_data(self, statuses: list[dict]) -> None:
        self.clear()

        rows = []
        for s in statuses:
            for claim in s.get("claims", []):
                source = short(claim.get("source", "?"))
                dest = short(s["node_id"])
                commit = claim.get("commit", "")[:8]
                size = claim.get("size", 0)
                xmit = claim.get("bytes_transmitted", 0)
                rate = claim.get("rate_mbps", 0.0)

                if size > 0 and xmit >= size:
                    prog = Text(f"{fmt_bytes(size)} done", style="green")
                elif size > 0:
                    prog = Text(f"{fmt_bytes(xmit)}/{fmt_bytes(size)}")
                else:
                    prog = Text("--")

                # Humanize rate: 44.9 MB/s -> "45 MB/s", 8.5 MB/s -> "8.5 MB/s"
                if rate > 0:
                    rate_bytes_per_sec = rate * 1_000_000
                    rate_str = humanize.naturalsize(rate_bytes_per_sec, binary=False, format="%.1f") + "/s"
                else:
                    rate_str = "--"
                rows.append((source, "\u2192", dest, rate_str, commit, prog))

        # Sort by dest, then source
        rows.sort(key=lambda r: (r[2], r[0]))

        if rows:
            for row in rows:
                self.add_row(*row)
        else:
            self.add_row("--", "", "--", "idle", Text(""), "")


# ---------------------------------------------------------------------------
# Nodes table
# ---------------------------------------------------------------------------

class NodesTable(DataTable):
    """Node summary table with status coloring."""

    DEFAULT_CSS = """
    NodesTable {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
    }
    """

    def on_mount(self) -> None:
        self.add_column("Node", width=8, key="node")
        self.add_column("Site", width=9, key="site")
        self.add_column("Class", width=7, key="class")
        self.add_column("Status", width=7, key="status")
        self.add_column("HB", width=4, key="hb")
        self.add_column("Uptime", width=9, key="uptime")
        self.add_column("Ver", width=5, key="ver")
        self.add_column("Seq", width=5, key="seq")
        self.add_column("Store", width=5, key="store")
        self.add_column("Free", width=7, key="free")
        self.add_column("Peers", width=5, key="peers")
        self.add_column("Pulls", width=5, key="pulls")
        self.cursor_type = "none"

        # Center all column headers
        for col_key in self.columns:
            self.columns[col_key].label_align = ("center", "middle")

        # Right-align numeric column content
        self.columns["hb"].content_align = ("right", "middle")
        self.columns["seq"].content_align = ("right", "middle")
        self.columns["store"].content_align = ("right", "middle")
        self.columns["free"].content_align = ("right", "middle")
        self.columns["peers"].content_align = ("right", "middle")
        self.columns["pulls"].content_align = ("right", "middle")

    def refresh_data(
        self, statuses: list[dict], node_status: dict[str, str],
        heartbeat_age: dict[str, float],
    ) -> None:
        self.clear()

        for s in sorted(statuses, key=lambda x: x["node_id"]):
            nid = s["node_id"]
            status = node_status.get(nid, "unknown")
            hb_age = heartbeat_age.get(nid, 0.0)
            hb_str = f"{hb_age:.0f}s" if hb_age > 0 else "--"
            free_gb = s.get("free_gb", 0)
            free_str = humanize.naturalsize(free_gb * 1_000_000_000, binary=False, format="%.0f")
            pulls = len(s.get("claims", []))
            pull_str = str(pulls) if pulls > 0 else "--"
            uptime = fmt_uptime(s.get("uptime_seconds", 0))
            peers = str(s.get("alive_peers", 0))

            status_style = (
                "green" if status == "alive"
                else "yellow" if status == "suspect"
                else "red"
            )
            free_style = "red bold" if free_gb < 50 else ""

            self.add_row(
                short(nid),
                s.get("cluster", "?"),
                s.get("node_class", "?"),
                Text(status, style=status_style),
                Text(hb_str, justify="right"),
                uptime,
                s.get("version", "?"),
                Text(str(s.get("seq", 0)), justify="right"),
                Text(str(s.get("store_count", 0)), justify="right"),
                Text(free_str, style=free_style, justify="right"),
                Text(peers, justify="right"),
                Text(pull_str, justify="right"),
            )
