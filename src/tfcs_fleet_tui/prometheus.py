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

Each fetch takes ``hosts: dict[name, Host]`` and returns ``dict[name, str]``
(formatted display values). Sensor presence is consulted on the Host so
that "absent" (sensor not declared) renders as ``--`` and "missing"
(declared but no Prom sample) renders as ``?``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp

from tfcs_fleet_tui.config import Host


@dataclass(frozen=True)
class HostFreshness:
    """Prometheus freshness state for one host."""

    up: str
    last_update: str


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


def _format_age(seconds: float | None) -> str:
    """Format scrape age for the Last column."""
    if seconds is None:
        return "?"
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


def _format_temp(value: float | None) -> str:
    return "?" if value is None else f"{value:.0f}C"


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
            freshness[name] = HostFreshness(up="?", last_update="?")
        elif age is not None and age > stale_after_seconds:
            freshness[name] = HostFreshness(up="stale", last_update=_format_age(age))
        elif up_value == 1:
            freshness[name] = HostFreshness(up="ok", last_update=_format_age(age))
        elif up_value == 0:
            freshness[name] = HostFreshness(up="down", last_update=_format_age(age))
        else:
            freshness[name] = HostFreshness(up="?", last_update=_format_age(age))

    return freshness


async def fetch_load(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, str]:
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

    loads: dict[str, str] = {}
    for name in hosts:
        load = load_by_host.get(name)
        cores = cores_by_host.get(name)
        if load is None and cores is None:
            loads[name] = "?"
        elif load is None:
            loads[name] = f"?/{int(cores)}" if cores else "?/?"
        elif cores is None:
            loads[name] = f"{load:.1f}/?"
        else:
            loads[name] = f"{load:.1f}/{int(cores)}"
    return loads


async def fetch_cpu_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, str]:
    """Fetch max CPU temperature per configured host."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    chip_regex = ".*(coretemp|k10temp).*|pci0000:00_0000:00:18_3|thermal_thermal_zone0"
    queries = (
        f'max by (instance) (node_hwmon_temp_celsius{{instance=~"{regex}",chip=~"{chip_regex}"}})',
        f'max by (instance) (sensors_temp_input{{instance=~"{regex}",chip=~"{chip_regex}"}})',
    )

    async with aiohttp.ClientSession() as session:
        primary_results, fallback_results = await asyncio.gather(
            _query(session, prometheus_url, queries[0], timeout_seconds),
            _query(session, prometheus_url, queries[1], timeout_seconds),
        )

    temps_by_host = _sample_values_by_host(primary_results, instance_to_host)
    fallback_by_host = _sample_values_by_host(fallback_results, instance_to_host)

    temps: dict[str, str] = {}
    for name, host in hosts.items():
        if not host.has("cpu"):
            temps[name] = "--"
            continue
        temp = temps_by_host.get(name, fallback_by_host.get(name))
        temps[name] = _format_temp(temp)
    return temps


async def fetch_hdd_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, str]:
    """Fetch max SATA/SAS HDD temperature per configured host."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    query = (
        'max by (instance) ('
        f'smartctl_device_temperature{{instance=~"{regex}",device=~"sd.*",temperature_type="current"}} '
        '* on(instance, device) group_left '
        f'smartctl_device{{instance=~"{regex}",form_factor="3.5 inches"}}'
        ')'
    )

    async with aiohttp.ClientSession() as session:
        results = await _query(session, prometheus_url, query, timeout_seconds)

    temps_by_host = _sample_values_by_host(results, instance_to_host)
    temps: dict[str, str] = {}
    for name, host in hosts.items():
        if not host.has("hdd"):
            temps[name] = "--"
            continue
        temps[name] = _format_temp(temps_by_host.get(name))
    return temps


async def fetch_nvme_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, str]:
    """Fetch max NVMe temperature per configured host."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    query = (
        'max by (instance) ('
        f'smartctl_device_temperature{{instance=~"{regex}",device=~"nvme.*",temperature_type="current"}}'
        ')'
    )

    async with aiohttp.ClientSession() as session:
        results = await _query(session, prometheus_url, query, timeout_seconds)

    temps_by_host = _sample_values_by_host(results, instance_to_host)
    temps: dict[str, str] = {}
    for name, host in hosts.items():
        if not host.has("nvme"):
            temps[name] = "--"
            continue
        temps[name] = _format_temp(temps_by_host.get(name))
    return temps


async def fetch_nic_temps(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, str]:
    """Fetch max NIC temperature per configured host."""
    if not hosts:
        return {}

    instance_to_host = _instance_to_host(hosts)
    regex = _hosts_regex(hosts)
    nic_chip_regex = "bnxt_en|ice|en.*|eth.*"
    query = (
        'max by (instance) ('
        f'node_hwmon_temp_celsius{{instance=~"{regex}"}} '
        '* on(instance, chip) group_left(chip_name) '
        f'node_hwmon_chip_names{{instance=~"{regex}",chip_name=~"{nic_chip_regex}"}}'
        ')'
    )

    async with aiohttp.ClientSession() as session:
        results = await _query(session, prometheus_url, query, timeout_seconds)

    temps_by_host = _sample_values_by_host(results, instance_to_host)
    temps: dict[str, str] = {}
    for name, host in hosts.items():
        if not host.has("nic"):
            temps[name] = "--"
            continue
        temps[name] = _format_temp(temps_by_host.get(name))
    return temps


async def fetch_filesystems(
    prometheus_url: str,
    hosts: dict[str, Host],
    timeout_seconds: int = 5,
) -> dict[str, dict[str, str]]:
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

    values: dict[str, dict[str, str]] = {}
    for name, host in hosts.items():
        values[name] = {}
        for column in ("root", "data"):
            mountpoint = host.mounts.get(column)
            if not mountpoint:
                values[name][column] = "?"
                continue
            sample = samples.get((name, mountpoint))
            if not sample or "avail" not in sample or "size" not in sample:
                values[name][column] = "?"
                continue
            if sample.get("fstype") == "zfs":
                pool = str(sample["device"]).split("/", 1)[0]
                pool_samples = zfs_by_pool.get((name, pool), [])
                if not pool_samples:
                    values[name][column] = "?"
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
            values[name][column] = f"{pct:.0f}%"
    return values
