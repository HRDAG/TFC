# Author: PB and Codex
# Date: 2026-05-21
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
from tfcs_fleet_tui.model import ABSENT, MISSING, Cell, FleetNode, FleetSnapshot
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
        self._has_rendered_snapshot = False
        self._last_freshness = self._unknown_freshness()
        self._last_loads = self._unknown_values()
        self._last_cpu_temps = self._unknown_values()
        self._last_hdd_temps = self._unknown_values()
        self._last_nvme_temps = self._unknown_values()
        self._last_nic_temps = self._unknown_values()
        self._last_filesystems = self._unknown_filesystems()
        self._last_pulls: dict[str, str] = {name: "?" for name in self._config.hosts}

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
                    pulls=self._last_pulls,
                    prom_status="freshness=checking, load=checking, cpu=checking",
                )
            )

        async def refresh_from_prometheus() -> None:
            hosts = self._config.hosts
            prom_url = self._config.prometheus_url

            freshness_status = "ok"
            load_status = "ok"
            cpu_status = "ok"
            hdd_status = "ok"
            nvme_status = "ok"
            nic_status = "ok"
            fs_status = "ok"

            try:
                self._last_freshness = await fetch_freshness(
                    prom_url, hosts, self._config.stale_after_seconds,
                )
            except Exception:
                freshness_status = "unreachable"
            try:
                self._last_loads = await fetch_load(prom_url, hosts)
            except Exception:
                load_status = "unreachable"
            try:
                self._last_cpu_temps = await fetch_cpu_temps(prom_url, hosts)
            except Exception:
                cpu_status = "unreachable"
            try:
                self._last_hdd_temps = await fetch_hdd_temps(prom_url, hosts)
            except Exception:
                hdd_status = "unreachable"
            try:
                self._last_nvme_temps = await fetch_nvme_temps(prom_url, hosts)
            except Exception:
                nvme_status = "unreachable"
            try:
                self._last_nic_temps = await fetch_nic_temps(prom_url, hosts)
            except Exception:
                nic_status = "unreachable"
            try:
                self._last_filesystems = await fetch_filesystems(prom_url, hosts)
            except Exception:
                fs_status = "unreachable"

            self._render_snapshot(
                self._build_snapshot(
                    freshness=self._last_freshness,
                    loads=self._last_loads,
                    cpu_temps=self._last_cpu_temps,
                    hdd_temps=self._last_hdd_temps,
                    nvme_temps=self._last_nvme_temps,
                    nic_temps=self._last_nic_temps,
                    filesystems=self._last_filesystems,
                    pulls=self._last_pulls,
                    prom_status=self._status_line(
                        freshness_status, load_status, cpu_status,
                        hdd_status, nvme_status, nic_status, fs_status,
                        "checking",
                    ),
                )
            )

            tfcs_status = "ok"
            tfcs_fqdns = tuple(
                h.tfcs_status for h in hosts.values() if h.tfcs_status
            )
            try:
                pull_summaries = await fetch_pull_summaries(
                    tfcs_fqdns, self._config.tfcs_port, timeout_seconds=1,
                )
                self._last_pulls = {
                    name: format_pull_summary(pull_summaries.get(name))
                    for name in hosts
                }
            except Exception:
                tfcs_status = "unreachable"

            self.query_one(FleetTable).update_pulls(
                {name: Cell.from_str(value) for name, value in self._last_pulls.items()}
            )
            self._update_source_bar(
                self._status_line(
                    freshness_status, load_status, cpu_status,
                    hdd_status, nvme_status, nic_status, fs_status,
                    tfcs_status,
                )
            )

        self.run_worker(refresh_from_prometheus, exclusive=True)

    def _unknown_freshness(self) -> dict[str, HostFreshness]:
        return {
            name: HostFreshness(up="?", last_update="?")
            for name in self._config.hosts
        }

    def _unknown_values(self) -> dict[str, str]:
        return {name: "?" for name in self._config.hosts}

    def _unknown_filesystems(self) -> dict[str, dict[str, str]]:
        return {name: {"root": "?", "data": "?"} for name in self._config.hosts}

    def _build_snapshot(
        self,
        freshness: dict[str, HostFreshness],
        prom_status: str,
        loads: dict[str, str],
        cpu_temps: dict[str, str],
        hdd_temps: dict[str, str],
        nvme_temps: dict[str, str],
        nic_temps: dict[str, str],
        filesystems: dict[str, dict[str, str]],
        pulls: dict[str, str],
    ) -> FleetSnapshot:
        nodes = []
        for name in self._config.hosts:
            fresh = freshness.get(name)
            fs = filesystems.get(name, {})
            cells = (
                Cell.from_str(fresh.last_update if fresh else "?"),
                Cell.from_str(fresh.up if fresh else "?"),
                Cell.from_str(loads.get(name, "?")),
                Cell.from_str(cpu_temps.get(name, "?")),
                Cell.from_str(hdd_temps.get(name, "?")),
                Cell.from_str(nvme_temps.get(name, "?")),
                Cell.from_str(nic_temps.get(name, "?")),
                Cell.from_str(fs.get("root", "?")),
                Cell.from_str(fs.get("data", "?")),
                Cell.from_str(pulls.get(name, "?")),
            )
            note = ""
            if all(cell.status == "missing" for cell in cells):
                note = "no prom data"
            (last_update, up, load, cpu, hdd, nvme, nic, root, data, pulls_cell) = cells
            nodes.append(
                FleetNode(
                    host=name,
                    last_update=last_update,
                    up=up,
                    load=load,
                    cpu_temp=cpu,
                    hdd_temp=hdd,
                    ssd_temp=ABSENT,
                    nvme_temp=nvme,
                    nic=nic,
                    root=root,
                    data=data,
                    pulls=pulls_cell,
                    note=note,
                )
            )
        return FleetSnapshot(
            nodes=tuple(nodes),
            source=prom_status,
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
            freshness_status, load_status, cpu_status,
            hdd_status, nvme_status, nic_status, fs_status,
        )
        if all(status == "unreachable" for status in prom_statuses):
            return (
                f"PROMETHEUS UNREACHABLE at {self._config.prometheus_url}; "
                f"tfcs={tfcs_status}"
            )
        return (
            f"freshness={freshness_status}, load={load_status}, "
            f"cpu={cpu_status}, hdd={hdd_status}, "
            f"nvme={nvme_status}, nic={nic_status}, fs={fs_status}, "
            f"tfcs={tfcs_status}"
        )

    def _update_source_bar(self, source: str) -> None:
        self.query_one("#source-bar", Static).update(
            f" source: {source}    prom: {self._config.prometheus_url}"
        )


def main() -> None:
    FleetDashboard(load_config()).run()


if __name__ == "__main__":
    main()
