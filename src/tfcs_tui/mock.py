# Author: PB and Claude
# Date: 2026-02-14
# License: (c) HRDAG, 2025, GPL-2 or newer
#
# ---
# src/tfcs_tui/mock.py

"""Mock data for --mock mode. Matches /status endpoint shape."""

from __future__ import annotations

STATUSES = [
    {
        "node_id": "scott.hrdag.net",
        "node_class": "active",
        "cluster": "hrdag-ofc",
        "seq": 1234,
        "uptime_seconds": 864000.0,
        "alive_peers": 6,
        "active_claims": 0,
        "wants_count": 423,
        "haves_count": 138,
        "store_count": 138,
        "version": "0.2.6",
        "capacity_gb": 500.0,
        "free_gb": 250.0,
        "claims": [],
    },
    {
        "node_id": "lizo.hrdag.net",
        "node_class": "active",
        "cluster": "cdmx",
        "seq": 45,
        "uptime_seconds": 72000.0,
        "alive_peers": 6,
        "active_claims": 1,
        "wants_count": 423,
        "haves_count": 12,
        "store_count": 12,
        "version": "0.2.6",
        "capacity_gb": 2000.0,
        "free_gb": 1800.0,
        "sole_holder_count": 50,
        "claims": [{"commit": "547652abcdef", "source": "scott.hrdag.net",
                    "size": 52_428_800, "bytes_transmitted": 31_457_280,
                    "rate_mbps": 8.5}],
    },
    {
        "node_id": "chll.hrdag.net",
        "node_class": "archive",
        "cluster": "chll",
        "seq": 98,
        "uptime_seconds": 360000.0,
        "alive_peers": 6,
        "active_claims": 1,
        "wants_count": 423,
        "haves_count": 15,
        "store_count": 15,
        "version": "0.2.6",
        "capacity_gb": 2000.0,
        "free_gb": 1200.0,
        "claims": [{"commit": "3ed225fedcba", "source": "scott.hrdag.net",
                    "size": 48_000_000, "bytes_transmitted": 48_000_000,
                    "rate_mbps": 12.1}],
    },
    {
        "node_id": "ipfs1.hrdag.net",
        "node_class": "storage",
        "cluster": "1015svn",
        "seq": 856,
        "uptime_seconds": 500000.0,
        "alive_peers": 6,
        "active_claims": 2,
        "wants_count": 423,
        "haves_count": 85,
        "store_count": 85,
        "version": "0.2.6",
        "capacity_gb": 1000.0,
        "free_gb": 500.0,
        "claims": [
            {"commit": "868562aaa111", "source": "scott.hrdag.net",
             "size": 50_000_000, "bytes_transmitted": 5_000_000,
             "rate_mbps": 4.2},
            {"commit": "a1b2c3d4e5f6", "source": "meerkat.hrdag.net",
             "size": 35_000_000, "bytes_transmitted": 20_000_000,
             "rate_mbps": 11.0},
        ],
    },
    {
        "node_id": "meerkat.hrdag.net",
        "node_class": "storage",
        "cluster": "1015svn",
        "seq": 823,
        "uptime_seconds": 400000.0,
        "alive_peers": 6,
        "active_claims": 1,
        "wants_count": 423,
        "haves_count": 82,
        "store_count": 82,
        "version": "0.2.6",
        "capacity_gb": 1000.0,
        "free_gb": 900.0,
        "claims": [{"commit": "7f62ea999888", "source": "scott.hrdag.net",
                    "size": 50_000_000, "bytes_transmitted": 25_000_000,
                    "rate_mbps": 9.8}],
    },
    {
        "node_id": "pihost.hrdag.net",
        "node_class": "storage",
        "cluster": "hrdag-ofc",
        "seq": 810,
        "uptime_seconds": 350000.0,
        "alive_peers": 6,
        "active_claims": 2,
        "wants_count": 423,
        "haves_count": 80,
        "store_count": 80,
        "version": "0.2.6",
        "capacity_gb": 500.0,
        "free_gb": 42.0,
        "claims": [
            {"commit": "cc1122334455", "source": "scott.hrdag.net",
             "size": 45_000_000, "bytes_transmitted": 10_000_000,
             "rate_mbps": 3.1},
            {"commit": "dd6677889900", "source": "meerkat.hrdag.net",
             "size": 52_000_000, "bytes_transmitted": 52_000_000,
             "rate_mbps": 0.0},
        ],
    },
    {
        "node_id": "snowball.hrdag.net",
        "node_class": "storage",
        "cluster": "hrdag-ofc",
        "seq": 790,
        "uptime_seconds": 300000.0,
        "alive_peers": 5,
        "active_claims": 1,
        "wants_count": 423,
        "haves_count": 70,
        "store_count": 70,
        "version": "0.2.5",
        "capacity_gb": 2000.0,
        "free_gb": 1500.0,
        "claims": [{"commit": "ee1122aabb33", "source": "ipfs1.hrdag.net",
                    "size": 40_000_000, "bytes_transmitted": 38_000_000,
                    "rate_mbps": 15.2}],
    },
]

NODE_STATUS = {
    "scott.hrdag.net": "alive",
    "lizo.hrdag.net": "alive",
    "chll.hrdag.net": "alive",
    "ipfs1.hrdag.net": "alive",
    "meerkat.hrdag.net": "alive",
    "pihost.hrdag.net": "alive",
    "snowball.hrdag.net": "suspect",
}

HEARTBEAT_AGE = {
    "scott.hrdag.net": 13.2,
    "lizo.hrdag.net": 20.2,
    "chll.hrdag.net": 18.1,
    "ipfs1.hrdag.net": 0.7,
    "meerkat.hrdag.net": 22.9,
    "pihost.hrdag.net": 3.8,
    "snowball.hrdag.net": 20.6,
}

REPLICATION = {
    0: 180,
    1: 120,
    2: 80,
    3: 43,
}

SITE_DISTRIBUTION = {
    1: 20,   # 20 commits on only 1 site — alarm state
    2: 60,
    3: 80,
    4: 43,
}

# ---------------------------------------------------------------------------
# Traffic matrix mock data
# ---------------------------------------------------------------------------

TRAFFIC_REPORTS = [
    {
        "node_id": "scott.hrdag.net",
        "timestamp": 1708032145.2,
        "poll_interval_secs": 2.5,
        "window_seconds": 10.0,
        "samples_in_window": 4,
        "traffic": {
            "100.64.0.4": {   # chll
                "tx_rate_bytes_per_sec": 1200000.0,  # 1.2 MB/s
                "rx_rate_bytes_per_sec": 890000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 27000,
                "min_rtt_us": 25000,
                "max_rtt_us": 30000,
            },
            "100.64.0.20": {  # ipfs1
                "tx_rate_bytes_per_sec": 45000.0,  # 45 KB/s
                "rx_rate_bytes_per_sec": 120000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 15000,
                "min_rtt_us": 14000,
                "max_rtt_us": 18000,
            },
        },
    },
    {
        "node_id": "chll.hrdag.net",
        "timestamp": 1708032145.1,
        "poll_interval_secs": 2.5,
        "window_seconds": 10.0,
        "samples_in_window": 4,
        "traffic": {
            "100.64.0.30": {  # scott
                "tx_rate_bytes_per_sec": 890000.0,
                "rx_rate_bytes_per_sec": 1200000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 28000,
                "min_rtt_us": 26000,
                "max_rtt_us": 31000,
            },
            "100.64.0.20": {  # ipfs1
                "tx_rate_bytes_per_sec": 23000.0,  # 23 KB/s
                "rx_rate_bytes_per_sec": 450000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 22000,
                "min_rtt_us": 20000,
                "max_rtt_us": 25000,
            },
        },
    },
    {
        "node_id": "ipfs1.hrdag.net",
        "timestamp": 1708032145.3,
        "poll_interval_secs": 2.5,
        "window_seconds": 10.0,
        "samples_in_window": 4,
        "traffic": {
            "100.64.0.30": {  # scott
                "tx_rate_bytes_per_sec": 120000.0,  # 120 KB/s
                "rx_rate_bytes_per_sec": 45000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 16000,
                "min_rtt_us": 15000,
                "max_rtt_us": 18000,
            },
            "100.64.0.4": {  # chll
                "tx_rate_bytes_per_sec": 450000.0,  # 450 KB/s
                "rx_rate_bytes_per_sec": 23000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 21000,
                "min_rtt_us": 19000,
                "max_rtt_us": 24000,
            },
            "100.64.0.14": {  # lizo
                "tx_rate_bytes_per_sec": 8500000.0,  # 8.5 MB/s
                "rx_rate_bytes_per_sec": 8200000.0,
                "connections": 2,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 75000,
                "min_rtt_us": 70000,
                "max_rtt_us": 82000,
            },
            "100.64.0.32": {  # meerkat
                "tx_rate_bytes_per_sec": 2300000.0,  # 2.3 MB/s
                "rx_rate_bytes_per_sec": 2100000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 45000,
                "min_rtt_us": 42000,
                "max_rtt_us": 50000,
            },
            "100.64.0.51": {  # pihost
                "tx_rate_bytes_per_sec": 15000.0,  # 15 KB/s
                "rx_rate_bytes_per_sec": 12000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 18000,
                "min_rtt_us": 17000,
                "max_rtt_us": 20000,
            },
            "100.64.0.2": {  # snowball
                "tx_rate_bytes_per_sec": 1200000.0,  # 1.2 MB/s
                "rx_rate_bytes_per_sec": 1100000.0,
                "connections": 1,
                "retrans_per_sec": 0.0,
                "avg_rtt_us": 32000,
                "min_rtt_us": 30000,
                "max_rtt_us": 35000,
            },
        },
    },
]

IP_MAP = {
    "100.64.0.30": "scott.hrdag.net",
    "100.64.0.4": "chll.hrdag.net",
    "100.64.0.20": "ipfs1.hrdag.net",
    "100.64.0.14": "lizo.hrdag.net",
    "100.64.0.32": "meerkat.hrdag.net",
    "100.64.0.51": "pihost.hrdag.net",
    "100.64.0.2": "snowball.hrdag.net",
}

# ---------------------------------------------------------------------------
# Heartbeat matrix mock data (observer -> {observed -> age_seconds})
# ---------------------------------------------------------------------------

HEARTBEAT_MATRIX = {
    "scott.hrdag.net": {
        "scott.hrdag.net": 0.0,
        "lizo.hrdag.net": 2.3,
        "chll.hrdag.net": 3.1,
        "ipfs1.hrdag.net": 1.8,
        "meerkat.hrdag.net": 2.9,
        "pihost.hrdag.net": 1.2,
        "snowball.hrdag.net": 45.6,  # Stale
    },
    "lizo.hrdag.net": {
        "scott.hrdag.net": 2.5,
        "lizo.hrdag.net": 0.0,
        "chll.hrdag.net": 80.2,  # Very stale
        "ipfs1.hrdag.net": 3.1,
        "meerkat.hrdag.net": 2.8,
        "pihost.hrdag.net": 12.3,
        "snowball.hrdag.net": 150.0,  # Very stale
    },
    "chll.hrdag.net": {
        "scott.hrdag.net": 3.2,
        "lizo.hrdag.net": 78.5,  # Very stale
        "chll.hrdag.net": 0.0,
        "ipfs1.hrdag.net": 4.1,
        "meerkat.hrdag.net": 5.2,
        "pihost.hrdag.net": 3.8,
        "snowball.hrdag.net": 180.0,  # Very stale
    },
    "ipfs1.hrdag.net": {
        "scott.hrdag.net": 1.9,
        "lizo.hrdag.net": 2.8,
        "chll.hrdag.net": 3.9,
        "ipfs1.hrdag.net": 0.0,
        "meerkat.hrdag.net": 1.5,
        "pihost.hrdag.net": 2.1,
        "snowball.hrdag.net": 35.2,
    },
    "meerkat.hrdag.net": {
        "scott.hrdag.net": 3.0,
        "lizo.hrdag.net": 2.9,
        "chll.hrdag.net": 5.1,
        "ipfs1.hrdag.net": 1.6,
        "meerkat.hrdag.net": 0.0,
        "pihost.hrdag.net": 3.3,
        "snowball.hrdag.net": 42.1,
    },
    "pihost.hrdag.net": {
        "scott.hrdag.net": 1.3,
        "lizo.hrdag.net": 11.8,
        "chll.hrdag.net": 3.7,
        "ipfs1.hrdag.net": 2.2,
        "meerkat.hrdag.net": 3.4,
        "pihost.hrdag.net": 0.0,
        "snowball.hrdag.net": 38.9,
    },
    "snowball.hrdag.net": {
        "scott.hrdag.net": 44.2,
        "lizo.hrdag.net": 145.0,  # Very stale
        "chll.hrdag.net": 175.0,  # Very stale
        "ipfs1.hrdag.net": 36.8,
        "meerkat.hrdag.net": 40.5,
        "pihost.hrdag.net": 37.1,
        "snowball.hrdag.net": 0.0,
    },
}

# ---------------------------------------------------------------------------
# Velocity mock data (for ReplicationVelocity widget)
# ---------------------------------------------------------------------------

MOCK_VELOCITY = {
    "window_minutes": 10,
    "new_copies": 12,
    "copies_per_min": 7.8,
    "bytes_per_min": 1_500_000_000,
    "by_source": {
        "chll.hrdag.net": 4,
        "lizo.hrdag.net": 3,
        "scott.hrdag.net": 3,
        "snowball.hrdag.net": 2,
    },
}

# Velocity history mock data (for VelocityChart)
# ---------------------------------------------------------------------------

MOCK_VELOCITY_HISTORY = [
    ("14:00", 8.2), ("14:05", 9.1), ("14:10", 7.8),
    ("14:15", 10.3), ("14:20", 11.0), ("14:25", 9.5),
    ("14:30", 12.1), ("14:35", 10.8), ("14:40", 11.5),
    ("14:45", 13.2), ("14:50", 12.0), ("14:55", 14.1),
]


def make_mock_snapshots() -> list[dict]:
    """Build mock snapshots spanning 5 minutes for immediate velocity display.

    Three snapshots at -300s, -180s, -60s showing gradual replication progress.
    Current REPLICATION total = 0*180 + 1*120 + 2*80 + 3*43 = 409
    Oldest snapshot total    = 0*200 + 1*140 + 2*70 + 3*30 = 370
    delta = 39 copies in 300s = 7.8 copies/min
    """
    import time
    now = time.time()
    return [
        {
            "epoch": now - 300,
            "histogram": {"0": 200, "1": 140, "2": 70, "3": 30},
        },
        {
            "epoch": now - 180,
            "histogram": {"0": 192, "1": 132, "2": 74, "3": 35},
        },
        {
            "epoch": now - 60,
            "histogram": {"0": 185, "1": 125, "2": 78, "3": 40},
        },
    ]
