# Author: PB and Codex
# Date: 2026-05-21
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/prometheus.py

"""Prometheus polling for the fleet dashboard.

The dashboard only talks to the configured Prometheus API. Instance values
such as ``chll.hrdag.net:9100`` are label values in scott's Prometheus, not
network endpoints contacted by this TUI.

Each fetch takes ``hosts: dict[name, Host]`` and returns ``dict[name, Cell]``
(rendered value + status + raw numeric). The raw numeric makes per-host
thresholds a direct comparison once they land; until then everything is
"ok" by default, with the stale_after_seconds boundary already classifying
freshness into "warn"/"crit".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

from tfcs_fleet_tui.config import Host
from tfcs_fleet_tui.model import Cell
from tfcs_fleet_tui.serverdoc import Thresholds


@dataclass(frozen=True)
class HostFreshness:
    """Prometheus freshness state for one host."""

    up: Cell
    last_update: Cell


def _instance_regex(instances: list[str]) -> str:
    """Build a Prometheus regex that matches exactly the configured labels."""
    regex_specials = {
        ".": "[.]", "+": "[+]", "?": "[?]", "(": "[(]", ")": "[)]",
        "[": "[[]", "]": "[]]", "{": "[{]", "}": "[}]",
        "^": "[^]", "$": "[$]", "|": "[|]", "*": "[*]",
    }
    return "|".join(
        "".join(regex_specials.get(char, char) for char in instance)
        for instance in instances
    )


def _instance_to_host(hosts: dict[str, Host]) -> dict[str, str]:
    return {host.instance: name for name, host in hosts.items()}


def _hosts_regex(hosts: dict[str, Host]) -> str:
    return _instance_regex([host.instance for host in hosts.values()])


def _format_age(seconds: float) -> str:
    """Format scrape age for the Last column."""
    if seconds < 60:
        return f"{max(0, int(seconds))}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h"


async def _query(
    session: aiohttp.ClientSession,
    prometheus_url: str,
    query: str,
    timeout_seconds: int,
) -> list[dict]:
    """Run an instant vector query and return result samples."""
    url = f"{prometheus_url.rstrip('/')}/api/v1/query"
    async with session.get(
        url,
        params={"query": query},
        timeout=aiohttp.ClientTimeout(total=timeout_seconds),
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
    if data.get("status") != "success":
        return []
    return list(data.get("data", {}).get("result", []))


async def fetch_known_instances(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> set[str]:
    """Fetch every instance label Prometheus currently scrapes.

    Used to distinguish a misconfigured ``instance`` value (label never
    appears, host permanently blank) from a real outage (label matches,
    scrape just failed) -- both otherwise render as identical "missing"
    cells.
    """
    if not hosts:
        return set()
    async with aiohttp.ClientSession() as session:
        samples = await _query(session, prometheus_url, "up", timeout_seconds)
    return {
        instance
        for sample in samples
        if (instance := sample.get("metric", {}).get("instance"))
    }


def _sample_values_by_host(
    samples: list[dict], instance_to_host: dict[str, str],
) -> dict[str, float]:
    """Convert Prometheus vector samples to host -> float value."""
    values: dict[str, float] = {}
    for sample in samples:
        instance = sample.get("metric", {}).get("instance")
        host = instance_to_host.get(instance)
        if not host:
            continue
        try:
            values[host] = float(sample.get("value", [None, None])[1])
        except (TypeError, ValueError):
            pass
    return values


def _temp_cell(value: float | None) -> Cell:
    return Cell.missing() if value is None else Cell.of(value, f"{value:.0f}C")


def _pct_cell(value: float) -> Cell:
    return Cell.of(value, f"{value:.0f}%")


def _classify(cell: Cell, t: Thresholds | None) -> Cell:
    """Classify a verified ok cell against a threshold.

    Returns "crit" / "warn" if the raw value crosses the matching boundary,
    "safe" when at least one threshold exists and the value is below all
    available boundaries (= explicitly verified within tolerance), and
    leaves the cell untouched when no threshold information exists. The
    "ok" → "safe" promotion is what gives the dashboard a green cell only
    where a real comparison happened.
    """
    if t is None or cell.status != "ok" or cell.raw is None:
        return cell
    if t.crit is not None and cell.raw >= t.crit:
        return Cell(value=cell.value, status="crit", raw=cell.raw)
    if t.warn is not None and cell.raw >= t.warn:
        return Cell(value=cell.value, status="warn", raw=cell.raw)
    if t.warn is not None or t.crit is not None:
        return Cell(value=cell.value, status="safe", raw=cell.raw)
    return cell


async def fetch_freshness(
    prometheus_url: str,
    hosts: dict[str, Host],
    stale_after_seconds: int,
    timeout_seconds: int = 5,
) -> dict[str, HostFreshness]:
    """Fetch ``Up`` and ``Last`` values for configured hosts."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    up_query = f'up{{instance=~"{regex}"}}'
    age_query = f'time() - timestamp(up{{instance=~"{regex}"}})'

    async with aiohttp.ClientSession() as session:
        up_results, age_results = await asyncio.gather(
            _query(session, prometheus_url, up_query, timeout_seconds),
            _query(session, prometheus_url, age_query, timeout_seconds),
        )

    up_by_host = _sample_values_by_host(up_results, instance_to_host)
    age_by_host = _sample_values_by_host(age_results, instance_to_host)

    freshness: dict[str, HostFreshness] = {}
    for name in hosts:
        age = age_by_host.get(name)
        up_value = up_by_host.get(name)
        if up_value is None and age is None:
            freshness[name] = HostFreshness(up=Cell.missing(), last_update=Cell.missing())
            continue
        # last_update is "safe" when we have a recent age — the stale check
        # below is the threshold for this metric. up=1 is also a verified
        # pass, so it earns "safe" too.
        fresh_last = (
            Cell.of(age, _format_age(age), status="safe")
            if age is not None else Cell.missing()
        )
        if age is not None and age > stale_after_seconds:
            freshness[name] = HostFreshness(
                up=Cell.of(None, "stale", status="warn"),
                last_update=Cell.of(age, _format_age(age), status="warn"),
            )
        elif up_value == 1:
            freshness[name] = HostFreshness(
                up=Cell.of(1, "ok", status="safe"),
                last_update=fresh_last,
            )
        elif up_value == 0:
            freshness[name] = HostFreshness(
                up=Cell.of(0, "down", status="crit"),
                last_update=fresh_last,
            )
        else:
            freshness[name] = HostFreshness(up=Cell.missing(), last_update=fresh_last)

    return freshness


async def fetch_load(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, Cell]:
    """Fetch load1 and CPU-core counts for configured hosts."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    load_query = f'node_load1{{instance=~"{regex}"}}'
    cores_query = (
        'count by (instance) ('
        f'count by (instance, cpu) (node_cpu_seconds_total{{instance=~"{regex}",mode="idle"}})'
        ')'
    )

    async with aiohttp.ClientSession() as session:
        load_results, cores_results = await asyncio.gather(
            _query(session, prometheus_url, load_query, timeout_seconds),
            _query(session, prometheus_url, cores_query, timeout_seconds),
        )

    load_by_host = _sample_values_by_host(load_results, instance_to_host)
    cores_by_host = _sample_values_by_host(cores_results, instance_to_host)

    cells: dict[str, Cell] = {}
    for name in hosts:
        load = load_by_host.get(name)
        cores = cores_by_host.get(name)
        if load is None and cores is None:
            cells[name] = Cell.missing()
        elif load is None:
            text = f"?/{int(cores)}" if cores else "?/?"
            cells[name] = Cell.of(None, text, status="missing")
        elif cores is None:
            cells[name] = Cell.of(load, f"{load:.1f}/?")
        else:
            cells[name] = Cell.of(load, f"{load:.1f}/{int(cores)}")
    return cells


async def _fetch_hwmon_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    sensor_key: str,
    metric_key: str,
    queries: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, Cell]:
    """Common temperature-fetch path: respect sensor capability, format, classify."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *(_query(session, prometheus_url, q, timeout_seconds) for q in queries)
        )

    temps_by_host: dict[str, float] = {}
    for batch in results:
        for name, value in _sample_values_by_host(batch, instance_to_host).items():
            temps_by_host.setdefault(name, value)

    cells: dict[str, Cell] = {}
    for name, host in hosts.items():
        if not host.has(sensor_key):
            cells[name] = Cell.absent()
            continue
        cells[name] = _classify(
            _temp_cell(temps_by_host.get(name)),
            host.threshold(metric_key),
        )
    return cells


async def fetch_cpu_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, Cell]:
    """Fetch max CPU temperature per configured host."""
    regex = _hosts_regex(hosts)
    chip_regex = ".*(coretemp|k10temp).*|pci0000:00_0000:00:18_3|thermal_thermal_zone0"
    queries = (
        f'max by (instance) (node_hwmon_temp_celsius{{instance=~"{regex}",chip=~"{chip_regex}"}})',
        f'max by (instance) (sensors_temp_input{{instance=~"{regex}",chip=~"{chip_regex}"}})',
    )
    return await _fetch_hwmon_temps(
        prometheus_url, hosts, "cpu", "cpu_temp", queries, timeout_seconds,
    )


async def fetch_hdd_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, Cell]:
    """Fetch max SATA/SAS HDD temperature per configured host."""
    regex = _hosts_regex(hosts)
    query = (
        'max by (instance) ('
        f'smartctl_device_temperature{{instance=~"{regex}",device=~"sd.*",temperature_type="current"}} '
        '* on(instance, device) group_left '
        f'smartctl_device{{instance=~"{regex}",form_factor="3.5 inches"}}'
        ')'
    )
    return await _fetch_hwmon_temps(
        prometheus_url, hosts, "hdd", "hdd_temp", (query,), timeout_seconds,
    )


async def fetch_nvme_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, Cell]:
    """Fetch max NVMe temperature per configured host."""
    regex = _hosts_regex(hosts)
    query = (
        'max by (instance) ('
        f'smartctl_device_temperature{{instance=~"{regex}",device=~"nvme.*",temperature_type="current"}}'
        ')'
    )
    return await _fetch_hwmon_temps(
        prometheus_url, hosts, "nvme", "nvme_temp", (query,), timeout_seconds,
    )


async def fetch_nic_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, Cell]:
    """Fetch max NIC temperature per configured host."""
    regex = _hosts_regex(hosts)
    nic_chip_regex = "bnxt_en|ice|en.*|eth.*"
    query = (
        'max by (instance) ('
        f'node_hwmon_temp_celsius{{instance=~"{regex}"}} '
        '* on(instance, chip) group_left(chip_name) '
        f'node_hwmon_chip_names{{instance=~"{regex}",chip_name=~"{nic_chip_regex}"}}'
        ')'
    )
    return await _fetch_hwmon_temps(
        prometheus_url, hosts, "nic", "nic_temp", (query,), timeout_seconds,
    )


async def fetch_filesystems(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, dict[str, Cell]]:
    """Fetch configured root/data filesystem usage percentages.

    For ZFS-backed mountpoints, aggregate at the pool level (identified by the
    ``device`` label's prefix) instead of using statvfs-on-one-dataset numbers,
    which under-report because nested datasets share pool free space.
    """
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    fstype_excl = "tmpfs|devtmpfs|overlay|squashfs"
    size_query = (
        f'node_filesystem_size_bytes{{instance=~"{regex}",fstype!~"{fstype_excl}"}}'
    )
    avail_query = (
        f'node_filesystem_avail_bytes{{instance=~"{regex}",fstype!~"{fstype_excl}"}}'
    )

    async with aiohttp.ClientSession() as session:
        size_results, avail_results = await asyncio.gather(
            _query(session, prometheus_url, size_query, timeout_seconds),
            _query(session, prometheus_url, avail_query, timeout_seconds),
        )

    samples: dict[tuple[str, str], dict[str, float | str]] = {}
    for sample in size_results:
        metric = sample.get("metric", {})
        name = instance_to_host.get(metric.get("instance"))
        mp = metric.get("mountpoint")
        if not name or not mp:
            continue
        try:
            size = float(sample["value"][1])
        except (TypeError, ValueError, KeyError):
            continue
        samples[(name, mp)] = {
            "size": size,
            "device": metric.get("device", ""),
            "fstype": metric.get("fstype", ""),
        }
    for sample in avail_results:
        metric = sample.get("metric", {})
        name = instance_to_host.get(metric.get("instance"))
        mp = metric.get("mountpoint")
        if not name or not mp:
            continue
        try:
            avail = float(sample["value"][1])
        except (TypeError, ValueError, KeyError):
            continue
        if (name, mp) in samples:
            samples[(name, mp)]["avail"] = avail

    # Index zfs samples by (host, pool) for pool-level aggregation.
    zfs_by_pool: dict[tuple[str, str], list[dict[str, float | str]]] = {}
    for (name, _mp), sample in samples.items():
        if sample.get("fstype") != "zfs":
            continue
        device = str(sample.get("device", ""))
        pool = device.split("/", 1)[0]
        if not pool:
            continue
        zfs_by_pool.setdefault((name, pool), []).append(sample)

    values: dict[str, dict[str, Cell]] = {}
    for name, host in hosts.items():
        values[name] = {}
        for column in ("root", "data"):
            mountpoint = host.mounts.get(column)
            if not mountpoint:
                values[name][column] = Cell.missing()
                continue
            sample = samples.get((name, mountpoint))
            if not sample or "avail" not in sample or "size" not in sample:
                values[name][column] = Cell.missing()
                continue
            if sample.get("fstype") == "zfs":
                pool = str(sample["device"]).split("/", 1)[0]
                pool_samples = zfs_by_pool.get((name, pool), [])
                if not pool_samples:
                    values[name][column] = Cell.missing()
                    continue
                used = sum(
                    float(s["size"]) - float(s["avail"])
                    for s in pool_samples
                    if "avail" in s
                )
                free = max(
                    (float(s["avail"]) for s in pool_samples if "avail" in s),
                    default=0.0,
                )
                total = used + free
                pct = 0.0 if total <= 0 else 100.0 * used / total
            else:
                size = float(sample["size"])
                avail = float(sample["avail"])
                pct = 0.0 if size <= 0 else 100.0 * (1.0 - avail / size)
            values[name][column] = _pct_cell(pct)
    return values
