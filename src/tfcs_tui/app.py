# Author: PB and Claude
# Date: 2026-02-14
# License: (c) HRDAG, 2025, GPL-2 or newer
#
# ---
# src/tfcs_tui/app.py

"""tfcs cluster dashboard — textual TUI app.

Production: tfcs-tui                                (reads /etc/hrdag/tfcs-tui.toml)
Dev:        tfcs-tui -c config/tfcs-tui.toml
Mock:       tfcs-tui --mock
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from tfcs_tui.data import (
    DEFAULT_CONFIG,
    load_config,
    load_tailscale_ip_map,
    poll_cluster,
    poll_traffic_matrix,
)
from tfcs_tui.widgets import (
    NodesTable,
    ReplicationChart,
    TrafficHeatmap,
    TrafficMatrixTable,
    TransfersTable,
)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class ClusterData(Message):
    """Posted when a poll completes with new cluster data."""

    def __init__(
        self,
        statuses: list[dict],
        node_status: dict[str, str],
        heartbeat_age: dict[str, float],
        replication: dict[int, int],
    ) -> None:
        super().__init__()
        self.statuses = statuses
        self.node_status = node_status
        self.heartbeat_age = heartbeat_age
        self.replication = replication


class TrafficData(Message):
    """Posted when traffic matrix poll completes."""

    def __init__(self, reports: list[dict]) -> None:
        super().__init__()
        self.reports = reports


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TfcsDashboard(App):
    """Cluster dashboard TUI — window 1."""

    TITLE = "tfcs dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_overview", "Overview", show=False),
        Binding("2", "tab_traffic", "Traffic", show=False),
        Binding("3", "tab_heatmap", "Heatmap", show=False),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    Screen {
        layout: vertical;
    }
    #title-bar {
        background: blue;
        color: white;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    """

    def __init__(
        self,
        peer_hosts: list[str] | None = None,
        http_port: int = 8099,
        target_copies: int = 3,
        refresh_seconds: int = 10,
        mock: bool = False,
    ) -> None:
        super().__init__()
        self._peer_hosts = peer_hosts or []
        self._http_port = http_port
        self._target_copies = target_copies
        self._refresh_seconds = refresh_seconds
        self._mock = mock

        # Rolling traffic updates (one node at a time)
        self._current_node_index = 0
        self._traffic_data: dict[str, dict] = {}  # Accumulated traffic reports

        # Load IP to hostname mapping from tailscale
        if mock:
            from tfcs_tui.mock import IP_MAP
            self._ip_map = IP_MAP
        else:
            self._ip_map = load_tailscale_ip_map(self._peer_hosts)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="title-bar")
        with TabbedContent(initial="tab-overview"):
            with TabPane("Overview", id="tab-overview"):
                yield ReplicationChart()
                yield NodesTable()
                yield TransfersTable()
            with TabPane("Traffic", id="tab-traffic"):
                yield TrafficMatrixTable(self._peer_hosts, self._ip_map)
            with TabPane("Heatmap", id="tab-heatmap"):
                yield TrafficHeatmap(self._peer_hosts, self._ip_map)
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        if not self._mock:
            # Cluster data (status, nodes, replication) every N seconds
            self.set_interval(self._refresh_seconds, self._refresh_cluster)
            # Traffic data: one node per second (rolling updates)
            self.set_interval(1.0, self._refresh_traffic_single_node)

    def action_refresh(self) -> None:
        """Initial refresh on startup (or manual refresh with 'r' key)."""
        if self._mock:
            from tfcs_tui.mock import (
                HEARTBEAT_AGE,
                NODE_STATUS,
                REPLICATION,
                STATUSES,
                TRAFFIC_REPORTS,
            )
            self.post_message(ClusterData(STATUSES, NODE_STATUS, HEARTBEAT_AGE, REPLICATION))
            self.post_message(TrafficData(TRAFFIC_REPORTS))
        else:
            self._refresh_cluster()
            self._refresh_traffic_single_node()

    def _refresh_cluster(self) -> None:
        """Poll cluster data (status, nodes, replication)."""
        self.run_worker(self._poll_cluster, exclusive=False)

    def _refresh_traffic_single_node(self) -> None:
        """Poll traffic from one node (rolling updates)."""
        if not self._peer_hosts:
            return

        # Get next node to poll
        host = self._peer_hosts[self._current_node_index]
        self._current_node_index = (self._current_node_index + 1) % len(self._peer_hosts)

        # Spawn worker to fetch from this node
        async def poll_this_node():
            await self._poll_traffic_single(host)

        self.run_worker(poll_this_node, exclusive=False)

    async def _poll_cluster(self) -> None:
        """Background worker: poll cluster endpoints."""
        statuses, node_status, heartbeat_age, replication = await poll_cluster(
            self._peer_hosts, self._http_port, self._target_copies,
        )
        self.post_message(ClusterData(statuses, node_status, heartbeat_age, replication))

    async def _poll_traffic_single(self, host: str) -> None:
        """Background worker: poll traffic from a single node."""
        from tfcs_tui.data import fetch_node_traffic
        import aiohttp

        async with aiohttp.ClientSession() as session:
            report = await fetch_node_traffic(session, host, self._http_port)
            if report:
                # Update accumulated data
                node_id = report["node_id"]
                self._traffic_data[node_id] = report

                # Post message with all accumulated reports
                reports = list(self._traffic_data.values())
                self.post_message(TrafficData(reports))

    def on_cluster_data(self, message: ClusterData) -> None:
        """Update all widgets with fresh cluster data."""
        statuses = message.statuses
        node_status = message.node_status
        heartbeat_age = message.heartbeat_age
        replication = message.replication

        # Update title bar (only if on overview tab)
        active_tab = self.query_one(TabbedContent).active
        if active_tab == "tab-overview":
            n_nodes = len(statuses)
            title_bar = self.query_one("#title-bar", Static)
            title_bar.update(
                f" tfcs cluster dashboard    {n_nodes} nodes"
            )

        # Widgets
        self.query_one(ReplicationChart).refresh_data(
            replication, self._target_copies,
        )
        self.query_one(NodesTable).refresh_data(statuses, node_status, heartbeat_age)
        self.query_one(TransfersTable).refresh_data(statuses)

    def on_traffic_data(self, message: TrafficData) -> None:
        """Update traffic matrix and heatmap with fresh data."""
        reports = message.reports

        # Update title bar based on active tab
        active_tab = self.query_one(TabbedContent).active
        if active_tab == "tab-traffic":
            n_reporting = len(reports)
            title_bar = self.query_one("#title-bar", Static)
            title_bar.update(
                f" tfcs traffic matrix    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )
        elif active_tab == "tab-heatmap":
            n_reporting = len(reports)
            title_bar = self.query_one("#title-bar", Static)
            title_bar.update(
                f" tfcs traffic heatmap    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )

        # Update both traffic views
        self.query_one(TrafficMatrixTable).refresh_data(reports)
        self.query_one(TrafficHeatmap).refresh_data(reports)

    def action_tab_overview(self) -> None:
        """Switch to overview tab."""
        self.query_one(TabbedContent).active = "tab-overview"
        # Update title bar for overview
        title_bar = self.query_one("#title-bar", Static)
        title_bar.update(" tfcs cluster dashboard")

    def action_tab_traffic(self) -> None:
        """Switch to traffic tab."""
        self.query_one(TabbedContent).active = "tab-traffic"
        # Update title bar for traffic
        title_bar = self.query_one("#title-bar", Static)
        title_bar.update(" tfcs traffic matrix")

    def action_tab_heatmap(self) -> None:
        """Switch to heatmap tab."""
        self.query_one(TabbedContent).active = "tab-heatmap"
        # Update title bar for heatmap
        title_bar = self.query_one("#title-bar", Static)
        title_bar.update(" tfcs traffic heatmap")

    def action_scroll_down(self) -> None:
        table = self.query_one(TransfersTable)
        table.scroll_down()

    def action_scroll_up(self) -> None:
        table = self.query_one(TransfersTable)
        table.scroll_up()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="tfcs cluster dashboard TUI")
    p.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG,
                   help=f"Path to TOML config (default: {DEFAULT_CONFIG})")
    p.add_argument("--mock", action="store_true",
                   help="Use built-in mock data")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.mock:
        app = TfcsDashboard(mock=True)
    else:
        if not args.config.exists():
            print(f"Config not found: {args.config}", file=sys.stderr)
            sys.exit(1)
        cfg = load_config(args.config)
        app = TfcsDashboard(
            peer_hosts=cfg["peer_hosts"],
            http_port=cfg["http_port"],
            target_copies=cfg["target_copies"],
            refresh_seconds=cfg["refresh_seconds"],
        )

    app.run()


if __name__ == "__main__":
    main()
