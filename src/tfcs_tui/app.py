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
    load_velocity_history,
    poll_cluster,
    poll_traffic_matrix,
    save_snapshot,
    short,
)
from tfcs_tui.widgets import (
    ClusterOverview,
    HeartbeatMatrix,
    LatencyHeatmap,
    NodesTable,
    ReplicationChart,
    ReplicationVelocity,
    SourceUtilization,
    TrafficHeatmap,
    TransfersTable,
    VelocityChart,
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
        Binding("1", "tab_replication", "Replication", show=False),
        Binding("2", "tab_nodes", "Nodes", show=False),
        Binding("3", "tab_traffic", "Traffic", show=False),
        Binding("4", "tab_latency", "Latency", show=False),
        Binding("5", "tab_heartbeats", "Heartbeats", show=False),
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

        # Snapshot persistence (real mode only)
        if not mock:
            self._velocity_history = load_velocity_history()
        else:
            self._velocity_history = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="title-bar")
        with TabbedContent(initial="tab-replication"):
            with TabPane("Replication", id="tab-replication"):
                yield ClusterOverview(self._target_copies)
                yield ReplicationChart()
                yield ReplicationVelocity()
                yield VelocityChart()
            with TabPane("Nodes", id="tab-nodes"):
                yield NodesTable()
                yield SourceUtilization()
                yield TransfersTable()
            with TabPane("Traffic", id="tab-traffic"):
                yield TrafficHeatmap(self._peer_hosts, self._ip_map)
            with TabPane("Latency", id="tab-latency"):
                yield LatencyHeatmap(self._peer_hosts, self._ip_map)
            with TabPane("Heartbeats", id="tab-heartbeats"):
                yield HeartbeatMatrix(self._peer_hosts)
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
                HEARTBEAT_MATRIX,
                MOCK_VELOCITY,
                MOCK_VELOCITY_HISTORY,
                NODE_STATUS,
                REPLICATION,
                SITE_DISTRIBUTION,
                STATUSES,
                TRAFFIC_REPORTS,
            )
            # Populate the datastore
            for s in STATUSES:
                self._store.update_node(s["node_id"], status=s, traffic=None)
            for r in TRAFFIC_REPORTS:
                self._store.update_node(r["node_id"], status=None, traffic=r)
            self._store.update_global(NODE_STATUS, HEARTBEAT_AGE, REPLICATION, HEARTBEAT_MATRIX,
                                      velocity=MOCK_VELOCITY,
                                      site_distribution=SITE_DISTRIBUTION)

            # Set velocity history for chart
            self._velocity_history = list(MOCK_VELOCITY_HISTORY)

            self.post_message(NodeUpdated(updated_node="mock"))
        else:
            # Full burst refresh using existing poll functions
            async def do_full_refresh():
                statuses, node_status, heartbeat_age, replication, velocity, site_dist, sole_holders = await poll_cluster(
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

                self._store.update_global(node_status, heartbeat_age, replication,
                                          velocity=velocity,
                                          site_distribution=site_dist,
                                          cluster_sole_holders=sole_holders)
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
            status, traffic, nodes_list, replication, velocity, site_dist, sole_holders = await fetch_node_all(
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

                # Fetch heartbeat matrix from all peers
                from tfcs_tui.data import fetch_heartbeat_matrix
                hb_matrix = await fetch_heartbeat_matrix(self._peer_hosts, self._http_port, session)

                self._store.update_global(node_status, heartbeat_age, replication, hb_matrix,
                                          velocity=velocity,
                                          site_distribution=site_dist,
                                          cluster_sole_holders=sole_holders)

            self.post_message(NodeUpdated(updated_node=node_id))

    def on_node_updated(self, message: NodeUpdated) -> None:
        """Update ALL widgets from the datastore."""
        import time
        store = self._store

        # --- Replication tab (Tab 1) ---
        self.query_one(ReplicationChart).refresh_data(
            store.replication, self._target_copies, store.site_distribution,
        )

        # Server-supplied velocity (from /replication?window=N)
        vel = store.velocity
        self.query_one(ReplicationVelocity).refresh_data(vel)

        # Build vel_data for ClusterOverview: server velocity + TUI-computed ETA
        vel_data: dict | None = None
        if vel is not None:
            cpm = vel.get("copies_per_min", 0)
            if cpm > 0:
                repl = store.replication
                target = self._target_copies
                below_target_copies = sum(k * v for k, v in repl.items() if k < target)
                below_target_count = sum(v for k, v in repl.items() if k < target)
                eta_min = None
                if below_target_count > 0:
                    copies_needed = target * below_target_count - below_target_copies
                    eta_min = round(copies_needed / cpm, 1)
                vel_data = {**vel, "eta_satisfied_min": eta_min}

        # Compute per-node sole_holder_count map for ClusterOverview alarm
        sole_holder_nodes = {
            short(s["node_id"]): s.get("sole_holder_count", 0)
            for s in store.statuses
            if s.get("sole_holder_count", 0) > 0
        }

        self.query_one(ClusterOverview).refresh_data(
            store.replication, store.node_status, vel_data,
            store.site_distribution, sole_holder_nodes,
        )

        if not self._mock and vel_data is not None:
            from datetime import datetime
            save_snapshot(store.replication, vel_data, time.time())
            label = datetime.now().strftime("%H:%M")
            cpm = vel_data["copies_per_min"]
            if not self._velocity_history or self._velocity_history[-1][0] != label:
                self._velocity_history.append((label, cpm))

        self.query_one(VelocityChart).refresh_data(self._velocity_history)

        # --- Nodes tab (Tab 2) ---
        self.query_one(NodesTable).refresh_data(store.statuses, store.node_status, store.heartbeat_age)
        self.query_one(SourceUtilization).refresh_data(store.statuses)
        self.query_one(TransfersTable).refresh_data(store.statuses)

        # --- Heatmap tabs (Tabs 3-5, unchanged) ---
        self.query_one(TrafficHeatmap).refresh_data(store.traffic_reports, message.updated_node)
        self.query_one(LatencyHeatmap).refresh_data(store.traffic_reports, message.updated_node)
        self.query_one(HeartbeatMatrix).refresh_data(store.heartbeat_matrix, message.updated_node)

        # Update title bar
        self._update_title_bar()

    def _update_title_bar(self) -> None:
        """Update title bar based on active tab."""
        active_tab = self.query_one(TabbedContent).active
        title_bar = self.query_one("#title-bar", Static)

        if active_tab == "tab-replication":
            title_bar.update(" tfcs cluster dashboard")
        elif active_tab == "tab-nodes":
            n_nodes = len(self._store.statuses)
            n_transfers = sum(len(s.get("claims", [])) for s in self._store.statuses)
            title_bar.update(f" tfcs nodes    {n_nodes} nodes, {n_transfers} active transfers")
        elif active_tab == "tab-traffic":
            n_reporting = len(self._store.traffic_reports)
            title_bar.update(
                f" tfcs traffic heatmap    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )
        elif active_tab == "tab-latency":
            n_reporting = len(self._store.traffic_reports)
            title_bar.update(
                f" tfcs latency heatmap    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )
        elif active_tab == "tab-heartbeats":
            n_reporting = len(self._store.heartbeat_matrix)
            title_bar.update(
                f" tfcs heartbeat matrix    {n_reporting}/{len(self._peer_hosts)} nodes reporting"
            )

    def action_tab_replication(self) -> None:
        """Switch to replication tab."""
        self.query_one(TabbedContent).active = "tab-replication"
        self._update_title_bar()

    def action_tab_nodes(self) -> None:
        """Switch to nodes tab."""
        self.query_one(TabbedContent).active = "tab-nodes"
        self._update_title_bar()

    def action_tab_traffic(self) -> None:
        """Switch to traffic tab."""
        self.query_one(TabbedContent).active = "tab-traffic"
        self._update_title_bar()

    def action_tab_latency(self) -> None:
        """Switch to latency tab."""
        self.query_one(TabbedContent).active = "tab-latency"
        self._update_title_bar()

    def action_tab_heartbeats(self) -> None:
        """Switch to heartbeats tab."""
        self.query_one(TabbedContent).active = "tab-heartbeats"
        self._update_title_bar()

    def action_scroll_down(self) -> None:
        # Scrolls TransfersTable regardless of active tab (harmless when off-screen)
        table = self.query_one(TransfersTable)
        table.scroll_down()

    def action_scroll_up(self) -> None:
        # Scrolls TransfersTable regardless of active tab (harmless when off-screen)
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
