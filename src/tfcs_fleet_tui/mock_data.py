# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/mock_data.py

"""Static fleet fixture for the initial dashboard mock."""

from __future__ import annotations

from tfcs_fleet_tui.model import Cell, FleetNode, FleetSnapshot


def _node(
    host: str,
    roles: tuple[str, ...] = (),
    last_update: str = "?",
    up: str = "--",
    load: str = "--",
    cpu_temp: str = "--",
    hdd_temp: str = "--",
    ssd_temp: str = "--",
    nvme_temp: str = "--",
    nic: str = "--",
    root: str = "--",
    data: str = "--",
    pulls: str = "--",
    note: str = "",
) -> FleetNode:
    return FleetNode(
        host=host,
        roles=roles,
        last_update=Cell.from_str(last_update),
        up=Cell.from_str(up),
        load=Cell.from_str(load),
        cpu_temp=Cell.from_str(cpu_temp),
        hdd_temp=Cell.from_str(hdd_temp),
        ssd_temp=Cell.from_str(ssd_temp),
        nvme_temp=Cell.from_str(nvme_temp),
        nic=Cell.from_str(nic),
        root=Cell.from_str(root),
        data=Cell.from_str(data),
        pulls=Cell.from_str(pulls),
        note=note,
    )


MOCK_SNAPSHOT = FleetSnapshot(
    source="mock fleet fixture",
    nodes=(
        _node("scott", roles=("compute", "gpu", "backup_source"),
              last_update="8s", up="ok", load="3.1/64", cpu_temp="54C",
              ssd_temp="41C", nvme_temp="67C", nic="ok",
              root="62%", data="71%", pulls="4", note="busy pulls"),
        _node("chll", roles=("offsite_backup", "storage", "ipfs"),
              last_update="11s", up="ok", load="0.8/32", cpu_temp="49C",
              hdd_temp="38C", nvme_temp="45C", nic="ok",
              root="55%", data="82%", pulls="1"),
        _node("ipfs1", roles=("storage", "ipfs"),
              last_update="9s", up="ok", load="0.5/8", cpu_temp="46C",
              hdd_temp="42C", nvme_temp="51C", nic="ok",
              root="39%", data="74%"),
        _node("pihost", roles=("environment", "ipfs"),
              last_update="14s", up="ok", load="0.2/4", cpu_temp="51C",
              nic="ok", root="44%", data="44%"),
        _node("meerkat", roles=("compute", "ipfs"),
              last_update="7s", up="ok", load="1.7/20", cpu_temp="58C",
              nvme_temp="49C", nic="ok", root="61%", data="61%"),
        _node("snowball", roles=("tfc_partner",),
              last_update="13s", up="ok", load="7.4/32", cpu_temp="91C",
              nvme_temp="61C", nic="ok",
              root="40%", data="68%", pulls="2", note="cpu warm"),
        _node("lizo", roles=("tfc_partner", "storage"),
              last_update="10s", up="ok", load="0.9/16", cpu_temp="47C",
              hdd_temp="37C", nvme_temp="43C", nic="ok",
              root="46%", data="79%", pulls="3"),
        _node("ben", roles=("storage",),
              last_update="15s", up="ok", load="2.2/32", cpu_temp="52C",
              hdd_temp="41C", nvme_temp="56C", nic="ok",
              root="58%", data="64%"),
        _node("ida", roles=("tfc_partner", "storage"),
              last_update="5m", up="stale", cpu_temp="?", hdd_temp="?",
              nvme_temp="?", nic="?", root="?", data="?",
              note="no scrape 5m"),
        _node("ant", roles=("tfc_partner", "storage"),
              last_update="12s", up="ok", load="1.1/16", cpu_temp="50C",
              hdd_temp="39C", nvme_temp="72C", nic="ok",
              root="48%", data="77%", pulls="2", note="nvme warm"),
        _node("nas", roles=("storage", "ups_nut", "ipfs"),
              last_update="10s", up="ok", load="1.6/16", cpu_temp="48C",
              hdd_temp="44C", nvme_temp="53C", nic="ok",
              root="52%", data="86%"),
        _node("kj", roles=("compute", "gpu"),
              last_update="9s", up="ok", load="4.8/64", cpu_temp="57C",
              nvme_temp="46C", nic="ok", root="45%", data="69%"),
    ),
)
