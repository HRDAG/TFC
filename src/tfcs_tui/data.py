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
import json
import logging
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
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
    target_copies: int, window_minutes: int = 10,
) -> tuple[dict[int, int], dict | None] | None:
    """GET /replication?target=N&window=W from a single peer.

    Returns (distribution, velocity) or None on failure.
      distribution: {copies: count} histogram (int keys)
      velocity: server-computed dict (copies_per_min, by_source, etc.) or None
    """
    url = f"http://{host}:{http_port}/replication?target={target_copies}&window={window_minutes}"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                dist = {int(k): v for k, v in data.get("distribution", {}).items()}
                velocity = data.get("velocity")  # None if endpoint doesn't support it yet
                return dist, velocity
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        pass
    return None


# ---------------------------------------------------------------------------
# Cluster polling
# ---------------------------------------------------------------------------

async def poll_cluster(
    peer_hosts: list[str], http_port: int, target_copies: int,
) -> tuple[list[dict], dict[str, str], dict[str, float], dict[int, int], dict | None]:
    """Poll /status, /nodes, and /replication from all peers.

    Returns (statuses, node_status, heartbeat_age, replication) where:
      statuses       = list of /status response dicts (one per responding peer)
      node_status    = {node_id: "alive"|"suspect"|"dead"|"unreachable"}
      heartbeat_age  = {node_id: heartbeat_age_seconds}
      replication    = {copies: count} histogram (empty if endpoint unavailable)
      velocity       = server-computed velocity dict or None
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
        velocity: dict | None = None
        for host in peer_hosts:
            result = await fetch_replication(
                session, host, http_port, target_copies,
            )
            if result is not None:
                replication, velocity = result
                break

        # Mark peers that didn't respond to /status as unreachable
        responding_ids = {s["node_id"] for s in statuses}
        for nid in list(node_status):
            if nid not in responding_ids:
                node_status[nid] = "unreachable"

    return statuses, node_status, heartbeat_age, replication, velocity


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = Path("/etc/hrdag/tfcs-tui.toml")
SNAPSHOT_DIR = Path("/var/lib/tfcs/diagnostics/snapshots")

_last_snapshot_epoch: float = 0.0
logger = logging.getLogger(__name__)


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


async def fetch_node_all(
    session: aiohttp.ClientSession,
    host: str,
    http_port: int,
    include_global: bool = False,
    target_copies: int = 3,
) -> tuple[dict | None, dict | None, list[dict] | None, dict[int, int] | None, dict | None]:
    """Fetch /status and /traffic from a single node.

    If include_global is True, also fetch /nodes and /replication
    (these are cluster-wide views, so only needed once per cycle).

    Returns: (status, traffic, nodes_list, replication, velocity)
    """
    # Always fetch per-node endpoints concurrently
    status_task = fetch_status(session, host, http_port)
    traffic_task = fetch_node_traffic(session, host, http_port)

    if include_global:
        # Fetch global endpoints as well
        nodes_task = fetch_nodes(session, host, http_port)
        repl_task = fetch_replication(session, host, http_port, target_copies)

        # Gather all four endpoints concurrently
        status, traffic, nodes_list, repl_result = await asyncio.gather(
            status_task, traffic_task, nodes_task, repl_task,
            return_exceptions=False,
        )
        replication, velocity = repl_result if repl_result is not None else (None, None)
    else:
        # Only fetch per-node endpoints
        status, traffic = await asyncio.gather(
            status_task, traffic_task,
            return_exceptions=False,
        )
        nodes_list = None
        replication = None
        velocity = None

    return status, traffic, nodes_list, replication, velocity


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


# ---------------------------------------------------------------------------
# NodeDataStore
# ---------------------------------------------------------------------------

@dataclass
class NodeSnapshot:
    """All data from a single node's most recent poll."""
    node_id: str
    status_response: dict | None = None    # Raw /status JSON
    traffic_response: dict | None = None   # Raw /traffic JSON
    node_status: str = "unknown"           # From /nodes endpoint
    heartbeat_age: float = 0.0             # From /nodes endpoint
    last_updated: float = 0.0              # time.monotonic() when polled


class NodeDataStore:
    """In-memory accumulator for rolling node polls."""

    def __init__(self) -> None:
        self._nodes: dict[str, NodeSnapshot] = {}  # node_id -> snapshot
        self._replication: dict[int, int] = {}      # copies -> count
        self._node_status: dict[str, str] = {}      # node_id -> alive/suspect/dead
        self._heartbeat_age: dict[str, float] = {}  # node_id -> seconds
        self._heartbeat_matrix: dict[str, dict[str, float]] = {}  # observer -> {observed -> age}
        self._cycle_count: int = 0                  # Increments each poll
        self._velocity: dict | None = None          # Server-computed velocity from /replication

    def update_node(self, node_id: str, status: dict | None, traffic: dict | None) -> None:
        """Update data for a single node after polling it."""
        if node_id not in self._nodes:
            self._nodes[node_id] = NodeSnapshot(node_id=node_id)

        snapshot = self._nodes[node_id]
        if status is not None:
            snapshot.status_response = status
        if traffic is not None:
            snapshot.traffic_response = traffic
        snapshot.last_updated = time.monotonic()
        self._cycle_count += 1

    def update_global(self, node_status: dict[str, str],
                      heartbeat_age: dict[str, float],
                      replication: dict[int, int],
                      heartbeat_matrix: dict[str, dict[str, float]] | None = None,
                      velocity: dict | None = None) -> None:
        """Update global data (from /nodes and /replication endpoints)."""
        self._node_status = node_status
        self._heartbeat_age = heartbeat_age
        self._replication = replication
        if heartbeat_matrix is not None:
            self._heartbeat_matrix = heartbeat_matrix
        if velocity is not None:
            self._velocity = velocity

        # Update per-node snapshots with status and heartbeat data
        for node_id, status in node_status.items():
            if node_id not in self._nodes:
                self._nodes[node_id] = NodeSnapshot(node_id=node_id)
            self._nodes[node_id].node_status = status

        for node_id, age in heartbeat_age.items():
            if node_id not in self._nodes:
                self._nodes[node_id] = NodeSnapshot(node_id=node_id)
            self._nodes[node_id].heartbeat_age = age

    @property
    def statuses(self) -> list[dict]:
        """All accumulated /status responses (for Overview tab widgets)."""
        return [
            snapshot.status_response
            for snapshot in self._nodes.values()
            if snapshot.status_response is not None
        ]

    @property
    def replication(self) -> dict[int, int]:
        """Replication distribution histogram."""
        return self._replication

    @property
    def node_status(self) -> dict[str, str]:
        """Node status map (alive/suspect/dead/unreachable)."""
        return self._node_status

    @property
    def heartbeat_age(self) -> dict[str, float]:
        """Heartbeat age in seconds per node."""
        return self._heartbeat_age

    @property
    def traffic_reports(self) -> list[dict]:
        """All accumulated /traffic responses (for Traffic/Heatmap widgets)."""
        return [
            snapshot.traffic_response
            for snapshot in self._nodes.values()
            if snapshot.traffic_response is not None
        ]

    @property
    def cycle_count(self) -> int:
        """Number of node updates performed (for heatmap freshness tracking)."""
        return self._cycle_count

    @property
    def heartbeat_matrix(self) -> dict[str, dict[str, float]]:
        """Heartbeat age matrix: observer -> {observed -> age_seconds}."""
        return self._heartbeat_matrix

    @property
    def velocity(self) -> dict | None:
        """Server-computed velocity from /replication?window=N endpoint."""
        return self._velocity


async def fetch_heartbeat_matrix(
    peer_hosts: list[str], http_port: int, session: aiohttp.ClientSession,
) -> dict[str, dict[str, float]]:
    """Fetch /nodes from ALL peers to build heartbeat age matrix.
    
    Returns: {observer_node: {observed_node: heartbeat_age_seconds}}
    """
    matrix: dict[str, dict[str, float]] = {}
    
    # Query /nodes from each peer concurrently
    tasks = []
    for host in peer_hosts:
        tasks.append(fetch_nodes(session, host, http_port))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Build matrix from results
    for host, result in zip(peer_hosts, results):
        if isinstance(result, list) and result:
            # result is the nodes list from this peer's perspective
            observer = host  # This peer is observing others
            matrix[observer] = {}

            for node_info in result:
                observed = node_info.get("node_id")
                hb_age = node_info.get("heartbeat_age_seconds", 0.0)
                if observed:
                    matrix[observer][observed] = hb_age

    return matrix


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def compute_total_copies(histogram: dict[int, int]) -> int:
    """Weighted sum of copies: sum(copies * count).

    Accepts dict[int, int] matching NodeDataStore.replication.
    No int() cast needed — keys are already int from fetch_replication().
    """
    return sum(copies * count for copies, count in histogram.items())


def save_snapshot(
    replication: dict[int, int], velocity_data: dict | None, timestamp: float,
) -> None:
    """Write JSON snapshot to disk, rate-limited to once per 60 seconds.

    Matches cluster-metrics.py snapshot format (string keys in JSON).
    Handles PermissionError/OSError gracefully — logs warning, does not crash.
    """
    global _last_snapshot_epoch
    if timestamp - _last_snapshot_epoch < 60:
        return

    # Convert int keys to string keys for JSON compatibility
    histogram = {str(k): v for k, v in replication.items()}
    total_copies = compute_total_copies(replication)
    total = sum(replication.values())
    satisfied = sum(v for k, v in replication.items() if k >= 3)
    sat_pct = round(satisfied / total * 100, 1) if total else 0.0

    dt = datetime.fromtimestamp(timestamp)
    snapshot = {
        "ts": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "epoch": round(timestamp, 1),
        "histogram": histogram,
        "total_copies": total_copies,
        "satisfied": satisfied,
        "satisfaction_pct": sat_pct,
        "velocity": velocity_data,
    }

    ts_file = dt.strftime("%Y%m%d-%H%M%S")
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / f"{ts_file}.json"
        path.write_text(json.dumps(snapshot, indent=2) + "\n")
        _last_snapshot_epoch = timestamp
    except (PermissionError, OSError) as exc:
        logger.warning("snapshot write failed: %s", exc)


def load_recent_snapshots(window_seconds: float = 600.0) -> list[dict]:
    """Load recent JSON snapshots from disk within time window.

    Returns list of parsed dicts sorted by epoch (oldest first).
    Default window is 10 minutes — wider than the 5-min rolling window
    so we have enough history to compute velocity immediately.
    """
    import time

    if not SNAPSHOT_DIR.exists():
        return []
    cutoff = time.time() - window_seconds
    snaps = []
    for p in SNAPSHOT_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("epoch", 0) >= cutoff:
                snaps.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    snaps.sort(key=lambda s: s.get("epoch", 0))
    return snaps


def load_velocity_history() -> list[tuple[str, float]]:
    """Load (HH:MM, copies_per_min) from all snapshots on disk.

    Returns chronologically sorted list. Skips snapshots without velocity data.
    """
    if not SNAPSHOT_DIR.exists():
        return []
    snaps = []
    for p in SNAPSHOT_DIR.glob("*.json"):
        try:
            snaps.append(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    snaps.sort(key=lambda s: s.get("epoch", 0))

    history = []
    for snap in snaps:
        vel = snap.get("velocity")
        if vel is None or vel.get("copies_per_min") is None:
            continue
        cpm = vel["copies_per_min"]
        if cpm > 5.0:
            continue  # Skip artifactual readings
        epoch = snap.get("epoch", 0)
        dt = datetime.fromtimestamp(epoch)
        label = dt.strftime("%H:%M")
        history.append((label, cpm))
    return history
