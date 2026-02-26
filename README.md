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

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              TFC Tailnet                                  │
│                                                                          │
│         gate — Tailscale control plane, auth key store                   │
│                            │                                             │
│        ┌───────────────────┼──────────────────────────┐                 │
│        ▼                   ▼                          ▼                 │
│                                                                          │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────────┐   │
│  │ HRDAG Office │  │ Chilliwack, BC  │  │  Partner nodes           │   │
│  │              │  │                 │  │                          │   │
│  │  scott  nas  │  │      chll       │  │  lizo (DataCivica)       │   │
│  └──────────────┘  └─────────────────┘  │  qnap_ii (II)           │   │
│                                          │  ant (Km0)              │   │
│  ┌────────────────────────────────┐      │  myrtle (IJLA)          │   │
│  │  Volunteer storage nodes       │      └──────────────────────────┘   │
│  │                                │                                      │
│  │  ipfs1  snowball  meerkat      │      ┌──────────────────────────┐   │
│  │  pihost  alex                  │      │  TechFutures (coloc.)    │   │
│  └────────────────────────────────┘      │  kj (GPU)  ben (storage) │   │
│                                          │  ← coming                │   │
│                                          └──────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

Nodes come in three classes: **active** (ingest + replicate), **archive**
(long-term retention), and **volunteer** (contribute storage capacity to
the network). Partner nodes are owned and operated by their respective
organizations; HRDAG coordinates but does not administer them.

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

| Repo | What it does |
|------|-------------|
| [server-documentation](https://github.com/HRDAG/server-documentation) | Machine inventory, hardware specs, network config, security architecture |
| [hrdag-ansible](https://github.com/HRDAG/hrdag-ansible) | Ansible playbooks: SSH, Tailscale, service deployment, user management |
| [hrdag-monitor](https://github.com/HRDAG/hrdag-monitor) | Infrastructure health monitoring. Prometheus + PostgreSQL. Daily email reports. |
| [filelister](https://github.com/HRDAG/filelister) | Scans filesystem, catalogs file paths into PostgreSQL |
| [ntx](https://github.com/HRDAG/ntx) | Packages files into encrypted + signed + timestamped commits |
| [tfcs](https://github.com/HRDAG/tfcs) | Replicates commits across the cluster. HTTP API on port 8099. |
| [TFC](https://github.com/HRDAG/tfcs-tui-app) (this repo) | Infrastructure overview + real-time replication dashboard |

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

## Getting Started

Good entry points into the system:

- **[Security architecture](https://github.com/HRDAG/server-documentation/blob/main/resources/security-architecture.md)** —
  how access, trust, and authentication work across the tailnet

- **[Fleet overview](https://github.com/HRDAG/server-documentation/blob/main/docs/README.md)** —
  all machines at a glance, organized by role

- **[Adding a new host](https://github.com/HRDAG/hrdag-ansible/blob/main/docs/adding-new-host.md)** —
  complete workflow for onboarding a machine into the tailnet and infrastructure

- **[ntx README](https://github.com/HRDAG/ntx/blob/main/README.md)** —
  how the archival pipeline works end to end, with diagrams and CLI reference

- **[tfcs README](https://github.com/HRDAG/tfcs/blob/main/README.md)** —
  how the replication cluster coordinates, and what the HTTP API exposes

- **[hrdag-monitor architecture](https://github.com/HRDAG/hrdag-monitor/blob/main/docs/ARCHITECTURE.md)** —
  how infrastructure health monitoring is structured and what each layer does

- **The TUI** — run `uv run tfcs-tui --mock` in this repo to see the cluster
  state without needing a live connection

---

## Real-Time Dashboard

To watch the tfcs backup running in real-time, clone this repo and run:

```bash
uv run tfcs-tui -c config/tfcs-tui.toml   # live cluster
uv run tfcs-tui --mock                      # offline / development
```

The dashboard shows replication progress, node health, per-org breakdown,
traffic heatmaps, and heartbeat freshness across all cluster nodes.
