Author: PB and Claude
Date: 2026-02-25
License: (c) HRDAG, 2026, GPL-2 or newer

---
tfcs-tui-app/README.md

# TFC — Data Pipeline & Infrastructure Overview

This repository is the entry point for understanding the TFC distributed
archival infrastructure and the map to every related codebase.

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
3. **Replicate** those archives across nodes owned by multiple organizations (tfcs)

No single organization holds all the data. No single node failure can destroy
it. Every archive has a cryptographic timestamp that proves it existed before a
given Bitcoin block.

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
| **hrdag-monitor** | Infrastructure health: CPU/disk/SMART/UPS/GPU. Prometheus + PostgreSQL. Daily email reports. | scott | `docs/ARCHITECTURE.md` |

### The Archival Pipeline

| Repo | What it does | Runs on | Start here |
|------|-------------|---------|------------|
| **filelister** | Scans the filesystem, catalogs file metadata into PostgreSQL (`scottfiles.paths`). Supports live scanning and ingest-mode (delete after archive). | scott, lizo | `README.md` |
| **ntx** | Packages files into encrypted + signed + timestamped commits. Writes to `/var/tmp/ntx/staging`. Blockchain proof via OpenTimestamps. | scott, lizo | `README.md` |
| **tfcs** | Replicates ntx commits across the cluster (target: 4 copies). HTTP API on port 8099. Decentralized coordination. | all nodes | `README.md` |
| **TFC** (this repo) | Infrastructure overview (this document) + real-time replication dashboard | any node | `README.md` (you're here) |

---

## The Cluster

Seven nodes participate in replication. Three are "board" nodes that
participate in coordination decisions.

| Node | Class | Trust Groups | Location | Notes |
|------|-------|-------------|----------|-------|
| **scott** | active | tfc_member, hrdag | HRDAG office | Ingest hub, 4-copy target, board |
| **lizo** | active | tfc_member, datacivica | DataCivica (DC) | DC ingest + storage, QNAP |
| **chll** | archive | tfc_member, hrdag | Chilliwack, BC | Long-term retention, ZFS, board |
| **snowball** | storage | tfc_member, hrdag | HRDAG office | Additional local copy |
| **ipfs1** | storage | tfc_member, hrdag | HRDAG office | Board |
| **meerkat** | storage | tfc_member, hrdag | HRDAG office | |
| **pihost** | storage | tfc_member, hrdag | HRDAG office | |

**Trust groups** control which nodes can exchange data. `tfc_member` nodes
can replicate to each other across organizational boundaries. `hrdag` and
`datacivica` are intra-org subsets.

All nodes communicate over a **self-hosted Tailscale mesh** (Headscale on
gate). The replication dashboard uses `tailscale status` to resolve IP
addresses to hostnames.

### Incoming Partner Nodes

As the cooperative grows, new partner organizations deploy their own storage
nodes:

| Node | Partner | Status |
|------|---------|--------|
| qnap_ii | II | In progress |
| ant | Km0 | Planned |
| myrtle | IJLA | Planned |

---

## For New Sysadmins

**If you're HRDAG staff:**

1. Read [server-documentation/docs/overview.md](../server-documentation/docs/overview.md) for the infrastructure map
2. Read [server-documentation/resources/security-architecture.md](../server-documentation/resources/security-architecture.md) for access model and trust boundaries
3. Read [server-documentation/docs/scott.md](../server-documentation/docs/scott.md) for the primary node

**If you're a partner org sysadmin (QNAP node):**

1. Your node is documented in `server-documentation/docs/<yourhost>.md`
2. Your node runs `tfcs` as a Docker container — configuration in `hrdag-ansible/inventory/host_vars/<yourhost>.yml`
3. Contact: HRDAG coordinates all TFC nodes. Reach out to pball for access issues.

---

## Real-Time Dashboard

To watch the tfcs backup running in real-time, clone this repo and run:

```bash
uv run tfcs-tui -c config/tfcs-tui.toml   # live cluster
uv run tfcs-tui --mock                      # offline / development
```

The dashboard shows replication progress, node health, per-org breakdown,
traffic heatmaps, and heartbeat freshness across all cluster nodes.
