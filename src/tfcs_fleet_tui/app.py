# Author: PB and Codex
# Date: 2026-05-21
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/app.py

"""TFC fleet health dashboard."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from tfcs_fleet_tui.config import FleetConfig, load_config
from tfcs_fleet_tui.model import FleetSnapshot
from tfcs_fleet_tui.source import FleetDataSource, PROM_STATUS_KEYS
from tfcs_fleet_tui.widgets import FleetTable


class FleetDashboard(App):
    """Fleet dashboard TUI."""

    TITLE = "tfcs fleet dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    Screen { layout: vertical; }
    #title-bar {
        background: blue;
        color: white;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    #source-bar {
        color: $text-muted;
        padding: 0 1;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="title-bar")
        yield Static("", id="source-bar")
        yield FleetTable()
        yield Footer()

    def __init__(self, config: FleetConfig) -> None:
        super().__init__()
        self._config = config
        self._source = FleetDataSource(config)
        self._has_rendered_snapshot = False

    def on_mount(self) -> None:
        self.action_refresh()
        self.set_interval(self._config.refresh_seconds, self.action_refresh)

    def action_refresh(self) -> None:
        if not self._has_rendered_snapshot:
            self._render_snapshot(self._build_snapshot(
                prom_status_line=self._source.status_line(
                    {k: "checking" for k in PROM_STATUS_KEYS}, "checking",
                ),
            ))

        self.run_worker(self._refresh, exclusive=True)

    async def _refresh(self) -> None:
        statuses, _ = await asyncio.gather(
            self._source.refresh_prometheus(),
            self._source.refresh_oob(),
        )

        self._render_snapshot(self._build_snapshot(
            prom_status_line=self._source.status_line(statuses, "checking"),
        ))

        tfcs_status = await self._source.refresh_pulls()

        self.query_one(FleetTable).update_pulls(self._source.last.get("pulls", {}))
        self._update_source_bar(self._source.status_line(statuses, tfcs_status))

    def _build_snapshot(self, prom_status_line: str) -> FleetSnapshot:
        return self._source.build_snapshot(prom_status_line)

    def _render_snapshot(self, snapshot: FleetSnapshot) -> None:
        self._has_rendered_snapshot = True
        self.query_one("#title-bar", Static).update(
            f" tfcs fleet dashboard    {len(snapshot.nodes)} hosts"
        )
        self._update_source_bar(snapshot.source)
        self.query_one(FleetTable).refresh_data(snapshot)

    def _update_source_bar(self, source: str) -> None:
        self.query_one("#source-bar", Static).update(
            f" source: {source}    prom: {self._config.prometheus_url}"
        )


def main() -> None:
    FleetDashboard(load_config()).run()


if __name__ == "__main__":
    main()
