# Author: PB and Claude
# Date: 2026-05-21
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/serverdoc.py

"""Per-host thresholds loaded from the server-documentation hardware KB.

Each ``machines/<host>.yaml`` declares the host's hardware by slug under
``devices.{platform,storage,network,...}[].hardware``. Each slug resolves to
``hardware/<category>/<slug>.yaml`` whose ``thresholds.temperature_celsius``
block carries ``warning_max`` and ``critical_max`` for that device model.

For hosts with multiple devices of the same type, the host's threshold is
the floor across devices — the strictest single device sets the cell's warn
and crit boundary. That matches the TUI's max-across-drives Prom query: any
one drive crossing its own threshold should color the host's row.

Filesystem-fullness and load thresholds are NOT in this layer. Those depend
on pool composition and workload class, not device model — see machines/<host>.yaml
for the upstream design (a per-host operational `thresholds:` block is the
next step in server-documentation).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


# device_type → metric key used by the dashboard fetchers
_DEVICE_TYPE_METRIC: dict[str, str] = {
    "cpu": "cpu_temp",
    "hdd": "hdd_temp",
    "nvme": "nvme_temp",
    "nic": "nic_temp",
}


@dataclass(frozen=True)
class Thresholds:
    """Per-metric warn / crit boundaries. Either may be None if undocumented."""

    warn: float | None = None
    crit: float | None = None

    @property
    def has_any(self) -> bool:
        return self.warn is not None or self.crit is not None


def _load_yaml(path: Path) -> dict:
    with open(path, "rb") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _hardware_slug_paths(hardware_root: Path) -> dict[str, Path]:
    """Index slug -> full path so each machines/<host>.yaml device list resolves."""
    index: dict[str, Path] = {}
    for path in hardware_root.glob("*/*.yaml"):
        index[path.stem] = path
    return index


def _device_temp(thresholds_block: dict) -> tuple[float | None, float | None]:
    """Pull (warning_max, critical_max) from a thresholds.temperature_celsius dict."""
    temp = thresholds_block.get("temperature_celsius") or {}
    warn = temp.get("warning_max")
    crit = temp.get("critical_max")
    try:
        warn_f = float(warn) if warn is not None else None
        crit_f = float(crit) if crit is not None else None
    except (TypeError, ValueError):
        return None, None
    return warn_f, crit_f


def _iter_machine_device_slugs(machine_doc: dict):
    """Yield (slug, declared_type) for every hardware entry in a machine file."""
    devices = machine_doc.get("devices") or {}
    if not isinstance(devices, dict):
        return
    for category_entries in devices.values():
        if not isinstance(category_entries, list):
            continue
        for entry in category_entries:
            if not isinstance(entry, dict):
                continue
            slug = entry.get("hardware")
            if not isinstance(slug, str):
                continue
            yield slug, entry.get("type")


def load_thresholds(server_doc_root: Path) -> dict[str, dict[str, Thresholds]]:
    """Return per-host per-metric thresholds.

    Returns ``{host_name: {metric_key: Thresholds}}`` keyed by the bare host
    stem (filename without ``.yaml``). Returns an empty dict if the root or
    expected subdirectories don't exist — the TUI then runs with no
    thresholds applied (every cell stays status="ok").
    """
    machines_dir = server_doc_root / "machines"
    hardware_dir = server_doc_root / "hardware"
    if not machines_dir.is_dir() or not hardware_dir.is_dir():
        return {}

    slug_paths = _hardware_slug_paths(hardware_dir)
    out: dict[str, dict[str, Thresholds]] = {}

    for machine_path in sorted(machines_dir.glob("*.yaml")):
        host_name = machine_path.stem
        machine_doc = _load_yaml(machine_path)
        # metric -> list of (warn, crit) seen across this host's devices
        observed: dict[str, list[tuple[float | None, float | None]]] = {}

        for slug, _declared_type in _iter_machine_device_slugs(machine_doc):
            hw_path = slug_paths.get(slug)
            if hw_path is None:
                continue
            # category comes from the parent dir; that's the source of truth
            # because some machine entries list type and some don't.
            category = hw_path.parent.name
            metric = _DEVICE_TYPE_METRIC.get(category)
            if metric is None:
                continue
            hw_doc = _load_yaml(hw_path)
            thresholds_block = hw_doc.get("thresholds") or {}
            warn, crit = _device_temp(thresholds_block)
            if warn is None and crit is None:
                continue
            observed.setdefault(metric, []).append((warn, crit))

        if not observed:
            continue
        out[host_name] = {}
        for metric, pairs in observed.items():
            warns = [w for w, _ in pairs if w is not None]
            crits = [c for _, c in pairs if c is not None]
            out[host_name][metric] = Thresholds(
                warn=min(warns) if warns else None,
                crit=min(crits) if crits else None,
            )

    return out
