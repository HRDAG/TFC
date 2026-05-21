# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/model.py

"""Fleet dashboard data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


NOT_EXPECTED = "--"
EXPECTED_MISSING = "?"

CellStatus = Literal["ok", "warn", "crit", "missing", "absent"]


@dataclass(frozen=True)
class Cell:
    """One displayable cell: rendered text plus its threshold/availability state."""

    value: str
    status: CellStatus = "ok"

    @classmethod
    def absent(cls) -> "Cell":
        return cls(value=NOT_EXPECTED, status="absent")

    @classmethod
    def missing(cls) -> "Cell":
        return cls(value=EXPECTED_MISSING, status="missing")

    @classmethod
    def from_str(cls, value: str) -> "Cell":
        if value == NOT_EXPECTED:
            return cls.absent()
        if value == EXPECTED_MISSING:
            return cls.missing()
        return cls(value=value, status="ok")


ABSENT = Cell.absent()
MISSING = Cell.missing()


@dataclass(frozen=True)
class FleetNode:
    """One row in the fleet dashboard."""

    host: str
    roles: tuple[str, ...] = field(default_factory=tuple)
    last_update: Cell = MISSING
    up: Cell = ABSENT
    load: Cell = ABSENT
    cpu_temp: Cell = ABSENT
    hdd_temp: Cell = ABSENT
    ssd_temp: Cell = ABSENT
    nvme_temp: Cell = ABSENT
    nic: Cell = ABSENT
    root: Cell = ABSENT
    data: Cell = ABSENT
    pulls: Cell = ABSENT
    note: str = ""


@dataclass(frozen=True)
class FleetSnapshot:
    """Point-in-time fleet view."""

    nodes: tuple[FleetNode, ...]
    source: str = "static fixture"
    refresh_seconds: int = 10
    stale_after_seconds: int = 120
