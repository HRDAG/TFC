# Author: PB and cx-tfc
# Date: 2026-07-04
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/source.py

"""Shared fleet dashboard data source."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import aiohttp

from tfcs_fleet_tui.config import FleetConfig, Host
from tfcs_fleet_tui.model import ABSENT, MISSING, Cell, FleetNode, FleetSnapshot
from tfcs_fleet_tui.prometheus import (
    HostFreshness,
    _instance_regex,
    _query,
    fetch_cpu_temps,
    fetch_filesystems,
    fetch_freshness,
    fetch_hdd_temps,
    fetch_known_instances,
    fetch_load,
    fetch_nic_temps,
    fetch_nvme_temps,
)
from tfcs_fleet_tui.tfcs import fetch_pull_summaries, pull_cell


FetchFn = Callable[[str, dict[str, Host], FleetConfig], Awaitable[Any]]


@dataclass(frozen=True)
class MetricFetch:
    """One Prometheus-backed fleet metric."""

    status_key: str
    last_attr: str
    factory: FetchFn


PROM_FETCHES: tuple[MetricFetch, ...] = (
    MetricFetch("freshness", "freshness",
                lambda u, h, c: fetch_freshness(u, h, c.stale_after_seconds)),
    MetricFetch("load",      "loads",       lambda u, h, c: fetch_load(u, h)),
    MetricFetch("cpu",       "cpu_temps",   lambda u, h, c: fetch_cpu_temps(u, h)),
    MetricFetch("hdd",       "hdd_temps",   lambda u, h, c: fetch_hdd_temps(u, h)),
    MetricFetch("nvme",      "nvme_temps",  lambda u, h, c: fetch_nvme_temps(u, h)),
    MetricFetch("nic",       "nic_temps",   lambda u, h, c: fetch_nic_temps(u, h)),
    MetricFetch("fs",        "filesystems", lambda u, h, c: fetch_filesystems(u, h)),
    MetricFetch("labels",    "known_instances", lambda u, h, c: fetch_known_instances(u, h)),
)
PROM_STATUS_KEYS: tuple[str, ...] = tuple(f.status_key for f in PROM_FETCHES)


class FleetDataSource:
    """Fetch and cache fleet-health data for either dashboard surface."""

    def __init__(self, config: FleetConfig) -> None:
        self.config = config
        self.last: dict[str, Any] = {}

    async def refresh_prometheus(self) -> dict[str, str]:
        """Refresh Prometheus-backed metrics and return per-source status."""
        prom_url = self.config.prometheus_url
        hosts = self.config.hosts

        results = await asyncio.gather(
            *(f.factory(prom_url, hosts, self.config) for f in PROM_FETCHES),
            return_exceptions=True,
        )
        statuses: dict[str, str] = {}
        for spec, result in zip(PROM_FETCHES, results, strict=True):
            if isinstance(result, Exception):
                statuses[spec.status_key] = "unreachable"
            else:
                statuses[spec.status_key] = "ok"
                self.last[spec.last_attr] = result
        return statuses

    async def refresh_pulls(self) -> str:
        """Refresh direct tfcs pull summaries and return source status."""
        hosts = self.config.hosts
        tfcs_fqdns = tuple(h.tfcs_status for h in hosts.values() if h.tfcs_status)
        try:
            pull_summaries = await fetch_pull_summaries(
                tfcs_fqdns, self.config.tfcs_port,
            )
            self.last["pulls"] = {
                name: pull_cell(pull_summaries.get(name)) for name in hosts
            }
        except Exception:
            return "unreachable"
        return "ok"

    async def refresh_oob(self) -> str:
        """Refresh configured OOB scrape status for host notes."""
        oob_instances = tuple(
            instance
            for host in self.config.hosts.values()
            for instance in host.oob_instances
        )
        if not oob_instances:
            self.last["oob"] = {}
            return "ok"

        regex = _instance_regex(list(oob_instances))
        query = f'up{{instance=~"{regex}"}}'
        try:
            async with aiohttp.ClientSession() as session:
                samples = await _query(session, self.config.prometheus_url, query, 5)
        except Exception:
            return "unreachable"

        values: dict[str, float] = {}
        for sample in samples:
            instance = sample.get("metric", {}).get("instance")
            try:
                values[instance] = float(sample.get("value", [None, None])[1])
            except (TypeError, ValueError):
                pass
        self.last["oob"] = values
        return "ok"

    @staticmethod
    def _oob_cell(host: Host, oob: dict[str, float]) -> Cell:
        """Build the OOB display cell.

        PiKVM entries with scrape labels carry live reachability. VPN-gated
        IPMI/iLO entries are display-only and intentionally remain plain.
        """
        if not host.oob_kind:
            return ABSENT
        label = host.oob_kind
        if not host.oob_instances:
            return Cell.from_str(label)

        states = []
        for instance in host.oob_instances:
            up_value = oob.get(instance)
            if up_value == 1:
                states.append("ok")
            elif up_value == 0:
                states.append("down")
            else:
                states.append("?")

        if all(state == "ok" for state in states):
            return Cell.of(1, label, status="safe")
        if any(state == "down" for state in states):
            return Cell.of(0, label, status="crit")
        return Cell.of(None, f"{label}?", status="missing")

    def build_snapshot(self, prom_status_line: str) -> FleetSnapshot:
        """Build a display snapshot from last-good cached values."""
        freshness: dict[str, HostFreshness] = self.last.get("freshness", {})
        loads: dict[str, Cell] = self.last.get("loads", {})
        cpu_temps: dict[str, Cell] = self.last.get("cpu_temps", {})
        hdd_temps: dict[str, Cell] = self.last.get("hdd_temps", {})
        nvme_temps: dict[str, Cell] = self.last.get("nvme_temps", {})
        nic_temps: dict[str, Cell] = self.last.get("nic_temps", {})
        filesystems: dict[str, dict[str, Cell]] = self.last.get("filesystems", {})
        pulls: dict[str, Cell] = self.last.get("pulls", {})
        oob: dict[str, float] = self.last.get("oob", {})
        known_instances: set[str] = self.last.get("known_instances", set())

        nodes = []
        for name in self.config.hosts:
            host = self.config.hosts[name]
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
            note_parts = []
            if host.kind != "tfcs":
                note_parts.append(host.kind)
            if host.note:
                note_parts.append(host.note)
            if all(c.status in ("missing", "absent") for c in cells):
                if known_instances and host.instance not in known_instances:
                    note_parts.append("bad instance label")
                else:
                    note_parts.append("no prom data")
            note = "; ".join(note_parts)
            oob_cell = self._oob_cell(host, oob)
            (last_update, up, load, cpu, hdd, nvme, nic, root, data, pulls_cell) = cells
            nodes.append(FleetNode(
                host=name,
                last_update=last_update,
                up=up,
                load=load,
                cpu_temp=cpu,
                hdd_temp=hdd,
                nvme_temp=nvme,
                nic=nic,
                root=root,
                data=data,
                pulls=pulls_cell,
                oob=oob_cell,
                note=note,
            ))
        return FleetSnapshot(
            nodes=tuple(nodes),
            source=prom_status_line,
            refresh_seconds=self.config.refresh_seconds,
            stale_after_seconds=self.config.stale_after_seconds,
        )

    def status_line(self, statuses: dict[str, str], tfcs_status: str) -> str:
        """Build a compact data source status line."""
        if all(statuses.get(k) == "unreachable" for k in PROM_STATUS_KEYS):
            return (
                f"PROMETHEUS UNREACHABLE at {self.config.prometheus_url}; "
                f"tfcs={tfcs_status}"
            )
        parts = [f"{k}={statuses.get(k, 'ok')}" for k in PROM_STATUS_KEYS]
        parts.append(f"tfcs={tfcs_status}")
        return ", ".join(parts)
