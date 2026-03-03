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

from tfcs_tui.data import compute_total_copies, fmt_bytes, fmt_uptime, short


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
        # Per-bin change tracking: bin -> (monotonic_ts, "↑"/"↓")
        # Arrow shows for 60s from when the change was first detected.
        self._prev_node_bins: dict[int, int] = {}
        self._prev_site_bins: dict[int, int] = {}
        self._node_bin_changes: dict[int, tuple[float, str]] = {}
        self._site_bin_changes: dict[int, tuple[float, str]] = {}

    def _render_histogram(
        self,
        bins: dict[int, int],
        labels: dict[int, str],
        styles: dict[int, str],
        bin_changes: dict[int, tuple[float, str]],
        now: float,
        bar_width: int = 40,
        alarm_bins: set[int] | None = None,
    ) -> list[Text]:
        """Render one histogram block, returning list of Text lines."""
        max_count = max(bins.values()) if bins else 1
        lines = []
        for b in sorted(bins):
            count = bins[b]
            label = labels[b]
            style = styles[b]
            filled = int(count / max_count * bar_width) if max_count else 0
            bar_str = "\u2588" * filled

            last_change = bin_changes.get(b)
            if last_change and now - last_change[0] <= 60:
                indicator = Text(f" {last_change[1]}",
                                 style="green" if last_change[1] == "↑" else "red")
            else:
                indicator = Text("")

            suffix = Text()
            suffix.append(f"  {count:>5}")
            if alarm_bins and b in alarm_bins and count > 0:
                suffix.append("  !!", style="bold red")
            suffix.append(indicator)

            line = Text()
            line.append(f"{label:>10}  ", style="")
            line.append(bar_str, style=style)
            line.append(suffix)
            lines.append(line)
        return lines

    def _update_changes(
        self,
        bins: dict[int, int],
        prev_bins: dict[int, int],
        bin_changes: dict[int, tuple[float, str]],
        now: float,
    ) -> None:
        """Update per-bin change tracking in place."""
        for b, count in bins.items():
            prev = prev_bins.get(b, count)
            if count > prev:
                bin_changes[b] = (now, "↑")
            elif count < prev:
                bin_changes[b] = (now, "↓")

    def refresh_data(
        self,
        repl: dict[int, int],
        target_copies: int,
        site_dist: dict[int, int] | None = None,
    ) -> None:
        import time
        now = time.monotonic()

        # --- Node copies histogram (staged-but-not-ingested not shown here) ---
        bins = {1: 0, 2: 0, 3: 0, 4: 0}
        for copies, count in repl.items():
            if 1 <= copies < 4:
                bins[copies] = count
            elif copies >= 4:
                bins[4] += count

        total = sum(bins.values())
        if total == 0:
            self.update(Text("replication: no data", style="dim"))
            return

        self._update_changes(bins, self._prev_node_bins, self._node_bin_changes, now)
        self._prev_node_bins = bins.copy()

        node_labels = {1: "1 copy", 2: "2 copies", 3: "3 copies", 4: "4+ copies"}
        node_styles = {1: "red", 2: "yellow", 3: "bright_yellow", 4: "green"}

        lines = []
        title = f"replication ({total} commits, target: {target_copies} copies) — node copies"
        lines.append(Text(f"  {title}", style="bold"))
        lines.extend(self._render_histogram(
            bins, node_labels, node_styles, self._node_bin_changes, now,
            alarm_bins={1},
        ))

        # --- Site distribution histogram ---
        if site_dist:
            site_bins = {1: 0, 2: 0, 3: 0, 4: 0}
            for sites, count in site_dist.items():
                if sites <= 1:
                    site_bins[1] += count
                elif sites < 4:
                    site_bins[sites] = count
                else:
                    site_bins[4] += count

            self._update_changes(site_bins, self._prev_site_bins, self._site_bin_changes, now)
            self._prev_site_bins = site_bins.copy()

            site_labels = {1: "1 site", 2: "2 sites", 3: "3 sites", 4: "4+ sites"}
            site_styles = {1: "bold red", 2: "yellow", 3: "bright_yellow", 4: "green"}

            lines.append(Text(""))
            lines.append(Text("  site copies (target: ≥2 sites)", style="bold"))
            lines.extend(self._render_histogram(
                site_bins, site_labels, site_styles, self._site_bin_changes, now,
                alarm_bins={1},
            ))

        self.update(Text("\n").join(lines))


# ---------------------------------------------------------------------------
# Cluster overview
# ---------------------------------------------------------------------------

class ClusterOverview(Static):
    """Cluster overview summary — top of Replication tab."""

    DEFAULT_CSS = """
    ClusterOverview {
        padding: 0 1;
        height: auto;
        margin-bottom: 0;
        background: $surface;
        border: tall $primary;
    }
    """

    def __init__(self, target_copies: int = 3) -> None:
        super().__init__()
        self._target = target_copies

    def refresh_data(
        self,
        replication: dict[int, int],
        node_status: dict[str, str],
        velocity_data: dict | None = None,
        site_dist: dict[int, int] | None = None,
        sole_holder_nodes: dict[str, int] | None = None,
    ) -> None:
        """Update overview from current cluster state."""
        target = self._target
        zero_copy = replication.get(0, 0)
        total_commits = sum(v for k, v in replication.items() if k > 0)
        total_copies = compute_total_copies(replication)
        satisfied = sum(v for k, v in replication.items() if k >= target)
        unsatisfied = sum(v for k, v in replication.items() if 0 < k < target)
        sat_pct = round(satisfied / total_commits * 100, 1) if total_commits else 0.0

        n_nodes = len(node_status)

        lines = []
        # Line 1: node count + total copies
        lines.append(Text(f"{n_nodes} nodes, {total_copies:,} total copies across {total_commits:,} commits", style="bold"))
        # Line 2: node-satisfied / unsatisfied
        sat_text = Text()
        sat_text.append(f"Node-satisfied (>={target} copies): ", style="")
        sat_text.append(f"{satisfied:,} ({sat_pct}%)", style="green")
        sat_text.append(f"  Unsatisfied: ", style="")
        sat_text.append(f"{unsatisfied:,}", style="yellow" if unsatisfied > 0 else "green")
        lines.append(sat_text)
        # Line 3: site distribution
        if site_dist:
            site_total = sum(site_dist.values())
            single_site = site_dist.get(1, 0)
            multi_site = site_total - single_site
            multi_pct = round(multi_site / site_total * 100, 1) if site_total else 0.0
            site_text = Text()
            site_text.append("Site-distributed (≥2 sites): ", style="")
            site_text.append(f"{multi_site:,} ({multi_pct}%)", style="green")
            site_text.append("  Single-site: ", style="")
            site_text.append(str(single_site), style="red bold" if single_site > 0 else "green")
            lines.append(site_text)
        # Line 4: velocity + ETA (compact)
        if velocity_data is not None:
            cpm = velocity_data.get("copies_per_min", 0)
            eta = velocity_data.get("eta_satisfied_min")
            vel_text = Text()
            vel_text.append(f"Velocity: ", style="")
            if cpm >= 0.1:
                vel_text.append(f"+{cpm:.1f} copies/min", style="green")
            else:
                vel_text.append("STALLED", style="yellow")
            if eta is not None:
                vel_text.append(f"  ETA: ~{eta:.0f} min ({eta/60:.1f} hr)", style="yellow")
            lines.append(vel_text)
        # Warnings
        if zero_copy > 0:
            zc_text = Text()
            zc_text.append(f"+{zero_copy} with no copies, may need investigation", style="yellow")
            lines.append(zc_text)
        if sole_holder_nodes:
            sole_text = Text()
            sole_text.append("!! Sole holders: ", style="red bold")
            parts = [f"{node} {count:,}" for node, count in sorted(sole_holder_nodes.items(), key=lambda x: -x[1])]
            sole_text.append("  ".join(parts), style="red")
            lines.append(sole_text)

        self.update(Text("\n").join(lines))


# ---------------------------------------------------------------------------
# Replication velocity
# ---------------------------------------------------------------------------

class ReplicationVelocity(Static):
    """Replication velocity from server /replication?window=N endpoint."""

    DEFAULT_CSS = """
    ReplicationVelocity {
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
        border: solid green;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def refresh_data(self, velocity: dict | None) -> None:
        """Display server-computed velocity data."""
        if velocity is None:
            self.update(Text("(waiting for velocity data...)", style="dim"))
            return

        cpm = velocity.get("copies_per_min", 0)
        new_copies = velocity.get("new_copies", 0)
        window_min = velocity.get("window_minutes", 10)
        bytes_per_min = velocity.get("bytes_per_min", 0)
        by_source = velocity.get("by_source", {})

        lines = []
        vel_text = Text()
        if cpm >= 0.1:
            vel_text.append(f"+{cpm:.1f} copies/min", style="green")
        else:
            vel_text.append("STALLED", style="yellow")
        vel_text.append(f"  ({new_copies} new in {window_min}m window)", style="dim")
        if bytes_per_min > 0:
            bw_str = humanize.naturalsize(bytes_per_min / 60, binary=False, format="%.1f") + "/s"
            vel_text.append(f"  ~{bw_str}", style="dim")
        lines.append(vel_text)

        if by_source:
            for node_fqdn, count in sorted(by_source.items(), key=lambda x: -x[1]):
                src_text = Text()
                src_text.append(f"  {short(node_fqdn):<10}", style="")
                src_text.append(f"{count:>3} copies", style="dim")
                lines.append(src_text)

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
        self.add_column("tfcs-Ver", width=9, key="ver")
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
            sole_count = s.get("sole_holder_count", 0)
            node_cell = Text(short(nid), style="red bold" if sole_count > 0 else "")

            self.add_row(
                node_cell,
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
# Source utilization
# ---------------------------------------------------------------------------

class SourceUtilization(DataTable):
    """Aggregated sends and bandwidth per source node."""

    DEFAULT_CSS = """
    SourceUtilization {
        height: auto;
        max-height: 10;
        margin-bottom: 1;
    }
    """

    def on_mount(self) -> None:
        self.add_column("Source", width=10, key="source")
        self.add_column("Sends", width=6, key="sends")
        self.add_column("BW", width=10, key="bw")
        self.cursor_type = "none"

    def refresh_data(self, statuses: list[dict]) -> None:
        self.clear()
        # Aggregate by source (statuses is list[dict], not dict[str, dict])
        agg: dict[str, dict] = {}
        for s in statuses:
            for claim in s.get("claims", []):
                src = short(claim.get("source", "?"))
                if src not in agg:
                    agg[src] = {"sends": 0, "total_bw_mbps": 0.0}
                agg[src]["sends"] += 1
                agg[src]["total_bw_mbps"] += claim.get("rate_mbps", 0.0)

        if not agg:
            self.add_row("--", "0", "no active sends")
            return

        for src in sorted(agg, key=lambda s: -agg[s]["sends"]):
            info = agg[src]
            # Convert Mbps to bytes/sec for display
            bw_bytes = info["total_bw_mbps"] * 125_000
            if bw_bytes > 0:
                bw_str = humanize.naturalsize(bw_bytes, binary=False, format="%.1f") + "/s"
            else:
                bw_str = "--"
            self.add_row(src, str(info["sends"]), bw_str)


# ---------------------------------------------------------------------------
# Velocity chart
# ---------------------------------------------------------------------------

class VelocityChart(Static):
    """Velocity-over-time chart using Textual's Sparkline."""

    DEFAULT_CSS = """
    VelocityChart {
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
    }
    """

    def refresh_data(self, history: list[tuple[str, float]]) -> None:
        """Render velocity chart from history.

        Args:
            history: [(HH:MM, copies_per_min), ...] chronologically sorted
        """
        if len(history) < 2:
            self.update(Text("Velocity chart: collecting data...", style="dim"))
            return

        # Trim to most recent 60 entries
        if len(history) > 60:
            history = history[-60:]

        # Filter negative readings (corrupted data)
        history = [(t, v) for t, v in history if v >= 0]
        if len(history) < 2:
            self.update(Text("Velocity chart: collecting data...", style="dim"))
            return

        values = [v for _, v in history]
        v_max = max(values)
        v_min = 0  # Always anchor at 0

        # Unicode block chars for sparkline (8 levels)
        blocks = " ▁▂▃▄▅▆▇█"
        v_range = v_max if v_max > 0 else 1.0

        current_val = values[-1]
        lines = []
        lines.append(Text(f"Velocity (copies/min)  current: {current_val:.1f}  max: {v_max:.1f}", style="bold"))

        # Build sparkline rows (4 rows high for resolution)
        height = 4
        mid = v_max / 2.0
        for row in range(height - 1, -1, -1):
            # Y-axis label: top row = max, middle row = mid, bottom row = 0
            if row == height - 1:
                label = f"{v_max:>5.1f}|"
            elif row == height // 2:
                label = f"{mid:>5.1f}|"
            elif row == 0:
                label = f"{v_min:>5.1f}|"
            else:
                label = "     |"
            line = Text()
            line.append(label, style="dim")
            for v in values:
                # Normalize to 0..height range (anchored at 0), then get sub-block for this row
                scaled = v / v_range * height
                row_val = scaled - row  # how much of this row is filled
                if row_val >= 1.0:
                    line.append("█", style="green")
                elif row_val > 0:
                    idx = int(row_val * 8)
                    line.append(blocks[max(1, idx)], style="green")
                else:
                    line.append(" ")
            lines.append(line)

        # Time labels: first and last — indent by 6 chars to align with chart area
        axis_prefix = " " * 6
        first_label = history[0][0]
        last_label = history[-1][0]
        gap = len(history) - len(first_label) - len(last_label)
        time_line = Text()
        time_line.append(axis_prefix, style="")
        if gap > 0:
            time_line.append(first_label, style="dim")
            time_line.append(" " * gap, style="dim")
            time_line.append(last_label, style="dim")
        else:
            time_line.append(first_label, style="dim")
        lines.append(time_line)

        self.update(Text("\n").join(lines))


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
# Base heatmap class
# ---------------------------------------------------------------------------

class BaseHeatmap(Static):
    """Base class for N×N heatmap grids with 3-row-tall cells."""

    def __init__(self, node_names: list[str]) -> None:
        super().__init__()
        self.node_names = self._sort_nodes(node_names)
        self._cell_update_cycle: dict[tuple[str, str], int] = {}
        self._current_cycle = 0

    def _sort_nodes(self, nodes: list[str]) -> list[str]:
        """Sort nodes: scott first, then alphabetical."""
        scott = [n for n in nodes if n.startswith("scott.")]
        others = sorted([n for n in nodes if not n.startswith("scott.")])
        return scott + others

    def _build_matrix(self, data: object) -> dict[tuple[str, str], float]:
        """Build metric matrix from data. Subclass implements."""
        raise NotImplementedError

    def _format_cell(self, value: float, cycles_old: int) -> tuple[str, str]:
        """Format cell with color. Subclass implements."""
        raise NotImplementedError

    def _get_row_label_width(self) -> int:
        """Return label width (18 for Traffic, 7 for others)."""
        return 7  # Override in TrafficHeatmap

    def _get_diagonal_pattern(self) -> tuple[str, str, str]:
        """Return diagonal pattern for row1, row2, row3."""
        return ("‾╲     ", "  ‾╲   ", "    ‾╲_")  # Standardized

    def _get_diagonal_style(self) -> str:
        """Return diagonal style."""
        return "blue on grey27"

    def _render_legend(self) -> list[Text]:
        """Render optional legend. Override in TrafficHeatmap."""
        return []  # No legend by default

    def _render_grid(self, matrix: dict[tuple[str, str], float]) -> None:
        """Render the grid (shared logic)."""
        lines = []
        label_width = self._get_row_label_width()
        diag_r1, diag_r2, diag_r3 = self._get_diagonal_pattern()
        diag_style = self._get_diagonal_style()

        # Axis labels
        col_area_width = len(self.node_names) * 7
        axis_line = Text()
        axis_line.append(f"{'sender ↓':<{label_width}}", style="dim")
        axis_line.append(f"{'receiver →':^{col_area_width}}", style="dim")
        lines.append(axis_line)

        # Column header
        header = Text(" " * label_width)
        for node in self.node_names:
            header.append(f"{short(node)[:5]:^7}", style="bold")
        lines.append(header)

        # Data rows (3 lines per node)
        for src in self.node_names:
            row1 = Text(" " * label_width)
            row2 = Text(f"{short(src):>{label_width-2}}  ")
            row3 = Text(" " * label_width)

            for dst in self.node_names:
                if src == dst:
                    row1.append(diag_r1, style=diag_style)
                    row2.append(diag_r2, style=diag_style)
                    row3.append(diag_r3, style=diag_style)
                else:
                    value = matrix.get((src, dst), 0.0)
                    cycles_old = self._current_cycle - self._cell_update_cycle.get((src, dst), 0)
                    text, style = self._format_cell(value, cycles_old)
                    row1.append(text, style=style)
                    row2.append(text, style=style)
                    row3.append(text, style=style)

            lines.extend([row1, row2, row3])

        # Optional legend
        lines.extend(self._render_legend())

        # Assemble
        group = Text()
        for i, line in enumerate(lines):
            if i > 0:
                group.append("\n")
            group.append(line)

        self.update(group)

    def _apply_freshness_dimming(self, r: int, g: int, b: int, cycles_old: int) -> tuple[int, int, int]:
        """Apply freshness dimming (shared logic)."""
        if cycles_old > 20:
            freshness = 0.0
        else:
            freshness = 1.0 - (cycles_old / 20.0)
        return (int(r * freshness), int(g * freshness), int(b * freshness))


# ---------------------------------------------------------------------------
# Traffic heatmap
# ---------------------------------------------------------------------------

class TrafficHeatmap(BaseHeatmap):
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
        super().__init__(node_names)
        self.ip_to_node = {ip: host for ip, host in ip_map.items()}
        self._gradient = self._make_gradient()
        self._max_rate = 80_000_000.0  # Fixed scale: 80 MB/s

    def _get_row_label_width(self) -> int:
        """Traffic heatmap uses wider labels."""
        return 18

    def _build_matrix(self, traffic_reports: list[dict]) -> dict[tuple[str, str], float]:
        """Build traffic matrix from reports."""
        matrix = {}
        for report in traffic_reports:
            src_node = report["node_id"]
            for peer_ip, stats in report.get("traffic", {}).items():
                dst_node = self.ip_to_node.get(peer_ip)
                if dst_node:
                    matrix[(src_node, dst_node)] = stats.get("tx_rate_bytes_per_sec", 0.0)
        return matrix

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
        self._current_cycle += 1
        matrix = self._build_matrix(traffic_reports)

        # Track freshness for cells from updated node
        for report in traffic_reports:
            if report["node_id"] == updated_node:
                for peer_ip, stats in report.get("traffic", {}).items():
                    dst = self.ip_to_node.get(peer_ip)
                    if dst:
                        self._cell_update_cycle[(report["node_id"], dst)] = self._current_cycle

        self._render_grid(matrix)

    def _format_cell(self, bytes_per_sec: float, cycles_old: int) -> tuple[str, str]:
        """Format cell as colored block with log scaling and freshness dimming."""
        import math

        if cycles_old > 20:
            return ("       ", "on grey11")

        if bytes_per_sec < 1:
            return ("       ", "on grey11")

        # Log scaling with fixed max_rate
        t = math.log1p(bytes_per_sec) / math.log1p(max(self._max_rate, 1.0))
        t = max(0.0, min(1.0, t))

        # Map to gradient color
        idx = int(t * (len(self._gradient) - 1))
        r, g, b = self._gradient[idx]

        # Apply freshness dimming
        r_dim, g_dim, b_dim = self._apply_freshness_dimming(r, g, b, cycles_old)

        return ("       ", f"on rgb({r_dim},{g_dim},{b_dim})")

    def _render_legend(self) -> list[Text]:
        """Render gradient legend with fixed scale (0-80 MB/s)."""
        lines = []
        lines.append(Text())  # Blank line

        legend = Text()
        legend.append("                  ", style="")  # Align with data (18 chars)
        legend.append("0 ", style="dim")

        # Draw gradient bar (40 chars)
        bar_len = 40
        for i in range(bar_len):
            t = i / (bar_len - 1)
            idx = int(t * (len(self._gradient) - 1))
            r, g, b = self._gradient[idx]
            legend.append(" ", style=f"on rgb({r},{g},{b})")

        legend.append(" 80M", style="dim")
        lines.append(legend)

        return lines


# ---------------------------------------------------------------------------
# Latency heatmap (RTT)
# ---------------------------------------------------------------------------

class LatencyHeatmap(BaseHeatmap):
    """Color-coded RTT latency heatmap (sender row → receiver col)."""

    DEFAULT_CSS = """
    LatencyHeatmap {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, node_names: list[str], ip_map: dict[str, str]) -> None:
        super().__init__(node_names)
        self.ip_to_node = {ip: host for ip, host in ip_map.items()}

    def _get_row_label_width(self) -> int:
        """Match TrafficHeatmap spacing."""
        return 18

    def _build_matrix(self, traffic_reports: list[dict]) -> dict[tuple[str, str], float]:
        """Build latency matrix from reports."""
        matrix = {}
        for report in traffic_reports:
            src_node = report["node_id"]
            for peer_ip, stats in report.get("traffic", {}).items():
                dst_node = self.ip_to_node.get(peer_ip)
                if dst_node and stats.get("avg_rtt_us", 0) > 0:
                    matrix[(src_node, dst_node)] = stats["avg_rtt_us"]
        return matrix

    def refresh_data(self, traffic_reports: list[dict], updated_node: str | None = None) -> None:
        """Update heatmap from /traffic poll results showing RTT latency."""
        self._current_cycle += 1
        matrix = self._build_matrix(traffic_reports)

        # Track freshness for cells from updated node
        for report in traffic_reports:
            if report["node_id"] == updated_node:
                for peer_ip, stats in report.get("traffic", {}).items():
                    dst = self.ip_to_node.get(peer_ip)
                    if dst and stats.get("avg_rtt_us", 0) > 0:
                        self._cell_update_cycle[(report["node_id"], dst)] = self._current_cycle

        self._render_grid(matrix)

    def _format_cell(self, rtt_us: float, cycles_old: int) -> tuple[str, str]:
        """Format cell with RTT and color (green → yellow → red for latency)."""
        if rtt_us < 1:
            return ("       ", "on grey11")

        # Determine color based on latency thresholds
        if rtt_us < 1000:  # <1ms - Excellent (green)
            r, g, b = 0, 200, 0
        elif rtt_us < 5000:  # 1-5ms - Good (cyan)
            r, g, b = 0, 180, 180
        elif rtt_us < 10000:  # 5-10ms - OK (blue)
            r, g, b = 50, 120, 200
        elif rtt_us < 50000:  # 10-50ms - Fair (yellow)
            r, g, b = 200, 200, 0
        elif rtt_us < 100000:  # 50-100ms - Poor (orange)
            r, g, b = 220, 140, 0
        else:  # >100ms - Bad (red)
            r, g, b = 220, 0, 0

        # Apply freshness dimming
        r_dim, g_dim, b_dim = self._apply_freshness_dimming(r, g, b, cycles_old)

        return ("█" * 7, f"rgb({r_dim},{g_dim},{b_dim})")

    def _render_legend(self) -> list[Text]:
        """Render latency threshold legend."""
        lines = []
        lines.append(Text())  # Blank line

        legend = Text()
        legend.append("                  ", style="")  # Align with data (18 chars)

        # Show color blocks for each threshold
        thresholds = [
            ("<1ms", (0, 200, 0)),
            ("1-5ms", (0, 180, 180)),
            ("5-10ms", (50, 120, 200)),
            ("10-50ms", (200, 200, 0)),
            ("50-100ms", (220, 140, 0)),
            (">100ms", (220, 0, 0)),
        ]

        for label, (r, g, b) in thresholds:
            legend.append("██", style=f"rgb({r},{g},{b})")
            legend.append(f" {label} ", style="dim")

        lines.append(legend)
        return lines
# ---------------------------------------------------------------------------
# Heartbeat Freshness Matrix
# ---------------------------------------------------------------------------

class HeartbeatMatrix(BaseHeatmap):
    """Heartbeat age matrix (observer row → observed peer col)."""

    DEFAULT_CSS = """
    HeartbeatMatrix {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def _get_row_label_width(self) -> int:
        """Match TrafficHeatmap spacing."""
        return 18

    def _build_matrix(self, heartbeat_matrix: dict[str, dict[str, float]]) -> dict[tuple[str, str], float]:
        """Build matrix from heartbeat age data."""
        matrix = {}
        for observer in heartbeat_matrix:
            for observed, age in heartbeat_matrix[observer].items():
                matrix[(observer, observed)] = age
        return matrix

    def refresh_data(self, heartbeat_matrix: dict[str, dict[str, float]], updated_node: str | None = None) -> None:
        """Update matrix from heartbeat age data."""
        self._current_cycle += 1
        matrix = self._build_matrix(heartbeat_matrix)

        # Track which cells were updated
        if updated_node and updated_node in heartbeat_matrix:
            for observed in heartbeat_matrix[updated_node]:
                self._cell_update_cycle[(updated_node, observed)] = self._current_cycle

        self._render_grid(matrix)

    def _format_cell(self, age_seconds: float, cycles_old: int) -> tuple[str, str]:
        """Format cell with heartbeat age and color (green → yellow → red for staleness)."""
        if age_seconds < 1:
            return ("       ", "on grey11")

        # Determine color based on heartbeat freshness
        if age_seconds < 5:  # <5s - Fresh (green)
            r, g, b = 0, 200, 0
        elif age_seconds < 15:  # 5-15s - Slightly stale (yellow)
            r, g, b = 200, 200, 0
        elif age_seconds < 60:  # 15-60s - Stale (orange)
            r, g, b = 220, 140, 0
        elif age_seconds < 300:  # 60-300s - Very stale (red)
            r, g, b = 220, 0, 0
        else:  # >300s - Dead/unknown (dark red)
            r, g, b = 100, 0, 0

        # Apply freshness dimming
        r_dim, g_dim, b_dim = self._apply_freshness_dimming(r, g, b, cycles_old)

        return ("█" * 7, f"rgb({r_dim},{g_dim},{b_dim})")

    def _render_legend(self) -> list[Text]:
        """Render heartbeat age threshold legend."""
        lines = []
        lines.append(Text())  # Blank line

        legend = Text()
        legend.append("                  ", style="")  # Align with data (18 chars)

        # Show color blocks for each threshold
        thresholds = [
            ("<5s", (0, 200, 0)),
            ("5-15s", (200, 200, 0)),
            ("15-60s", (220, 140, 0)),
            ("1-5m", (220, 0, 0)),
            (">5m", (100, 0, 0)),
        ]

        for label, (r, g, b) in thresholds:
            legend.append("██", style=f"rgb({r},{g},{b})")
            legend.append(f" {label} ", style="dim")

        lines.append(legend)
        return lines


# ---------------------------------------------------------------------------
# Orgs table (copies + site distribution per org)
# ---------------------------------------------------------------------------

class OrgsTable(DataTable):
    """Replication breakdown by org: copies and site distribution."""

    DEFAULT_CSS = """
    OrgsTable {
        height: auto;
        max-height: 12;
        margin-bottom: 1;
    }
    """

    def __init__(self, target_copies: int = 4) -> None:
        super().__init__()
        self._target = target_copies

    def on_mount(self) -> None:
        self.add_column("Org", width=11, key="org")
        self.add_column("Total", width=7, key="total")
        self.add_column("1cp", width=6, key="cp1")
        self.add_column("2cp", width=6, key="cp2")
        self.add_column("3cp", width=6, key="cp3")
        self.add_column("≥4cp", width=7, key="cp4")
        self.add_column("1-site", width=7, key="s1")
        self.add_column("2-site", width=7, key="s2")
        self.add_column("3-site", width=7, key="s3")
        self.add_column("≥4-site", width=8, key="s4")
        self.cursor_type = "none"

    def refresh_data(self, by_org: dict) -> None:
        self.clear()
        if not by_org:
            return

        for org in sorted(by_org):
            org_data = by_org[org]
            dist = org_data.get("distribution", {})
            site_dist = org_data.get("site_distribution", {})

            total = sum(dist.values())
            cp1 = dist.get(1, 0)
            cp2 = dist.get(2, 0)
            cp3 = sum(v for k, v in dist.items() if k == 3)
            cp4 = sum(v for k, v in dist.items() if k >= 4)

            s1 = site_dist.get(1, 0)
            s2 = site_dist.get(2, 0)
            s3 = site_dist.get(3, 0)
            s4 = sum(v for k, v in site_dist.items() if k >= 4)

            def cell(n: int, style: str) -> Text:
                return Text(f"{n:,}" if n > 0 else "--", style=style if n > 0 else "dim")

            self.add_row(
                Text(org, style="bold"),
                Text(f"{total:,}"),
                cell(cp1, "red bold"),
                cell(cp2, "yellow"),
                cell(cp3, "yellow"),
                cell(cp4, "green"),
                cell(s1, "red bold"),
                cell(s2, "yellow"),
                cell(s3, "green"),
                cell(s4, "green"),
            )


# ---------------------------------------------------------------------------
# Org × node commit count table
# ---------------------------------------------------------------------------

class OrgNodeTable(DataTable):
    """Commit count matrix: org rows × node columns."""

    DEFAULT_CSS = """
    OrgNodeTable {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }
    """

    def __init__(self, peer_hosts: list[str]) -> None:
        super().__init__()
        scott = [h for h in peer_hosts if h.startswith("scott.")]
        others = sorted([h for h in peer_hosts if not h.startswith("scott.")])
        self._peer_nodes = scott + others

    def on_mount(self) -> None:
        self.add_column("Org", width=11, key="org")
        for node in self._peer_nodes:
            name = short(node)[:6]
            self.add_column(name, width=7, key=f"n_{short(node)}")
        self.cursor_type = "none"

    def refresh_data(self, by_org: dict) -> None:
        self.clear()
        if not by_org:
            return

        for org in sorted(by_org):
            org_data = by_org[org]
            by_node = org_data.get("by_node", {})
            total = sum(org_data.get("distribution", {}).values())

            row: list = [Text(org, style="bold")]
            for node in self._peer_nodes:
                count = by_node.get(node, 0)
                if count == 0:
                    row.append(Text("--", style="dim"))
                else:
                    pct = count / total if total > 0 else 0
                    style = "green" if pct >= 0.1 else "yellow"
                    row.append(Text(f"{count:,}", style=style))
            self.add_row(*row)


# ---------------------------------------------------------------------------
# Ingest overview (ntx aggregate summary)
# ---------------------------------------------------------------------------

class IngestOverview(Static):
    """Aggregate ingest summary across all ntx nodes."""

    DEFAULT_CSS = """
    IngestOverview {
        padding: 0 1;
        height: auto;
        margin-bottom: 0;
        background: $surface;
        border: tall $primary;
    }
    """

    def refresh_data(self, ntx_statuses: list[dict]) -> None:
        if not ntx_statuses:
            self.update(Text("Ingest: waiting for data...", style="dim"))
            return

        total_pending_files = sum(s["pending"]["files"] for s in ntx_statuses)
        total_pending_bytes = sum(s["pending"]["bytes"] for s in ntx_statuses)
        total_committed_files = sum(s["committed"]["files"] for s in ntx_statuses)
        total_committed_bytes = sum(s["committed"]["bytes"] for s in ntx_statuses)
        total_rate_1h = sum(
            s["throughput"]["last_1h"]["bytes_per_sec"] for s in ntx_statuses
        )

        all_healthy = all(
            s.get("health", {}).get("ingest_running", False)
            for s in ntx_statuses
        )

        lines = []
        lines.append(Text(f"{len(ntx_statuses)} ingest nodes", style="bold"))

        pend = Text()
        pend.append("Pending: ", style="")
        pend.append(f"{total_pending_files:,} files  ", style="yellow")
        pend.append(
            humanize.naturalsize(total_pending_bytes, binary=False), style="yellow",
        )
        pend.append("    Committed: ", style="")
        pend.append(f"{total_committed_files:,} files  ", style="green")
        pend.append(
            humanize.naturalsize(total_committed_bytes, binary=False), style="green",
        )
        lines.append(pend)

        tp = Text()
        tp.append("Throughput (1h): ", style="")
        tp.append(
            humanize.naturalsize(total_rate_1h, binary=False) + "/s", style="cyan",
        )
        tp.append("    Health: ", style="")
        if all_healthy:
            tp.append("OK", style="green bold")
        else:
            tp.append("DEGRADED", style="red bold")
        lines.append(tp)

        self.update(Text("\n").join(lines))


# ---------------------------------------------------------------------------
# Ingest per-node table
# ---------------------------------------------------------------------------

class IngestNodeTable(DataTable):
    """Per-node ingest metrics table."""

    DEFAULT_CSS = """
    IngestNodeTable {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }
    """

    def on_mount(self) -> None:
        self.add_column("Node", width=8, key="node")
        self.add_column("ntx ver", width=7, key="ver")
        self.add_column("Uptime", width=9, key="uptime")
        self.add_column("Pending", width=12, key="pending")
        self.add_column("Committed", width=12, key="committed")
        self.add_column("Rate 1h", width=10, key="rate_1h")
        self.add_column("Rate 24h", width=10, key="rate_24h")
        self.add_column("ETA", width=8, key="eta")
        self.add_column("Last", width=6, key="last_age")
        self.add_column("Health", width=7, key="health")
        self.cursor_type = "none"

    def refresh_data(self, ntx_statuses: list[dict]) -> None:
        self.clear()
        if not ntx_statuses:
            return

        for s in sorted(ntx_statuses, key=lambda x: x.get("node_id", "")):
            node = s.get("node_id", "?")
            health = s.get("health", {})
            running = health.get("ingest_running", False)
            last_age = health.get("last_commit_age_seconds", 0)
            eta_data = s.get("eta", {})
            eta_hrs = eta_data.get("hours_remaining")

            rate_1h = s["throughput"]["last_1h"]["bytes_per_sec"]
            rate_24h = s["throughput"]["last_24h"]["bytes_per_sec"]

            health_text = Text("OK", style="green") if running else Text("DOWN", style="red bold")

            if last_age < 120:
                last_str = f"{last_age:.0f}s"
                last_style = "green"
            elif last_age < 3600:
                last_str = f"{last_age / 60:.0f}m"
                last_style = "yellow"
            else:
                last_str = f"{last_age / 3600:.1f}h"
                last_style = "red"

            if eta_hrs is not None and eta_hrs > 0:
                if eta_hrs < 24:
                    eta_str = f"{eta_hrs:.1f}h"
                else:
                    eta_str = f"{eta_hrs / 24:.1f}d"
            else:
                eta_str = "--"

            self.add_row(
                short(node),
                s.get("version", "?"),
                fmt_uptime(s.get("uptime_seconds", 0)),
                humanize.naturalsize(s["pending"]["bytes"], binary=False),
                humanize.naturalsize(s["committed"]["bytes"], binary=False),
                humanize.naturalsize(rate_1h, binary=False) + "/s",
                humanize.naturalsize(rate_24h, binary=False) + "/s",
                eta_str,
                Text(last_str, style=last_style),
                health_text,
            )


# ---------------------------------------------------------------------------
# Ingest pipeline / OTS detail
# ---------------------------------------------------------------------------

class IngestPipeline(Static):
    """Per-node pipeline and OTS detail."""

    DEFAULT_CSS = """
    IngestPipeline {
        padding: 0 1;
        height: auto;
        margin-bottom: 1;
        border: solid green;
    }
    """

    def refresh_data(self, ntx_statuses: list[dict]) -> None:
        if not ntx_statuses:
            self.update(Text("Pipeline: waiting for data...", style="dim"))
            return

        lines = []
        for s in sorted(ntx_statuses, key=lambda x: x.get("node_id", "")):
            node = short(s.get("node_id", "?"))
            pipe = s.get("pipeline", {})
            ots = s.get("ots", {})
            staging = s.get("staging", {})
            health = s.get("health", {})

            header = Text()
            header.append(f"{node}", style="bold")
            header.append(f"  pipeline: {pipe.get('total_commits', 0):,} commits", style="")
            header.append(f"  signed: {pipe.get('signed', 0):,}", style="dim")
            lines.append(header)

            ots_line = Text()
            ots_line.append("  OTS: ", style="")
            confirmed = ots.get("confirmed", 0)
            awaiting = ots.get("awaiting_confirmation", 0)
            ots_line.append(f"{confirmed:,} confirmed", style="green")
            if awaiting > 0:
                ots_line.append(f"  {awaiting:,} awaiting", style="yellow")
                age_hrs = ots.get("oldest_unconfirmed_age_hours", 0)
                if age_hrs > 0:
                    ots_line.append(f" (oldest: {age_hrs:.1f}h)", style="dim")
            lines.append(ots_line)

            stg_line = Text()
            stg_line.append("  Staging: ", style="")
            stg_line.append(f"{staging.get('commit_dirs', 0):,} dirs", style="")
            stg_line.append(f"  {staging.get('human', '?')}", style="dim")
            errors = health.get("errors_24h", 0)
            if errors > 0:
                stg_line.append(f"  errors(24h): {errors}", style="red bold")
            lines.append(stg_line)

            lines.append(Text(""))  # blank separator between nodes

        # Remove trailing blank line
        if lines and lines[-1].plain == "":
            lines.pop()

        self.update(Text("\n").join(lines))
