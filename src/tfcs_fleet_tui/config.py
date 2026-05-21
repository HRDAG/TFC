# Author: PB and Codex
# Date: 2026-05-21
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/config.py

"""Hardwired config loading for the fleet dashboard."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tfcs-fleet-tui.toml"

# Sensors a host may or may not have. New sensors get added here, not as
# separate exclusion lists elsewhere.
SENSOR_KEYS: tuple[str, ...] = ("cpu", "hdd", "ssd", "nvme", "nic")


@dataclass(frozen=True)
class Host:
    """One configured fleet member.

    `instance` is the Prometheus label value the node_exporter scrape uses.
    `tfcs_status` is the FQDN for direct /status polling, or None if the host
    does not run tfcs. `mounts` maps display column ("root", "data") to the
    filesystem mountpoint to query. `sensors[key]` is True when the host is
    expected to expose that sensor; False marks a physical absence so cells
    render as `--` (absent) rather than `?` (missing).
    """

    name: str
    instance: str
    tfcs_status: str | None = None
    mounts: dict[str, str] = field(default_factory=dict)
    sensors: dict[str, bool] = field(default_factory=dict)

    def has(self, sensor: str) -> bool:
        return self.sensors.get(sensor, True)


@dataclass(frozen=True)
class FleetConfig:
    """Runtime configuration for the fleet dashboard."""

    prometheus_url: str
    refresh_seconds: int
    stale_after_seconds: int
    thresholds_path: Path
    hosts: dict[str, Host]
    tfcs_port: int
    enabled_columns: tuple[str, ...]
    sort: str
    temperature_unit: str

    @property
    def host_instances(self) -> dict[str, str]:
        return {name: host.instance for name, host in self.hosts.items()}


def _parse_host(name: str, raw: dict) -> Host:
    sensors = {key: True for key in SENSOR_KEYS}
    sensors.update(raw.get("sensors", {}))
    tfcs_status = raw.get("tfcs_status")
    if tfcs_status is False:
        tfcs_status = None
    return Host(
        name=name,
        instance=str(raw["instance"]),
        tfcs_status=tfcs_status,
        mounts=dict(raw.get("mounts", {})),
        sensors=sensors,
    )


def load_config() -> FleetConfig:
    """Load the hardwired fleet dashboard TOML."""
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "rb") as f:
        raw = tomllib.load(f)

    display = raw.get("display", {})
    columns = raw.get("columns", {})
    hosts_raw = raw.get("hosts", {})
    tfcs = raw.get("tfcs", {})

    hosts = {name: _parse_host(name, block) for name, block in hosts_raw.items()}

    return FleetConfig(
        prometheus_url=raw.get("prometheus_url", "http://scott.hrdag.net:9090"),
        refresh_seconds=int(raw.get("refresh_seconds", 10)),
        stale_after_seconds=int(raw.get("stale_after_seconds", 120)),
        thresholds_path=Path(
            raw.get("thresholds_path", "config/fleet-thresholds.generated.toml")
        ),
        hosts=hosts,
        tfcs_port=int(tfcs.get("port", 8099)),
        enabled_columns=tuple(columns.get("enabled", ())),
        sort=display.get("sort", "fixed"),
        temperature_unit=display.get("temperature_unit", "celsius"),
    )
