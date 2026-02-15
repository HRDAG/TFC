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

            # Color scheme: 1=red, 2=yellow, 3=orange, 4+=green
            if copies == 1:
                style = "red"
            elif copies == 2:
                style = "yellow"
            elif copies == 3:
                style = "bright_yellow"  # orange-ish
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
# Replication velocity
# ---------------------------------------------------------------------------

class ReplicationVelocity(Static):
    """Track replication progress over 5-minute rolling window."""

    DEFAULT_CSS = """
    ReplicationVelocity {
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
        border: solid green;
    }
    """

    def __init__(self, target_copies: int = 3) -> None:
        super().__init__()
        self._target = target_copies
        self._history: list[tuple[float, dict[int, int]]] = []  # (timestamp, distribution)
        self._window_seconds = 300.0  # 5 minutes

    def refresh_data(self, repl: dict[int, int], timestamp: float | None = None) -> None:
        """Update with new replication snapshot."""
        import time
        if timestamp is None:
            timestamp = time.time()

        # Skip empty/unpopulated data (during startup before first global poll)
        if not repl or sum(repl.values()) == 0:
            self.update(Text("Replication Progress (acquiring timing data, stand by...)", style="dim"))
            return

        # Add current snapshot to history
        self._history.append((timestamp, dict(repl)))

        # Prune snapshots older than window
        cutoff = timestamp - self._window_seconds
        self._history = [(ts, dist) for ts, dist in self._history if ts >= cutoff]

        # Need at least 2 snapshots AND 3 minutes elapsed to calculate velocity
        if len(self._history) < 2:
            self.update(Text("Replication Progress (acquiring timing data, stand by...)", style="dim"))
            return

        # Calculate deltas between oldest and newest
        oldest_ts, oldest_dist = self._history[0]
        newest_ts, newest_dist = self._history[-1]
        elapsed_sec = newest_ts - oldest_ts

        if elapsed_sec < 180:  # Less than 3 minutes of data
            self.update(Text("Replication Progress (acquiring timing data, stand by...)", style="dim"))
            return

        # Under-replicated = 1, 2, 3 copies (target is 4+)
        # At target = 4+ copies (bucket 4 in the distribution)
        under_replicated_old = sum(oldest_dist.get(i, 0) for i in [1, 2, 3])
        under_replicated_new = sum(newest_dist.get(i, 0) for i in [1, 2, 3])
        at_target_old = oldest_dist.get(4, 0)  # 4+ copies bucket
        at_target_new = newest_dist.get(4, 0)

        under_delta = under_replicated_new - under_replicated_old
        target_delta = at_target_new - at_target_old

        # Convert to per-minute rate
        elapsed_min = elapsed_sec / 60.0
        under_rate = under_delta / elapsed_min if elapsed_min > 0 else 0
        target_rate = target_delta / elapsed_min if elapsed_min > 0 else 0

        # Build display
        lines = []
        window_min = int(elapsed_sec / 60)
        lines.append(Text(f"Replication Progress ({window_min}min window)", style="bold"))

        # Under-replicated section (1, 2, 3 copies)
        lines.append(Text())
        under_text = Text()
        under_text.append(f"Under-replicated: {under_replicated_new:,} commits", style="")
        lines.append(under_text)

        # Per-bucket breakdown (1, 2, 3 copies only - no 0-copy bucket)
        for copies in [1, 2, 3]:
            old_count = oldest_dist.get(copies, 0)
            new_count = newest_dist.get(copies, 0)
            delta = new_count - old_count
            rate = delta / elapsed_min if elapsed_min > 0 else 0

            line = Text()
            if copies == 1:
                line.append(f"  1 copy:   {new_count:>4}", style="")
            else:
                line.append(f"  {copies} copies: {new_count:>4}", style="")

            # Show delta and rate
            if abs(delta) > 0:
                sign = "+" if delta > 0 else ""
                line.append(f"  ({sign}{delta} in {window_min}m = ", style="dim")
                if abs(rate) >= 0.1:
                    line.append(f"{rate:+.1f}/min)", style="dim")
                else:
                    line.append("~0/min)", style="dim")
            else:
                line.append("  (---)", style="dim")

            lines.append(line)

        # At-target section (4+ copies)
        lines.append(Text())
        target_text = Text()
        target_text.append(f"At target (4+): {at_target_new:,}", style="green")
        if abs(target_delta) > 0:
            sign = "+" if target_delta > 0 else ""
            target_text.append(f" ({sign}{target_delta}/{window_min}m = ", style="dim")
            if abs(target_rate) >= 0.1:
                target_text.append(f"{target_rate:+.1f}/min)", style="dim")
            else:
                target_text.append("~0/min)", style="dim")
        else:
            target_text.append(" (stalled)", style="dim yellow")
        lines.append(target_text)

        # Net velocity
        lines.append(Text())
        net_text = Text()
        net_text.append("Net velocity: ", style="bold")
        if abs(target_rate) >= 0.1:
            net_text.append(f"{target_rate:+.1f} commits/min → target", style="green" if target_rate > 0 else "red")
        else:
            net_text.append("STALLED", style="yellow")
        lines.append(net_text)

        self.update(Text("\n").join(lines))


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

                # Convert rate from Mbps (megabits/sec) to bytes/sec
                if rate > 0:
                    rate_bytes_per_sec = rate * 125_000  # Mbps → bytes/sec (1Mbps = 125KB/s)
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

        # Sort with scott first, then alphabetical
        def sort_key(s):
            nid = s["node_id"]
            return (0 if nid.startswith("scott.") else 1, nid)

        for s in sorted(statuses, key=sort_key):
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


# ---------------------------------------------------------------------------
# Traffic matrix
# ---------------------------------------------------------------------------

class TrafficMatrixTable(DataTable):
    """7×7 bandwidth matrix showing TX from row → column."""

    DEFAULT_CSS = """
    TrafficMatrixTable {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }
    """

    def __init__(self, node_names: list[str], ip_map: dict[str, str]) -> None:
        """
        Args:
            node_names: Sorted list of node FQDNs
            ip_map: {ip: hostname} mapping from tailscale status
        """
        super().__init__()
        # Sort with scott first, then alphabetical
        scott = [n for n in node_names if n.startswith("scott.")]
        others = sorted([n for n in node_names if not n.startswith("scott.")])
        self.node_names = scott + others
        self.ip_to_node = {ip: host for ip, host in ip_map.items()}

    def on_mount(self) -> None:
        # Header row: "From↓ To→" + node short names (4 chars)
        self.add_column("From↓ To→", width=10, key="source")
        for node in self.node_names:
            # Truncate to 4 chars for compact display
            node_abbrev = short(node)[:4]
            self.add_column(node_abbrev, width=4, key=f"dest_{node}")

        self.cursor_type = "none"

        # Right-align column headers to match cell data
        for col_key in self.columns:
            self.columns[col_key].label_align = ("right", "middle")

    def refresh_data(self, traffic_reports: list[dict]) -> None:
        """Update matrix from /traffic poll results.

        Args:
            traffic_reports: [{"node_id": "scott.hrdag.net",
                               "traffic": {"100.64.0.4": {
                                   "tx_rate_bytes_per_sec": ..., ...}}}]
        """
        self.clear()

        # Build traffic matrix: {(src_node, dst_node): tx_rate}
        matrix = {}

        for report in traffic_reports:
            src_node = report["node_id"]
            for peer_ip, stats in report.get("traffic", {}).items():
                dst_node = self.ip_to_node.get(peer_ip)
                if dst_node:
                    tx_rate = stats.get("tx_rate_bytes_per_sec", 0.0)
                    matrix[(src_node, dst_node)] = tx_rate

        # Render matrix rows
        for src in self.node_names:
            # Truncate row labels to 4 chars to match column headers
            row = [short(src)[:4]]

            for dst in self.node_names:
                if src == dst:
                    # Diagonal: pattern creating descending line
                    cell = Text("‾╲__", style="blue on grey27", justify="left")
                else:
                    tx_rate = matrix.get((src, dst), 0.0)
                    cell = self._format_cell(tx_rate)

                row.append(cell)

            self.add_row(*row)

    def _format_cell(self, bytes_per_sec: float) -> Text:
        """Format cell with rate and color gradient (cool → warm)."""

        if bytes_per_sec < 1:
            # Truly zero or negligible
            return Text("--", style="dim", justify="right")

        # Format rate (show even tiny amounts)
        if bytes_per_sec >= 1024 * 1024:
            rate_str = f"{bytes_per_sec/(1024*1024):.1f}M"
        elif bytes_per_sec >= 1024:
            rate_str = f"{bytes_per_sec/1024:.0f}K"
        else:
            # < 1 KB/s: show in bytes (e.g., "45" for 45 B/s)
            rate_str = f"{bytes_per_sec:.0f}"

        # Color gradient: cool (blue) → warm (red)
        if bytes_per_sec < 1024:               # < 1 KB/s (tiny cluster traffic)
            style = "dim cyan"
        elif bytes_per_sec < 100 * 1024:       # < 100 KB/s
            style = "blue"
        elif bytes_per_sec < 500 * 1024:       # < 500 KB/s
            style = "cyan"
        elif bytes_per_sec < 1024 * 1024:      # < 1 MB/s
            style = "green"
        elif bytes_per_sec < 5 * 1024 * 1024:  # < 5 MB/s
            style = "yellow"
        elif bytes_per_sec < 10 * 1024 * 1024: # < 10 MB/s
            style = "bright_yellow"
        else:                                   # >= 10 MB/s
            style = "red bold"

        return Text(rate_str, style=style, justify="right")


# ---------------------------------------------------------------------------
# Traffic heatmap
# ---------------------------------------------------------------------------

class TrafficHeatmap(Static):
    """Color-coded traffic intensity heatmap (sender row → receiver col)."""

    DEFAULT_CSS = """
    TrafficHeatmap {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, node_names: list[str], ip_map: dict[str, str]) -> None:
        """
        Args:
            node_names: Sorted list of node FQDNs
            ip_map: {ip: hostname} mapping from tailscale status
        """
        super().__init__()
        # Sort with scott first, then alphabetical
        self.node_names = self._sort_nodes(node_names)
        self.ip_to_node = {ip: host for ip, host in ip_map.items()}
        self._gradient = self._make_gradient()

        # Track data freshness for dimming
        self._cell_update_cycle: dict[tuple[str, str], int] = {}
        self._current_cycle = 0

    def _sort_nodes(self, nodes: list[str]) -> list[str]:
        """Sort nodes with scott.hrdag.net first, then alphabetical."""
        scott = [n for n in nodes if n.startswith("scott.")]
        others = sorted([n for n in nodes if not n.startswith("scott.")])
        return scott + others

    def _make_gradient(self) -> list[tuple[int, int, int]]:
        """Build gradient: black → blue → cyan → green → yellow → red."""
        stops = [
            (0.0,  (0, 0, 0)),
            (0.15, (0, 0, 180)),
            (0.3,  (0, 140, 180)),
            (0.45, (0, 180, 0)),
            (0.65, (200, 200, 0)),
            (0.85, (220, 80, 0)),
            (1.0,  (255, 60, 60)),
        ]
        gradient = []
        n_colors = 64
        for i in range(n_colors):
            t = i / (n_colors - 1)
            # Find surrounding stops
            for si in range(len(stops) - 1):
                t0, c0 = stops[si]
                t1, c1 = stops[si + 1]
                if t0 <= t <= t1:
                    frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
                    r = int(c0[0] + frac * (c1[0] - c0[0]))
                    g = int(c0[1] + frac * (c1[1] - c0[1]))
                    b = int(c0[2] + frac * (c1[2] - c0[2]))
                    gradient.append((r, g, b))
                    break
        return gradient

    def refresh_data(self, traffic_reports: list[dict], updated_node: str | None = None) -> None:
        """Update heatmap from /traffic poll results.

        Args:
            traffic_reports: [{\"node_id\": \"scott.hrdag.net\",
                               \"traffic\": {\"100.64.0.4\": {
                                   \"tx_rate_bytes_per_sec\": ..., ...}}}]
            updated_node: Which node was just polled (for freshness tracking)
        """
        # Increment cycle counter for freshness tracking
        self._current_cycle += 1

        # Build traffic matrix: {(src_node, dst_node): tx_rate}
        matrix = {}
        # Fixed scale: 0 to 80 MB/s (prevents jarring color changes)
        max_rate = 80_000_000.0  # 80 MB/s

        for report in traffic_reports:
            src_node = report["node_id"]
            for peer_ip, stats in report.get("traffic", {}).items():
                dst_node = self.ip_to_node.get(peer_ip)
                if dst_node:
                    tx_rate = stats.get("tx_rate_bytes_per_sec", 0.0)
                    matrix[(src_node, dst_node)] = tx_rate
                    # Only mark cell as fresh if it's from the newly updated node
                    if src_node == updated_node:
                        self._cell_update_cycle[(src_node, dst_node)] = self._current_cycle

        # Build the heatmap as a single Rich Text object
        lines = []

        # Header row
        header = Text()
        header.append("From↓ To→         ", style="bold")  # Space for full row labels
        for node in self.node_names:
            # Abbreviate to 5 chars, centered in 7-char cell
            header.append(f"{short(node)[:5]:^7}", style="bold")
        lines.append(header)

        # Data rows (3 lines per node for larger square cells)
        for src in self.node_names:
            # First line of row (no label)
            row1 = Text()
            row1.append(" " * 18, style="")

            # Second line of row (row label in middle)
            row2 = Text()
            row2.append(f"{short(src):>17} ", style="")

            # Third line of row (no label)
            row3 = Text()
            row3.append(" " * 18, style="")

            # Cells (7 chars each, touching, 3 lines tall)
            for dst in self.node_names:
                if src == dst:
                    # Diagonal: stepped pattern
                    # (1,1,‾), (1,2,╲), (2,3,‾), (2,4,╲), (3,5,‾), (3,6,╲), (3,7,_)
                    row1.append("‾╲     ", style="blue on grey27")
                    row2.append("  ‾╲   ", style="blue on grey27")
                    row3.append("    ‾╲_", style="blue on grey27")
                else:
                    tx_rate = matrix.get((src, dst), 0.0)
                    # Calculate freshness (cycles since last update)
                    cycles_old = self._current_cycle - self._cell_update_cycle.get((src, dst), 0)
                    text, style = self._format_cell(tx_rate, max_rate, cycles_old)
                    row1.append(text, style=style)
                    row2.append(text, style=style)
                    row3.append(text, style=style)

            lines.append(row1)
            lines.append(row2)
            lines.append(row3)

        # Legend (gradient bar with fixed scale: 0 to 80 MB/s)
        lines.append(Text())  # Blank line
        legend = Text()
        legend.append("                  ", style="")  # Align with data (17 + 1)
        legend.append("0 ", style="dim")

        # Draw gradient bar (40 chars)
        bar_len = 40
        for i in range(bar_len):
            t = i / (bar_len - 1)
            idx = int(t * (len(self._gradient) - 1))
            r, g, b = self._gradient[idx]
            legend.append(" ", style=f"on rgb({r},{g},{b})")

        # Fixed max label: 80 MB/s
        legend.append(" 80M", style="dim")
        lines.append(legend)

        # Update widget with rendered text
        grid = Text("\n").join(lines)
        self.update(grid)

    def _format_cell(self, bytes_per_sec: float, max_rate: float, cycles_old: int) -> tuple[str, str]:
        """Format cell as colored block with log scaling and freshness dimming.

        Args:
            bytes_per_sec: Traffic rate in bytes/sec
            max_rate: Maximum rate in current dataset for scaling
            cycles_old: Number of cycles since last update

        Returns:
            Tuple of (text, style) for Rich Text.append()
        """
        import math

        # Fade out stale data (>20 cycles = 20 seconds)
        if cycles_old > 20:
            return ("       ", "on grey11")

        if bytes_per_sec < 1:
            # No traffic
            return ("       ", "on grey11")

        # Log scaling as recommended in heatmap.py
        # Use max_rate as upper bound for scaling
        t = math.log1p(bytes_per_sec) / math.log1p(max(max_rate, 1.0))
        t = max(0.0, min(1.0, t))

        # Map to gradient color
        idx = int(t * (len(self._gradient) - 1))
        r, g, b = self._gradient[idx]

        # Apply freshness dimming (linear fade over 20 cycles)
        freshness = 1.0 - (cycles_old / 20.0)
        r_dim = int(r * freshness)
        g_dim = int(g * freshness)
        b_dim = int(b * freshness)

        # Return colored block (7 chars wide) with dimming
        return ("       ", f"on rgb({r_dim},{g_dim},{b_dim})")
