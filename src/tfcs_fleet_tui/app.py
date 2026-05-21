# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/app.py

"""TFC fleet health dashboard."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from tfcs_fleet_tui.config import FleetConfig, load_config
from tfcs_fleet_tui.mock_data import MOCK_SNAPSHOT
from tfcs_fleet_tui.model import Cell, FleetNode, FleetSnapshot
from tfcs_fleet_tui.prometheus import (
    HostFreshness,
    fetch_cpu_temps,
    fetch_filesystems,
    fetch_freshness,
    fetch_hdd_temps,
    fetch_load,
    fetch_nic_temps,
    fetch_nvme_temps,
)
from tfcs_fleet_tui.tfcs import fetch_pull_summaries, format_pull_summary
from tfcs_fleet_tui.widgets import FleetTable


class FleetDashboard(App):
    """Fleet dashboard TUI."""

    TITLE = "tfcs fleet dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
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
        self._has_rendered_snapshot = False
        self._last_freshness = self._unknown_freshness()
        self._last_loads = self._unknown_values()
        self._last_cpu_temps = self._unknown_values()
        self._last_hdd_temps = self._unknown_values()
        self._last_nvme_temps = self._unknown_values()
        self._last_nic_temps = self._unknown_values()
        self._last_filesystems = self._unknown_filesystems()
        self._last_pulls = self._unknown_values()

    def on_mount(self) -> None:
        self.action_refresh()
        self.set_interval(self._config.refresh_seconds, self.action_refresh)

    def action_refresh(self) -> None:
        if not self._has_rendered_snapshot:
            self._render_snapshot(
                self._build_snapshot(
                    freshness=self._unknown_freshness(),
                    loads=self._unknown_values(),
                    cpu_temps=self._unknown_values(),
                    hdd_temps=self._unknown_values(),
                    nvme_temps=self._unknown_values(),
                    nic_temps=self._unknown_values(),
                    filesystems=self._unknown_filesystems(),
                    pulls=self._unknown_values(),
                    prom_status="freshness=checking, load=checking, cpu=checking",
                )
            )

        async def refresh_from_prometheus() -> None:
            freshness_status = "ok"
            load_status = "ok"
            cpu_status = "ok"
            hdd_status = "ok"
            nvme_status = "ok"
            nic_status = "ok"
            fs_status = "ok"
            freshness = self._last_freshness
            loads = self._last_loads
            cpu_temps = self._last_cpu_temps
            hdd_temps = self._last_hdd_temps
            nvme_temps = self._last_nvme_temps
            nic_temps = self._last_nic_temps
            filesystems = self._last_filesystems
            try:
                freshness = await fetch_freshness(
                    self._config.prometheus_url,
                    self._config.host_instances,
                    self._config.stale_after_seconds,
                )
                self._last_freshness = freshness
            except Exception:
                freshness_status = "unreachable"
            try:
                loads = await fetch_load(
                    self._config.prometheus_url,
                    self._config.host_instances,
                )
                self._last_loads = loads
            except Exception:
                load_status = "unreachable"
            try:
                cpu_temps = await fetch_cpu_temps(
                    self._config.prometheus_url,
                    self._config.host_instances,
                )
                self._last_cpu_temps = cpu_temps
            except Exception:
                cpu_status = "unreachable"
            try:
                hdd_temps = await fetch_hdd_temps(
                    self._config.prometheus_url,
                    self._config.host_instances,
                    self._config.no_hdd_hosts,
                )
                self._last_hdd_temps = hdd_temps
            except Exception:
                hdd_status = "unreachable"
            try:
                nvme_temps = await fetch_nvme_temps(
                    self._config.prometheus_url,
                    self._config.host_instances,
                )
                self._last_nvme_temps = nvme_temps
            except Exception:
                nvme_status = "unreachable"
            try:
                nic_temps = await fetch_nic_temps(
                    self._config.prometheus_url,
                    self._config.host_instances,
                    self._config.no_nic_hosts,
                )
                self._last_nic_temps = nic_temps
            except Exception:
                nic_status = "unreachable"
            try:
                filesystems = await fetch_filesystems(
                    self._config.prometheus_url,
                    self._config.host_instances,
                    self._config.filesystems,
                )
                self._last_filesystems = filesystems
            except Exception:
                fs_status = "unreachable"
            self._render_snapshot(
                self._build_snapshot(
                    freshness=freshness,
                    loads=loads,
                    cpu_temps=cpu_temps,
                    hdd_temps=hdd_temps,
                    nvme_temps=nvme_temps,
                    nic_temps=nic_temps,
                    filesystems=filesystems,
                    pulls=self._last_pulls,
                    prom_status=self._status_line(
                        freshness_status,
                        load_status,
                        cpu_status,
                        hdd_status,
                        nvme_status,
                        nic_status,
                        fs_status,
                        "checking",
                    ),
                )
            )
            tfcs_status = "ok"
            try:
                pull_summaries = await fetch_pull_summaries(
                    self._config.tfcs_hosts,
                    self._config.tfcs_port,
                    timeout_seconds=1,
                )
                self._last_pulls = {
                    host: format_pull_summary(pull_summaries.get(host))
                    for host in self._config.host_instances
                }
            except Exception:
                tfcs_status = "unreachable"
            self.query_one(FleetTable).update_pulls(
                {host: Cell.from_str(value) for host, value in self._last_pulls.items()}
            )
            self._update_source_bar(
                self._status_line(
                    freshness_status,
                    load_status,
                    cpu_status,
                    hdd_status,
                    nvme_status,
                    nic_status,
                    fs_status,
                    tfcs_status,
                )
            )

        self.run_worker(refresh_from_prometheus, exclusive=True)

    def _unknown_freshness(self) -> dict[str, HostFreshness]:
        """Unknown freshness for Prometheus-backed rows."""
        return {
            host: HostFreshness(up="?", last_update="?")
            for host in self._config.host_instances
        }

    def _unknown_values(self) -> dict[str, str]:
        """Unknown values for Prometheus-backed columns."""
        return {host: "?" for host in self._config.host_instances}

    def _unknown_filesystems(self) -> dict[str, dict[str, str]]:
        """Unknown filesystem values for Prometheus-backed columns."""
        return {
            host: {"root": "?", "data": "?"}
            for host in self._config.host_instances
        }

    def _build_snapshot(
        self,
        freshness: dict[str, HostFreshness],
        prom_status: str,
        loads: dict[str, str] | None = None,
        cpu_temps: dict[str, str] | None = None,
        hdd_temps: dict[str, str] | None = None,
        nvme_temps: dict[str, str] | None = None,
        nic_temps: dict[str, str] | None = None,
        filesystems: dict[str, dict[str, str]] | None = None,
        pulls: dict[str, str] | None = None,
    ) -> FleetSnapshot:
        fixture_by_host = {node.host: node for node in MOCK_SNAPSHOT.nodes}
        loads = loads or {}
        cpu_temps = cpu_temps or {}
        hdd_temps = hdd_temps or {}
        nvme_temps = nvme_temps or {}
        nic_temps = nic_temps or {}
        filesystems = filesystems or {}
        pulls = pulls or {}
        nodes = []
        for host in self._config.host_instances:
            fixture = fixture_by_host.get(host, FleetNode(host=host))
            fresh = freshness.get(host)
            fs = filesystems.get(host, {})
            prom_values = (
                fresh.last_update if fresh else "?",
                fresh.up if fresh else "?",
                loads.get(host, "?"),
                cpu_temps.get(host, "?"),
                hdd_temps.get(host, "?"),
                nvme_temps.get(host, "?"),
                nic_temps.get(host, "?"),
                fs.get("root", "?"),
                fs.get("data", "?"),
            )
            note = fixture.note
            if not note and all(value == "?" for value in prom_values):
                note = "no prom data"
            nodes.append(
                FleetNode(
                    host=host,
                    roles=fixture.roles,
                    last_update=Cell.from_str(prom_values[0]),
                    up=Cell.from_str(prom_values[1]),
                    load=Cell.from_str(prom_values[2]),
                    cpu_temp=Cell.from_str(prom_values[3]),
                    hdd_temp=Cell.from_str(prom_values[4]),
                    ssd_temp=fixture.ssd_temp,
                    nvme_temp=Cell.from_str(prom_values[5]),
                    nic=Cell.from_str(prom_values[6]),
                    root=Cell.from_str(prom_values[7]),
                    data=Cell.from_str(prom_values[8]),
                    pulls=Cell.from_str(pulls.get(host, "?")),
                    note=note,
                )
            )
        return FleetSnapshot(
            nodes=tuple(nodes),
            source=f"{MOCK_SNAPSHOT.source}; {prom_status}",
            refresh_seconds=self._config.refresh_seconds,
            stale_after_seconds=self._config.stale_after_seconds,
        )

    def _render_snapshot(self, snapshot: FleetSnapshot) -> None:
        self._has_rendered_snapshot = True
        self.query_one("#title-bar", Static).update(
            f" tfcs fleet dashboard    {len(snapshot.nodes)} hosts"
        )
        self._update_source_bar(snapshot.source)
        self.query_one(FleetTable).refresh_data(snapshot)

    def _status_line(
        self,
        freshness_status: str,
        load_status: str,
        cpu_status: str,
        hdd_status: str,
        nvme_status: str,
        nic_status: str,
        fs_status: str,
        tfcs_status: str,
    ) -> str:
        """Build a compact data source status line."""
        prom_statuses = (
            freshness_status,
            load_status,
            cpu_status,
            hdd_status,
            nvme_status,
            nic_status,
            fs_status,
        )
        if all(status == "unreachable" for status in prom_statuses):
            return f"PROMETHEUS UNREACHABLE at {self._config.prometheus_url}; tfcs={tfcs_status}"
        return (
            f"freshness={freshness_status}, load={load_status}, "
            f"cpu={cpu_status}, hdd={hdd_status}, "
            f"nvme={nvme_status}, nic={nic_status}, fs={fs_status}, "
            f"tfcs={tfcs_status}"
        )

    def _update_source_bar(self, source: str) -> None:
        """Update the dashboard source/status line."""
        self.query_one("#source-bar", Static).update(
            f" source: {source}    prom: {self._config.prometheus_url}"
        )


def main() -> None:
    FleetDashboard(load_config()).run()


if __name__ == "__main__":
    main()
