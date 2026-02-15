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
from textual.widgets import Footer, Header, Static

from tfcs_tui.data import DEFAULT_CONFIG, load_config, poll_cluster
from tfcs_tui.widgets import NodesTable, ReplicationChart, TransfersTable


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


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TfcsDashboard(App):
    """Cluster dashboard TUI — window 1."""

    TITLE = "tfcs dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "window_1", "Overview", show=False),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="title-bar")
        yield ReplicationChart()
        yield NodesTable()
        yield TransfersTable()
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        if not self._mock:
            self.set_interval(self._refresh_seconds, self.action_refresh)

    def action_refresh(self) -> None:
        """Poll cluster (or load mock data) and update widgets."""
        if self._mock:
            from tfcs_tui.mock import HEARTBEAT_AGE, NODE_STATUS, REPLICATION, STATUSES
            self.post_message(ClusterData(STATUSES, NODE_STATUS, HEARTBEAT_AGE, REPLICATION))
        else:
            self.run_worker(self._poll, exclusive=True)

    async def _poll(self) -> None:
        """Background worker: poll cluster endpoints."""
        statuses, node_status, heartbeat_age, replication = await poll_cluster(
            self._peer_hosts, self._http_port, self._target_copies,
        )
        self.post_message(ClusterData(statuses, node_status, heartbeat_age, replication))

    def on_cluster_data(self, message: ClusterData) -> None:
        """Update all widgets with fresh cluster data."""
        statuses = message.statuses
        node_status = message.node_status
        heartbeat_age = message.heartbeat_age
        replication = message.replication

        # Title bar
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

    def action_window_1(self) -> None:
        """Switch to window 1 (current — no-op for now)."""
        pass

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
