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
    NodeDataStore,
    fetch_node_all,
    load_config,
    load_tailscale_ip_map,
    poll_cluster,
    poll_traffic_matrix,
)
from tfcs_tui.widgets import (
    NodesTable,
    ReplicationChart,
    ReplicationVelocity,
    TrafficHeatmap,
    TrafficMatrixTable,
    TransfersTable,
)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class NodeUpdated(Message):
    """Posted when a single node poll completes."""
    def __init__(self, updated_node: str) -> None:
        super().__init__()
        self.updated_node = updated_node


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
        self._store = NodeDataStore()

        # Rolling updates (one node at a time)
        self._current_node_index = 0

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
                yield ReplicationVelocity(self._target_copies)
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
            self.set_interval(1.0, self._poll_next_node)

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
            # Populate the datastore
            for s in STATUSES:
                self._store.update_node(s["node_id"], status=s, traffic=None)
            for r in TRAFFIC_REPORTS:
                self._store.update_node(r["node_id"], status=None, traffic=r)
            self._store.update_global(NODE_STATUS, HEARTBEAT_AGE, REPLICATION)
            self.post_message(NodeUpdated(updated_node="mock"))
        else:
            # Full burst refresh using existing poll functions
            async def do_full_refresh():
                statuses, node_status, heartbeat_age, replication = await poll_cluster(
                    self._peer_hosts, self._http_port, self._target_copies
                )
                traffic_reports = await poll_traffic_matrix(
                    self._peer_hosts, self._http_port
                )

                # Populate datastore
                for status in statuses:
                    node_id = status.get("node_id")
                    if node_id:
                        self._store.update_node(node_id, status, None)

                for traffic in traffic_reports:
                    node_id = traffic.get("node_id")
                    if node_id:
                        # Merge with existing node or create new
                        self._store.update_node(node_id, None, traffic)

                self._store.update_global(node_status, heartbeat_age, replication)
                self.post_message(NodeUpdated(updated_node="refresh"))

            self.run_worker(do_full_refresh, exclusive=False)

    def _poll_next_node(self) -> None:
        """Poll next node in rolling sequence (1 node per second)."""
        if not self._peer_hosts:
            return

        host = self._peer_hosts[self._current_node_index]
        include_global = (self._current_node_index == 0)  # Fetch global data on first node
        self._current_node_index = (self._current_node_index + 1) % len(self._peer_hosts)

        async def do_poll():
            await self._do_poll(host, include_global)

        self.run_worker(do_poll, exclusive=False)

    async def _do_poll(self, host: str, include_global: bool) -> None:
        """Background worker: poll single node for all endpoints."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            status, traffic, nodes_list, replication = await fetch_node_all(
                session, host, self._http_port, include_global, self._target_copies
            )

            # Extract node_id from status or traffic
            node_id = None
            if status:
                node_id = status.get("node_id")
            elif traffic:
                node_id = traffic.get("node_id")

            if not node_id:
                return

            # Update datastore
            self._store.update_node(node_id, status, traffic)

            if include_global and nodes_list is not None and replication is not None:
                # Parse nodes_list into node_status and heartbeat_age dicts
                node_status = {}
                heartbeat_age = {}
                for node_info in nodes_list:
                    nid = node_info.get("node_id")
                    if nid:
                        node_status[nid] = node_info.get("status", "unknown")
                        heartbeat_age[nid] = node_info.get("heartbeat_age_seconds", 0.0)

                self._store.update_global(node_status, heartbeat_age, replication)

            self.post_message(NodeUpdated(updated_node=node_id))

    def on_node_updated(self, message: NodeUpdated) -> None:
        """Update ALL widgets from the datastore."""
        import time
        store = self._store

        # Overview widgets
        self.query_one(ReplicationChart).refresh_data(store.replication, self._target_copies)
        self.query_one(ReplicationVelocity).refresh_data(store.replication, timestamp=time.time())
        self.query_one(NodesTable).refresh_data(store.statuses, store.node_status, store.heartbeat_age)
        self.query_one(TransfersTable).refresh_data(store.statuses)

        # Traffic widgets
        self.query_one(TrafficMatrixTable).refresh_data(store.traffic_reports)
        self.query_one(TrafficHeatmap).refresh_data(store.traffic_reports, message.updated_node)

        # Update title bar
        self._update_title_bar()

    def _update_title_bar(self) -> None:
        """Update title bar based on active tab."""
        active_tab = self.query_one(TabbedContent).active
        title_bar = self.query_one("#title-bar", Static)

        if active_tab == "tab-overview":
            n_nodes = len(self._store.statuses)
            title_bar.update(f" tfcs cluster dashboard    {n_nodes} nodes")
        elif active_tab == "tab-traffic":
            n_reporting = len(self._store.traffic_reports)
            title_bar.update(
                f" tfcs traffic matrix    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )
        elif active_tab == "tab-heatmap":
            n_reporting = len(self._store.traffic_reports)
            title_bar.update(
                f" tfcs traffic heatmap    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )

    def action_tab_overview(self) -> None:
        """Switch to overview tab."""
        self.query_one(TabbedContent).active = "tab-overview"
        self._update_title_bar()

    def action_tab_traffic(self) -> None:
        """Switch to traffic tab."""
        self.query_one(TabbedContent).active = "tab-traffic"
        self._update_title_bar()

    def action_tab_heatmap(self) -> None:
        """Switch to heatmap tab."""
        self.query_one(TabbedContent).active = "tab-heatmap"
        self._update_title_bar()

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
