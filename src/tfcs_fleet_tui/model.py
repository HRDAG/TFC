# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/model.py

"""Fleet dashboard data model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ABSENT_STR = "--"
MISSING_STR = "?"

CellStatus = Literal["ok", "warn", "crit", "missing", "absent"]


@dataclass(frozen=True)
class Cell:
    """One displayable cell: rendered text, threshold/availability state, raw value.

    ``raw`` carries the underlying numeric (celsius, percent, load1, age in seconds,
    puller count) so that threshold comparisons can read it directly without
    re-parsing ``value``. It is ``None`` for absent/missing cells and for cells
    whose value has no meaningful numeric form (e.g. up="stale").
    """

    value: str
    status: CellStatus = "ok"
    raw: float | None = None

    @classmethod
    def absent(cls) -> "Cell":
        return cls(value=ABSENT_STR, status="absent")

    @classmethod
    def missing(cls) -> "Cell":
        return cls(value=MISSING_STR, status="missing")

    @classmethod
    def of(cls, raw: float | None, value: str, status: CellStatus = "ok") -> "Cell":
        return cls(value=value, status=status, raw=raw)

    @classmethod
    def from_str(cls, value: str) -> "Cell":
        if value == ABSENT_STR:
            return cls.absent()
        if value == MISSING_STR:
            return cls.missing()
        return cls(value=value, status="ok")


ABSENT = Cell.absent()
MISSING = Cell.missing()


@dataclass(frozen=True)
class FleetNode:
    """One row in the fleet dashboard."""

    host: str
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
