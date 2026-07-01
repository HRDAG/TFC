# Author: PB and cx-tfc
# Date: 2026-06-30
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_tui/risk.py

"""Deterministic cluster safety-risk classification."""

from __future__ import annotations

from dataclasses import dataclass

import humanize

from tfcs_tui.data import NodeDataStore, is_valid_velocity


@dataclass(frozen=True)
class Risk:
    severity: str
    message: str


@dataclass(frozen=True)
class Velocity:
    copies_per_min: float
    bytes_per_sec: float


def valid_velocity(value: dict | None) -> Velocity | None:
    """Normalize a velocity sample, rejecting absent or invalid measurements."""
    if not is_valid_velocity(value):
        return None
    try:
        copies_per_min = float(value["copies_per_min"])
        bytes_per_min = float(value["bytes_per_min"])
    except (KeyError, TypeError, ValueError):  # narrowed by is_valid_velocity
        return None
    return Velocity(copies_per_min, bytes_per_min / 60)


def _age_suffix(store: NodeDataStore, source: str) -> str:
    age = store.source_age(source)
    if age is None:
        return ""
    return f"; last known {humanize.naturaldelta(age)} ago"


def _activity(store: NodeDataStore) -> str:
    velocity = valid_velocity(store.velocity)
    if velocity is None:
        return "replication activity unavailable"
    byte_rate = (
        "0 bytes/s" if velocity.bytes_per_sec == 0
        else humanize.naturalsize(
            velocity.bytes_per_sec, binary=False, format="%.1f",
        ) + "/s"
    )
    rates = f"{velocity.copies_per_min:.1f} copies/min, {byte_rate}"
    if velocity.copies_per_min >= 0.1:
        return f"replication active: {rates}"
    return f"no material replication activity: {rates}"


def classify_risk(store: NodeDataStore, target_copies: int) -> Risk:
    """Return the highest supported replication risk."""
    replication_state = store.source_state("replication")
    if replication_state == "missing":
        return Risk("UNKNOWN", "replication safety data has never been obtained")

    sites_state = store.source_state("sites")
    site_dist = store.site_distribution
    zero_site = site_dist.get(0, 0)
    if zero_site:
        suffix = _age_suffix(store, "replication") if replication_state != "fresh" else ""
        return Risk(
            "CRITICAL",
            f"{zero_site:,} commits reported at zero sites{suffix}",
        )

    unreachable_sole = []
    oldest_status_age = 0.0
    for status in store.statuses:
        node_id = status.get("node_id", "")
        if (
            status.get("sole_holder_count", 0) > 0
            and store.node_status.get(node_id) in {"dead", "unreachable"}
        ):
            unreachable_sole.append(node_id.split(".")[0] or "?")
            oldest_status_age = max(
                oldest_status_age, float(status.get("_seen_age") or 0),
            )
    if unreachable_sole:
        ages = max(oldest_status_age, store.source_age("nodes") or 0)
        qualifier = (
            f"; last-known evidence up to {humanize.naturaldelta(ages)} old"
            if ages >= 30 else ""
        )
        return Risk(
            "CRITICAL",
            "sole copies last known on unreachable "
            + ", ".join(sorted(unreachable_sole))
            + qualifier,
        )

    if sites_state == "missing":
        return Risk("UNKNOWN", "site-distribution safety data is unavailable")
    if sites_state == "expired":
        return Risk("UNKNOWN", "site-distribution safety data expired")
    if replication_state == "expired":
        return Risk("UNKNOWN", "replication safety data expired")

    replication = store.replication
    unsatisfied = sum(
        count for copies, count in replication.items() if copies < target_copies
    )
    single_site = site_dist.get(1, 0)
    if single_site or store.cluster_sole_holders:
        count = max(single_site, store.cluster_sole_holders)
        return Risk(
            "WARN",
            f"{count:,} sole/single-site commits; {_activity(store)}",
        )
    if unsatisfied:
        return Risk(
            "WARN",
            f"{unsatisfied:,} commits below {target_copies} copies; {_activity(store)}",
        )
    if replication_state == "stale" or sites_state == "stale":
        return Risk(
            "WARN",
            "replication safety data stale" + _age_suffix(store, "replication"),
        )
    return Risk("OK", "current data; no known safety deficit")
