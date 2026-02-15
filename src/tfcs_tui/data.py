# Author: PB and Claude
# Date: 2026-02-14
# License: (c) HRDAG, 2025, GPL-2 or newer
#
# ---
# src/tfcs_tui/data.py

"""Data acquisition — HTTP polling of tfcs cluster endpoints.

No tfcs code imports. Pure HTTP client.
"""

from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path

import aiohttp


# ---------------------------------------------------------------------------
# HTTP fetchers
# ---------------------------------------------------------------------------

async def fetch_status(
    session: aiohttp.ClientSession, host: str, http_port: int,
) -> dict | None:
    """GET /status from a single peer. Returns dict or None on failure."""
    url = f"http://{host}:{http_port}/status"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                return await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return None


async def fetch_nodes(
    session: aiohttp.ClientSession, host: str, http_port: int,
) -> list[dict] | None:
    """GET /nodes from a single peer. Returns list of node dicts or None."""
    url = f"http://{host}:{http_port}/nodes"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("nodes", [])
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return None


async def fetch_replication(
    session: aiohttp.ClientSession, host: str, http_port: int,
    target_copies: int,
) -> dict[int, int] | None:
    """GET /replication?target=N from a single peer.

    Returns {copies: count} dict or None on failure.
    Note: JSON keys are strings, we convert to int.
    """
    url = f"http://{host}:{http_port}/replication?target={target_copies}"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                dist = data.get("distribution", {})
                return {int(k): v for k, v in dist.items()}
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return None


# ---------------------------------------------------------------------------
# Cluster polling
# ---------------------------------------------------------------------------

async def poll_cluster(
    peer_hosts: list[str], http_port: int, target_copies: int,
) -> tuple[list[dict], dict[str, str], dict[str, float], dict[int, int]]:
    """Poll /status, /nodes, and /replication from all peers.

    Returns (statuses, node_status, heartbeat_age, replication) where:
      statuses       = list of /status response dicts (one per responding peer)
      node_status    = {node_id: "alive"|"suspect"|"dead"|"unreachable"}
      heartbeat_age  = {node_id: heartbeat_age_seconds}
      replication    = {copies: count} histogram (empty if endpoint unavailable)
    """
    async with aiohttp.ClientSession() as session:
        # Fetch /status from all peers concurrently
        tasks = [fetch_status(session, h, http_port) for h in peer_hosts]
        results = await asyncio.gather(*tasks)
        statuses = [r for r in results if r is not None]

        # Fetch /nodes from first responding peer for failure-detector view
        node_status: dict[str, str] = {}
        heartbeat_age: dict[str, float] = {}
        for host in peer_hosts:
            nodes = await fetch_nodes(session, host, http_port)
            if nodes is not None:
                node_status = {n["node_id"]: n["status"] for n in nodes}
                heartbeat_age = {n["node_id"]: n.get("heartbeat_age_seconds", 0.0) for n in nodes}
                break

        # Fetch /replication from first responding peer
        replication: dict[int, int] = {}
        for host in peer_hosts:
            repl = await fetch_replication(
                session, host, http_port, target_copies,
            )
            if repl is not None:
                replication = repl
                break

        # Mark peers that didn't respond to /status as unreachable
        responding_ids = {s["node_id"] for s in statuses}
        for nid in list(node_status):
            if nid not in responding_ids:
                node_status[nid] = "unreachable"

    return statuses, node_status, heartbeat_age, replication


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = Path("/etc/hrdag/tfcs-tui.toml")


def load_config(config_path: Path) -> dict:
    """Load TUI config from TOML.

    Expected keys:
        bootstrap_peers = ["host:port", ...]
        http_port = 8099
        target_copies = 3
        refresh_seconds = 10

    Returns dict with parsed values.
    """
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    peers = raw.get("bootstrap_peers", [])
    if not peers:
        raise SystemExit(f"config error: no bootstrap_peers in {config_path}")

    return {
        "peer_hosts": [bp.rsplit(":", 1)[0] for bp in peers],
        "http_port": raw.get("http_port", 8099),
        "target_copies": raw.get("target_copies", 3),
        "refresh_seconds": raw.get("refresh_seconds", 10),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def short(fqdn: str) -> str:
    """scott.hrdag.net -> scott"""
    return fqdn.split(".")[0]


def fmt_bytes(nbytes: int) -> str:
    """Human-readable: 31457280 -> '30M', 1100000000 -> '1.1G'"""
    mb = nbytes / 1_000_000
    if mb >= 1000:
        return f"{mb / 1000:.1f}G"
    return f"{mb:.0f}M"


def fmt_uptime(seconds: float) -> str:
    """86400.5 -> '24:00:00', 3661 -> '01:01:01', 59 -> '00:00:59'"""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


# ---------------------------------------------------------------------------
# Traffic matrix fetcher
# ---------------------------------------------------------------------------

async def fetch_node_traffic(
    session: aiohttp.ClientSession, host: str, http_port: int,
) -> dict | None:
    """GET /traffic from a single peer.

    Returns: {"node_id": ..., "traffic": {...}, "window_seconds": ..., ...} or None on failure
    """
    url = f"http://{host}:{http_port}/traffic"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                # Ensure node_id is present (use host if backend doesn't provide it)
                if "node_id" not in data:
                    data["node_id"] = host
                return data
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return None


async def poll_traffic_matrix(
    peer_hosts: list[str], http_port: int,
) -> list[dict]:
    """Poll /traffic from all peers concurrently.

    Returns: List of traffic reports from responding nodes.
             [{"node_id": "scott.hrdag.net", "traffic": {...},
               "window_seconds": 10.0, "samples_in_window": 4, ...}, ...]
    """
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_node_traffic(session, h, http_port) for h in peer_hosts]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# IP to hostname mapping
# ---------------------------------------------------------------------------

def load_tailscale_ip_map(peer_hosts: list[str] | None = None) -> dict[str, str]:
    """Parse tailscale status to map IPs to hostnames.

    Args:
        peer_hosts: Optional list of FQDNs to map short names to

    Returns: {"100.64.0.4": "chll.hrdag.net", ...}
    """
    import subprocess

    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    # Build short name -> FQDN map from peer_hosts
    short_to_fqdn = {}
    if peer_hosts:
        for fqdn in peer_hosts:
            short_name = short(fqdn)
            short_to_fqdn[short_name] = fqdn

    ip_map = {}
    for line in result.stdout.split('\n'):
        # Format: "100.64.0.4   chll    user    linux   active  ..."
        # NOTE: Column 2 is SHORT name, not FQDN!
        parts = line.split()
        if len(parts) >= 2:
            ip = parts[0]
            short_name = parts[1]
            if ip.startswith('100.'):  # Tailscale IP
                # Map short name to FQDN if available, otherwise use short name
                hostname = short_to_fqdn.get(short_name, short_name)
                ip_map[ip] = hostname

    return ip_map
