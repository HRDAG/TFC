# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/config.py

"""Hardwired config loading for the fleet dashboard."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "tfcs-fleet-tui.toml"


@dataclass(frozen=True)
class FleetConfig:
    """Runtime configuration for the fleet dashboard."""

    prometheus_url: str
    refresh_seconds: int
    stale_after_seconds: int
    thresholds_path: Path
    host_instances: dict[str, str]
    no_hdd_hosts: tuple[str, ...]
    no_nic_hosts: tuple[str, ...]
    filesystems: dict[str, dict[str, str]]
    tfcs_hosts: tuple[str, ...]
    tfcs_port: int
    enabled_columns: tuple[str, ...]
    sort: str
    temperature_unit: str


def load_config() -> FleetConfig:
    """Load the hardwired fleet dashboard TOML."""
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config not found: {CONFIG_PATH}")

    with open(CONFIG_PATH, "rb") as f:
        raw = tomllib.load(f)

    display = raw.get("display", {})
    columns = raw.get("columns", {})
    hosts = raw.get("hosts", {})
    tfcs = raw.get("tfcs", {})

    return FleetConfig(
        prometheus_url=raw.get("prometheus_url", "http://scott.hrdag.net:9090"),
        refresh_seconds=int(raw.get("refresh_seconds", 10)),
        stale_after_seconds=int(raw.get("stale_after_seconds", 120)),
        thresholds_path=Path(
            raw.get("thresholds_path", "config/fleet-thresholds.generated.toml")
        ),
        host_instances=dict(hosts.get("instances", {})),
        no_hdd_hosts=tuple(hosts.get("no_hdd", ())),
        no_nic_hosts=tuple(hosts.get("no_nic", ())),
        filesystems={
            host: dict(mounts)
            for host, mounts in hosts.get("filesystems", {}).items()
        },
        tfcs_hosts=tuple(tfcs.get("hosts", ())),
        tfcs_port=int(tfcs.get("port", 8099)),
        enabled_columns=tuple(columns.get("enabled", ())),
        sort=display.get("sort", "fixed"),
        temperature_unit=display.get("temperature_unit", "celsius"),
    )
