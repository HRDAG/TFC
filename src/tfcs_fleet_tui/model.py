# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/model.py

"""Fleet dashboard data model.

The first implementation is populated by a static fixture. Prometheus polling
should fill this same model later so the UI does not care where values came
from.
"""

from __future__ import annotations

from dataclasses import dataclass, field


NOT_EXPECTED = "--"
EXPECTED_MISSING = "?"


@dataclass(frozen=True)
class FleetNode:
    """One row in the fleet dashboard."""

    host: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    last_update: str = EXPECTED_MISSING
    up: str = "--"
    load: str = "--"
    cpu_temp: str = "--"
    hdd_temp: str = "--"
    ssd_temp: str = "--"
    nvme_temp: str = "--"
    nic: str = "--"
    root: str = "--"
    data: str = "--"
    pulls: str = "--"
    note: str = ""


@dataclass(frozen=True)
class FleetSnapshot:
    """Point-in-time fleet view."""

    nodes: tuple[FleetNode, ...]
    source: str = "static fixture"
    refresh_seconds: int = 10
    stale_after_seconds: int = 120
