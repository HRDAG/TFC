# Author: PB and Codex
# Date: 2026-05-21
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/app.py

"""TFC fleet health dashboard."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static

from tfcs_fleet_tui.config import FleetConfig, Host, load_config
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
from tfcs_fleet_tui.tfcs import fetch_pull_summaries, pull_cell
from tfcs_fleet_tui.widgets import FleetTable


FetchFn = Callable[[str, dict[str, Host], FleetConfig], Awaitable[Any]]


@dataclass(frozen=True)
class MetricFetch:
    """One prom-backed metric: short status name, last-value attribute, fetcher."""

    status_key: str         # appears in the source-bar status line
    last_attr: str          # self._last_<last_attr> caches the result
    factory: FetchFn


_PROM_FETCHES: tuple[MetricFetch, ...] = (
    MetricFetch("freshness", "freshness",
                lambda u, h, c: fetch_freshness(u, h, c.stale_after_seconds)),
    MetricFetch("load",      "loads",       lambda u, h, c: fetch_load(u, h)),
    MetricFetch("cpu",       "cpu_temps",   lambda u, h, c: fetch_cpu_temps(u, h)),
    MetricFetch("hdd",       "hdd_temps",   lambda u, h, c: fetch_hdd_temps(u, h)),
    MetricFetch("nvme",      "nvme_temps",  lambda u, h, c: fetch_nvme_temps(u, h)),
    MetricFetch("nic",       "nic_temps",   lambda u, h, c: fetch_nic_temps(u, h)),
    MetricFetch("fs",        "filesystems", lambda u, h, c: fetch_filesystems(u, h)),
)
_PROM_STATUS_KEYS: tuple[str, ...] = tuple(f.status_key for f in _PROM_FETCHES)


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
        # Last-good cache keyed by MetricFetch.last_attr (plus "pulls"). Each
        # value is dict[host_name, Cell] for the simple metrics; freshness
        # holds dict[host_name, HostFreshness] and filesystems holds nested
        # dict[host_name, dict[column, Cell]].
        self._last: dict[str, Any] = {}

    def on_mount(self) -> None:
        self.action_refresh()
        self.set_interval(self._config.refresh_seconds, self.action_refresh)

    def action_refresh(self) -> None:
        if not self._has_rendered_snapshot:
            self._render_snapshot(self._build_snapshot(
                prom_status_line=self._status_line(
                    {k: "checking" for k in _PROM_STATUS_KEYS}, "checking",
                ),
            ))

        self.run_worker(self._refresh, exclusive=True)

    async def _refresh(self) -> None:
        prom_url = self._config.prometheus_url
        hosts = self._config.hosts

        results = await asyncio.gather(
            *(f.factory(prom_url, hosts, self._config) for f in _PROM_FETCHES),
            return_exceptions=True,
        )
        statuses: dict[str, str] = {}
        for spec, result in zip(_PROM_FETCHES, results, strict=True):
            if isinstance(result, Exception):
                statuses[spec.status_key] = "unreachable"
            else:
                statuses[spec.status_key] = "ok"
                self._last[spec.last_attr] = result

        self._render_snapshot(self._build_snapshot(
            prom_status_line=self._status_line(statuses, "checking"),
        ))

        tfcs_status = "ok"
        tfcs_fqdns = tuple(h.tfcs_status for h in hosts.values() if h.tfcs_status)
        try:
            pull_summaries = await fetch_pull_summaries(
                tfcs_fqdns, self._config.tfcs_port, timeout_seconds=1,
            )
            self._last["pulls"] = {
                name: pull_cell(pull_summaries.get(name)) for name in hosts
            }
        except Exception:
            tfcs_status = "unreachable"

        self.query_one(FleetTable).update_pulls(self._last.get("pulls", {}))
        self._update_source_bar(self._status_line(statuses, tfcs_status))

    def _build_snapshot(self, prom_status_line: str) -> FleetSnapshot:
        last = self._last
        freshness: dict[str, HostFreshness] = last.get("freshness", {})
        loads: dict[str, Cell] = last.get("loads", {})
        cpu_temps: dict[str, Cell] = last.get("cpu_temps", {})
        hdd_temps: dict[str, Cell] = last.get("hdd_temps", {})
        nvme_temps: dict[str, Cell] = last.get("nvme_temps", {})
        nic_temps: dict[str, Cell] = last.get("nic_temps", {})
        filesystems: dict[str, dict[str, Cell]] = last.get("filesystems", {})
        pulls: dict[str, Cell] = last.get("pulls", {})

        nodes = []
        for name in self._config.hosts:
            fresh = freshness.get(name)
            fs = filesystems.get(name, {})
            cells = (
                fresh.last_update if fresh else MISSING,
                fresh.up if fresh else MISSING,
                loads.get(name, MISSING),
                cpu_temps.get(name, MISSING),
                hdd_temps.get(name, MISSING),
                nvme_temps.get(name, MISSING),
                nic_temps.get(name, MISSING),
                fs.get("root", MISSING),
                fs.get("data", MISSING),
                pulls.get(name, MISSING),
            )
            note = "no prom data" if all(c.status == "missing" for c in cells) else ""
            (last_update, up, load, cpu, hdd, nvme, nic, root, data, pulls_cell) = cells
            # ssd_temp has no fetcher yet; left absent until a real SSD path lands.
            nodes.append(FleetNode(
                host=name,
                last_update=last_update, up=up, load=load,
                cpu_temp=cpu, hdd_temp=hdd, ssd_temp=ABSENT, nvme_temp=nvme,
                nic=nic, root=root, data=data, pulls=pulls_cell, note=note,
            ))
        return FleetSnapshot(
            nodes=tuple(nodes),
            source=prom_status_line,
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

    def _status_line(self, statuses: dict[str, str], tfcs_status: str) -> str:
        """Build a compact data source status line."""
        if all(statuses.get(k) == "unreachable" for k in _PROM_STATUS_KEYS):
            return (
                f"PROMETHEUS UNREACHABLE at {self._config.prometheus_url}; "
                f"tfcs={tfcs_status}"
            )
        parts = [f"{k}={statuses.get(k, 'ok')}" for k in _PROM_STATUS_KEYS]
        parts.append(f"tfcs={tfcs_status}")
        return ", ".join(parts)

    def _update_source_bar(self, source: str) -> None:
        self.query_one("#source-bar", Static).update(
            f" source: {source}    prom: {self._config.prometheus_url}"
        )


def main() -> None:
    FleetDashboard(load_config()).run()


if __name__ == "__main__":
    main()
