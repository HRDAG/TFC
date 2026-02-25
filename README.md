Author: PB and Claude
Date: 2026-02-25
License: (c) HRDAG, 2026, GPL-2 or newer

---
tfcs-tui-app/README.md

# TFC Infrastructure — Overview & Monitor

This repository is the entry point for understanding the TFC distributed
infrastructure. It contains the real-time monitoring dashboard (`tfcs-tui`)
for the replication cluster, and this document is the map to everything else.

---

## What We're Doing

HRDAG is a founding member of the **Technology Freedom Cooperative (TFC)**, a
coalition of human rights organizations that mutually operate each other's
storage infrastructure. The goal is durable, verifiable preservation of
evidence — the kind that must survive organizational failure, government
seizure, or simple hardware death.

The core pipeline:

1. **Catalog** every file on our servers (filelister)
2. **Package** files into encrypted, signed, blockchain-timestamped archives (ntx)
3. **Replicate** those archives across 7 nodes owned by multiple organizations (tfcs)
4. **Monitor** replication health in real time (this repo)

No single organization holds all the data. No single node failure can destroy
it. Every archive has a cryptographic timestamp that proves it existed before a
given Bitcoin block.

---

## Quick Start — The TUI

Clone this repo and run the dashboard against the live cluster:

```bash
git clone <this-repo>
cd tfcs-tui-app
uv run tfcs-tui -c config/tfcs-tui.toml
```

Or run with mock data for development:

```bash
uv run tfcs-tui --mock
```

**Keybinds:**

| Key | Tab | Shows |
|-----|-----|-------|
| `1` | Replication | Copy distribution, velocity, ETA to target |
| `2` | Nodes | Node status, disk space, active transfers |
| `3` | Orgs | Per-organization replication breakdown |
| `4` | Traffic | 7×7 TX bandwidth heatmap |
| `5` | Latency | RTT heatmap (Tailscale mesh) |
| `6` | Heartbeats | Peer-to-peer heartbeat freshness |
| `r` | — | Force refresh |
| `q` | — | Quit |

The TUI polls each node's HTTP API (port 8099) once per second on a rolling
schedule. It needs `tailscale status` to resolve IP→hostname mappings.

---

## The Data Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  scott (primary ingest node)                                     │
│                                                                  │
│  Filesystem (~9M files)                                         │
│       │                                                          │
│       ▼  filelister (scans every N minutes)                     │
│  PostgreSQL: scottfiles.paths                                    │
│       │                                                          │
│       ▼  ntx-scan.timer (every 5 min)                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  1. Batch ~1GB of unarchived files                      │   │
│  │  2. BLAKE3 hash each file                               │   │
│  │  3. DAR archive → 50MB slices                           │   │
│  │  4. age encrypt (X25519)                                │   │
│  │  5. par2 parity (5% redundancy)                         │   │
│  │  6. SSH ed25519 sign manifest                           │   │
│  │  7. Submit Merkle root to OpenTimestamps                │   │
│  └────────────────────────────┬────────────────────────────┘   │
│                                │                                 │
│                  /var/tmp/ntx/staging/commit_<ts>/              │
│                                │                                 │
│                                ▼  tfcs-ingest                  │
│                  /var/tmp/tfcs/store/                           │
└────────────────────────────────┼────────────────────────────────┘
                                 │
                   tfcs replication (target: 4 copies)
                                 │
          ┌──────────┬───────────┼───────────┬──────────┐
          ▼          ▼           ▼           ▼          ▼
        lizo       chll       snowball     ipfs1    meerkat
     (DataCivica) (Chilliwack)            pihost
```

**Each commit is:** a sealed, encrypted, parity-protected, signed, and
Bitcoin-timestamped snapshot of a batch of files. Once confirmed on the
Bitcoin blockchain, the timestamp is permanent and unforgeable.

---

## Repository Map

All repos live at `../` relative to this one.

### Infrastructure

| Repo | What it does | Who runs it | Start here |
|------|-------------|-------------|------------|
| **server-documentation** | Machine inventory, hardware specs, network config, security architecture. YAML → generated markdown. | pball (from laptop) | `docs/README.md` → machine docs |
| **hrdag-ansible** | Ansible playbooks for provisioning: SSH setup, Tailscale enrollment, service deployment, user management | pball (from laptop) | `README.md` → `docs/adding-new-host.md` |

### The Archival Pipeline

| Repo | What it does | Runs on | Start here |
|------|-------------|---------|------------|
| **filelister** | Scans the filesystem, catalogs file metadata into PostgreSQL (`scottfiles.paths`). Supports live scanning and ingest-mode (delete after archive). | scott, lizo | `README.md` |
| **ntx** | Packages files into encrypted + signed + timestamped commits. Writes to `/var/tmp/ntx/staging`. Blockchain proof via OpenTimestamps. | scott, lizo | `README.md` |
| **tfcs** | Replicates ntx commits across the cluster (target: 4 copies). HTTP API on port 8099. Decentralized coordination. | all 7 nodes | `README.md` |

### Monitoring

| Repo | What it does | Frequency | Start here |
|------|-------------|-----------|------------|
| **tfcs-tui-app** (this repo) | Real-time dashboard: replication status, node health, traffic, latency | live (1s poll) | `README.md` (you're here) |
| **hrdag-monitor** | Infrastructure health: CPU/disk/SMART/UPS/GPU. Prometheus + PostgreSQL. Daily email reports. | daily | `docs/ARCHITECTURE.md` |

---

## The Cluster

Seven nodes participate in replication. Three are "board" nodes that
participate in coordination decisions.

| Node | Class | Trust Groups | Location | Notes |
|------|-------|-------------|----------|-------|
| **scott** | active | tfc_member, hrdag | HRDAG office | Ingest hub, 4-copy target, board |
| **lizo** | active | tfc_member, datacivica | DataCivica (partner) | DataCivica ingest + storage, QNAP |
| **chll** | archive | tfc_member, hrdag | Chilliwack, BC | Long-term retention, ZFS, board |
| **snowball** | storage | tfc_member, hrdag | HRDAG office | Additional local copy |
| **ipfs1** | storage | tfc_member, hrdag | HRDAG office | Board |
| **meerkat** | storage | tfc_member, hrdag | HRDAG office | |
| **pihost** | storage | tfc_member, hrdag | HRDAG office | |

**Trust groups** control which nodes can exchange data. `tfc_member` nodes
can replicate to each other across organizational boundaries. `hrdag` and
`datacivica` are intra-org subsets.

All nodes communicate over a **self-hosted Tailscale mesh** (Headscale on
gate). The TUI uses `tailscale status` to resolve IP addresses to hostnames.

### Incoming Partner Nodes

As the cooperative grows, new partner organizations deploy their own storage
nodes. Nodes currently being provisioned:

| Node | Partner | Status |
|------|---------|--------|
| qnap_ii | II | In progress |
| ant | Km0 | Planned |
| myrtle | IJLA | Planned |
| qnap_dc | DC | Planned |

---

## Key Locations on scott

| Path | Contents |
|------|----------|
| `/var/tmp/ntx/staging/` | ntx commits awaiting tfcs ingest |
| `/var/tmp/tfcs/store/` | tfcs local store (NVMe) |
| `/var/tmp/tfcs/state/` | tfcs replication state (JSONL) |
| `/etc/tfc/common.toml` | Shared TFC configuration (Ansible-managed) |
| `/etc/tfc/ntx.toml` | ntx-specific config |
| `/etc/tfc/tfcs.toml` | tfcs-specific config |
| `/var/lib/tfcs/diagnostics/snapshots/` | TUI snapshot files (velocity history) |
| `scottfiles` (PostgreSQL) | File catalog (filelister → ntx source) |

---

## For New Sysadmins

**If you're HRDAG staff:**

1. Read [server-documentation/docs/overview.md](../server-documentation/docs/overview.md) for the infrastructure map
2. Read [server-documentation/resources/security-architecture.md](../server-documentation/resources/security-architecture.md) for access model and trust boundaries
3. Run `uv run tfcs-tui -c config/tfcs-tui.toml` from this repo to see the cluster state
4. Read [server-documentation/docs/scott.md](../server-documentation/docs/scott.md) for the primary node

**If you're a partner org sysadmin (QNAP node):**

1. Your node is documented in [server-documentation/docs/lizo.md](../server-documentation/docs/lizo.md) (or your equivalent)
2. Your node runs `tfcs` as a Docker container — configuration in `hrdag-ansible/inventory/host_vars/<yourhost>.yml`
3. The replication status for your node is visible in the TUI (Nodes tab and Orgs tab)
4. Contact: HRDAG coordinates all TFC nodes. Reach out to pball for access issues.

---

## Configuration Reference

The TUI config (`config/tfcs-tui.toml`):

```toml
[tfcs]
bootstrap_peers = ["scott.hrdag.net", "lizo.hrdag.net", ...]
http_port = 8099
target_copies = 4
refresh_seconds = 10
```

---

## Development

```bash
# Install dependencies
uv sync

# Run with mock data (no cluster needed)
uv run tfcs-tui --mock

# Run against live cluster
uv run tfcs-tui -c config/tfcs-tui.toml
```

**Dependencies:** Python 3.14, textual>=0.50, aiohttp>=3.9, humanize>=4.15.0

Source layout:
- `src/tfcs_tui/app.py` — main app, message routing, polling loop
- `src/tfcs_tui/widgets.py` — all display widgets (6 tabs)
- `src/tfcs_tui/data.py` — HTTP polling, NodeDataStore, snapshot persistence
- `src/tfcs_tui/mock.py` — mock data for offline development
