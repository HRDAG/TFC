# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/widgets.py

"""Widgets for the fleet dashboard."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import DataTable

from tfcs_fleet_tui.model import Cell, FleetSnapshot


_STATUS_STYLE: dict[str, str] = {
    "warn": "yellow",
    "crit": "bold red",
    "missing": "dim",
    "absent": "dim",
}


def _styled(cell: Cell) -> Text | str:
    style = _STATUS_STYLE.get(cell.status)
    if style is None:
        return cell.value
    return Text(cell.value, style=style)


_METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("last", "last_update"),
    ("up", "up"),
    ("load", "load"),
    ("cpu", "cpu_temp"),
    ("hdd", "hdd_temp"),
    ("ssd", "ssd_temp"),
    ("nvme", "nvme_temp"),
    ("nic", "nic"),
    ("root", "root"),
    ("data", "data"),
    ("pulls", "pulls"),
)


class FleetTable(DataTable):
    """Single-table fleet health view."""

    DEFAULT_CSS = """
    FleetTable {
        height: auto;
        margin: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._hosts: set[str] = set()

    def on_mount(self) -> None:
        self.add_column("Host", width=10, key="host")
        self.add_column("Last", width=6, key="last")
        self.add_column("Up", width=6, key="up")
        self.add_column("Load", width=8, key="load")
        self.add_column("CPU", width=6, key="cpu")
        self.add_column("HDD", width=6, key="hdd")
        self.add_column("SSD", width=6, key="ssd")
        self.add_column("NVMe", width=6, key="nvme")
        self.add_column("NIC", width=5, key="nic")
        self.add_column("Root", width=6, key="root")
        self.add_column("Data", width=6, key="data")
        self.add_column("Pulls", width=8, key="pulls")
        self.add_column("Note", width=20, key="note")
        self.cursor_type = "none"

        for col_key in self.columns:
            self.columns[col_key].label_align = ("center", "middle")

        for col_key in (
            "last", "load", "cpu", "hdd", "ssd", "nvme", "root", "data", "pulls"
        ):
            self.columns[col_key].content_align = ("right", "middle")

    def refresh_data(self, snapshot: FleetSnapshot) -> None:
        for node in snapshot.nodes:
            if node.host not in self._hosts:
                self._add_node_row(node)
                continue
            self.update_cell(node.host, "host", node.host)
            for col_key, attr in _METRIC_COLUMNS:
                self.update_cell(node.host, col_key, _styled(getattr(node, attr)))
            self.update_cell(node.host, "note", node.note)

    def update_pulls(self, pulls: dict[str, Cell]) -> None:
        """Update only the Pulls column."""
        for host, cell in pulls.items():
            if host in self._hosts:
                self.update_cell(host, "pulls", _styled(cell))

    def _add_node_row(self, node) -> None:
        """Add a fully populated row for one host."""
        self.add_row(
            node.host,
            *(_styled(getattr(node, attr)) for _, attr in _METRIC_COLUMNS),
            node.note,
            key=node.host,
        )
        self._hosts.add(node.host)
