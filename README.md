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

No single organization holds all the data. No single node failure can destroy
it. Every archive has a cryptographic timestamp that proves it existed before a
given Bitcoin block.

---

## The Network

All nodes connect over a self-hosted Tailscale mesh (Headscale on `gate`).

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         TFC Tailnet (Headscale on gate)                  │
│                                                                          │
│  ┌──────────────────────────────────┐    ┌───────────────────┐          │
│  │         HRDAG Office             │    │   Chilliwack, BC   │          │
│  │                                  │    │                   │          │
│  │  scott   nas     snowball        │    │       chll        │          │
│  │  gate    ipfs1   meerkat  pihost │    │    (archive/ZFS)  │          │
│  └──────────────────────────────────┘    └───────────────────┘          │
│                                                                          │
│  ┌───────────────────┐    ┌───────────────────────────────────┐         │
│  │  DataCivica (DC)  │    │  Incoming partner nodes           │         │
│  │       lizo        │    │  qnap_ii (II)  ant (Km0)         │         │
│  │  (QNAP, active)   │    │  myrtle (IJLA)                   │         │
│  └───────────────────┘    └───────────────────────────────────┘         │
│                                                                          │
│  ┌──────────────────────────┐    ┌──────────────────────────────────┐   │
│  │  TechFutures (coloc.)    │    │  Future volunteer storage nodes  │   │
│  │  kj (GPU)  ben (storage) │    │  any org, anywhere               │   │
│  │  ← coming                │    │  open to TFC members             │   │
│  └──────────────────────────┘    └──────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Node roles

| Node | Class | Location | Notes |
|------|-------|----------|-------|
| **scott** | active | HRDAG office | Primary ingest hub, board node |
| **nas** | storage | HRDAG office | Local NAS (ZFS), not a tfcs node |
| **lizo** | active | DataCivica (DC) | DC ingest + storage, QNAP |
| **chll** | archive | Chilliwack, BC | Long-term retention, ZFS, board |
| **snowball** | storage | HRDAG office | Additional local copy |
| **ipfs1** | storage | HRDAG office | Board node |
| **meerkat** | storage | HRDAG office | |
| **pihost** | storage | HRDAG office | |
| **gate** | edge | HRDAG office | VPN gateway, Headscale |

---

## Understanding the Infrastructure

Four tools give four different views of the same system:

```
  ◄─────────────────────────── increasing recency ────────────────────────►

  "What machines        "How were they        "What went wrong     "What's happening
   do we have?"          set up?"              yesterday?"          right now?"
  ─────────────────     ─────────────────     ─────────────────    ─────────────────
  server-               hrdag-ansible         hrdag-monitor        tfcs-tui
  documentation                                                     (this repo)

  Machine inventory     Ansible playbooks     Prometheus           Replication live
  Hardware specs        SSH certificates      CPU / disk           Node health
  Network config        Tailscale setup       SMART / UPS          Traffic heatmaps
  Security arch         Service deploy        GPU / ZFS pools      Heartbeat matrix
                        User accounts         → daily email
```

### Repository map

All repos live at `../` relative to this one.

| Repo | What it does | Start here |
|------|-------------|------------|
| **server-documentation** | Machine inventory, hardware specs, network config, security architecture | `docs/README.md` |
| **hrdag-ansible** | Ansible playbooks: SSH, Tailscale, service deployment, user management | `README.md` → `docs/adding-new-host.md` |
| **hrdag-monitor** | Infrastructure health monitoring. Prometheus + PostgreSQL. Daily email reports. | `docs/ARCHITECTURE.md` |
| **filelister** | Scans filesystem, catalogs paths into PostgreSQL | `README.md` |
| **ntx** | Packages files into encrypted + signed + timestamped commits | `README.md` |
| **tfcs** | Replicates commits across the cluster. HTTP API on port 8099. | `README.md` |
| **TFC** (this repo) | Infrastructure overview + real-time replication dashboard | you're here |

---

## The Archival Pipeline

```
  filelister — knows where your files are
  ────────────────────────────────────────
  Scans filesystem, tracks what's new or changed
  Catalogs file paths → PostgreSQL (scottfiles.paths)
        │
        ▼
  ntx — bundles files into sealed, provable commits
  ──────────────────────────────────────────────────
  Batches ~1GB of files into one commit
  Hashes, archives, encrypts, adds parity
  Signs with org key, anchors to Bitcoin via OpenTimestamps
  Result: unforgeable proof that this data existed at this moment
        │
        ▼  sealed commit packages
        │
  tfcs — moves commits to safe machines
  ──────────────────────────────────────
  Replicates across 4+ nodes in multiple organizations
        │
   ┌────┴─────────────┬──────────────────────┬───────────────────┐
   ▼                  ▼                      ▼                   ▼
  partner nodes    rclone endpoints       IPFS / Filecoin      volunteer
  scott, lizo,     S3, Google Drive,      decentralized        nodes
  chll, ipfs1,     Dropbox, Backblaze     storage layer        (future)
  meerkat...       (cloud copies)         (planned)
```

---

## For New Sysadmins

**If you're HRDAG staff:**

1. Read [server-documentation/docs/overview.md](../server-documentation/docs/overview.md) for the infrastructure map
2. Read [server-documentation/resources/security-architecture.md](../server-documentation/resources/security-architecture.md) for the access model
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
