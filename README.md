# TFC — Data Pipeline & Infrastructure Overview

The Technology Freedom Cooperative (TFC) is a coalition of human rights
organizations that mutually support each other's storage infrastructure.

Every archive is encrypted so that only the organizational owner can decrypt
it; signed to affirm that only this organization could have created it; and
it has a cryptographic timestamp that proves it existed before a given
Bitcoin block.

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
│  │  nas         │  │      chll       │  │  scott  ant  ida         │   │
│  └──────────────┘  └─────────────────┘  │  lizo   myrtle           │   │
│                                          └──────────────────────────┘   │
│  ┌────────────────────────────────┐                                      │
│  │  Volunteer storage nodes       │      ┌──────────────────────────┐   │
│  │                                │      │  TechFutures (coloc.)    │   │
│  │  ipfs1 (HRDAG)                 │      │  kj (GPU)  ben (storage) │   │
│  │  snowball (HRDAG)              │      │  ← coming                │   │
│  │  meerkat (HRDAG)               │      └──────────────────────────┘   │
│  │  pihost (HRDAG)                │                                      │
│  │  alex (HRDAG)                  │                                      │
│  └────────────────────────────────┘                                      │
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
  ──────────────────────────── increasing recency ────────────────────────►

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
| [TFC](https://github.com/HRDAG/TFC) (this repo) | Infrastructure overview + real-time replication dashboard |

---

## The Archival Pipeline

```
  filelister — knows where your files are
  ────────────────────────────────────────
  Scans filesystem, tracks what's new or changed
  Catalogs file paths → PostgreSQL (scottfiles.paths)
        │
        ▼  new/changed paths
        │
  ntx — bundles files into sealed, provable commits
  ──────────────────────────────────────────────────
  Reads new paths from filelister in PostgreSQL
  Batches files into ~1 GB bundles, with error correction (par2)
  Encrypts each bundle with the owner's key — only the keyholder can read it
  Signs with org key + Bitcoin timestamp (OpenTimestamps)
  Result: only the owner can read it; only the owner could have made it; and provably timestamped.
  Deposits sealed commits → staging/
        │
        ▼  sealed commit packages in staging/
        │
  tfcs — ingests, then replicates across the coalition
  ─────────────────────────────────────────────────────
  Picks up commits from staging/ into its content-addressed store
  Replicates to other nodes; tracks copies-per-commit
```

> par2 error correction: [Parchive](https://wiki.archlinux.org/title/Parchive) · Bitcoin timestamping: [OpenTimestamps](https://en.wikipedia.org/wiki/OpenTimestamps)

## What Replication Means

```
                      The TFC Coalition
          ┌──────────────────────────────────────────────┐
          │                                              │
          │   HRDAG ←──────→ DataCivica ←──────→ II     │
          │     ↕                                ↕       │
          │   IJLA  ←──────────────────→ Km0            │
          │                                              │
          │      each org stores the others' data        │
          └──┬──────────────────────────────────┬────────┘
             │                                  │
    ┌────────┴────────┐                ┌─────────┴──────────┐
    │                 │                │                    │
    ▼                 ▼                ▼                    ▼
┌──────────┐   ┌───────────┐    ┌──────────┐   ┌──────────────────┐
│ archive  ├───┤ volunteer │    │  cloud   │   │ IPFS / Filecoin  │
│  nodes   │   │  nodes    │    │ storage  │   │    (planned)     │
│  chll    │   │ snowball  │    │ S3       │   │ decentralized    │
│  ben     │   │ meerkat   │    │ GDrive   │   │ permanent        │
│ (coming) │   │ pihost    │    │ Dropbox  │   │ storage          │
│          │   │ alex      │    │ Backbl.  │   │                  │
│          │   │ + future  │    │ (planned)│   │                  │
└──────────┘   └───────────┘    └──────────┘   └──────────────────┘
```

---

## Getting Started

Good entry points into the system:

- **[Security architecture](https://github.com/HRDAG/server-documentation/blob/main/architecture/security-architecture.md)** —
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

If you want to watch our dashboard running in real time, clone this repository to a machine that is authenticated to our tailnet, `cd` into this directory, and run this. 

```bash
uv run tfcs-tui -c config/tfcs-tui.toml   # live cluster
uv run tfcs-tui --mock                      # offline / development
```

The dashboard shows replication progress, node health, per-org breakdown, traffic heatmaps, and heartbeat freshness across all cluster nodes.
