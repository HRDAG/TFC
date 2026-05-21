# Author: PB and Codex
# Date: 2026-05-18
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# src/tfcs_fleet_tui/tfcs.py

"""Temporary direct tfcs status polling for pull activity."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import aiohttp

from tfcs_fleet_tui.model import Cell


@dataclass(frozen=True)
class PullSummary:
    """Active pullers from one source host."""

    puller_count: int
    bytes_per_second: float


def _short_host(host: str) -> str:
    """Normalize FQDN-ish tfcs host names to dashboard row names."""
    return host.split(".", 1)[0]


def _format_rate(bytes_per_second: float) -> str:
    """Format rsync byte rate compactly for a narrow table cell."""
    if bytes_per_second >= 1_000_000:
        return f"{bytes_per_second / 1_000_000:.1f}M"
    if bytes_per_second >= 1_000:
        return f"{bytes_per_second / 1_000:.0f}K"
    return f"{bytes_per_second:.0f}"


def format_pull_summary(summary: PullSummary | None) -> str:
    """Format puller count and summed source bandwidth."""
    if summary is None or summary.puller_count == 0:
        return "0"
    if summary.bytes_per_second <= 0:
        return str(summary.puller_count)
    return f"{summary.puller_count}/{_format_rate(summary.bytes_per_second)}"


def pull_cell(summary: PullSummary | None) -> Cell:
    """Build a Cell carrying both the display text and the puller count as raw."""
    count = 0 if summary is None else summary.puller_count
    return Cell.of(count, format_pull_summary(summary))


async def _fetch_status(
    session: aiohttp.ClientSession,
    host: str,
    port: int,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    """Fetch one tfcs status document, returning None on host-local failure."""
    url = f"http://{host}:{port}/status"
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=timeout_seconds),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def fetch_pull_summaries(
    hosts: tuple[str, ...],
    port: int,
    timeout_seconds: int = 3,
) -> dict[str, PullSummary]:
    """Fetch tfcs statuses and aggregate active pulls by source host.

    A claim appears on the pulling machine and names the source. The dashboard
    wants the inverse: for each source host, how many distinct machines are
    pulling from it, plus the summed rsync rate for those claims.
    """
    if not hosts:
        return {}

    async with aiohttp.ClientSession() as session:
        statuses = await asyncio.gather(
            *(_fetch_status(session, host, port, timeout_seconds) for host in hosts)
        )
    if not any(status is not None for status in statuses):
        raise RuntimeError("no tfcs status endpoints reachable")

    pullers_by_source: dict[str, set[str]] = defaultdict(set)
    rate_by_source: dict[str, float] = defaultdict(float)

    for host, status in zip(hosts, statuses, strict=True):
        if not status:
            continue
        puller = _short_host(host)
        claims = status.get("claims", [])
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            source = claim.get("source")
            if not isinstance(source, str) or not source:
                continue
            source_host = _short_host(source)
            if source_host == puller:
                continue
            pullers_by_source[source_host].add(puller)
            try:
                rate_by_source[source_host] += float(claim.get("rsync_rate_bps", 0))
            except (TypeError, ValueError):
                pass

    return {
        source: PullSummary(
            puller_count=len(pullers),
            bytes_per_second=rate_by_source[source],
        )
        for source, pullers in pullers_by_source.items()
    }
