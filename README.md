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
│  └──────────────┘  └─────────────────┘  │  lizo   dwight           │   │
│                                          └──────────────────────────┘   │
│  ┌────────────────────────────────┐                                      │
│  │  Storage nodes                 │      ┌──────────────────────────┐   │
│  │                                │      │  TechFutures (coloc.)    │   │
│  │  snowball  meerkat             │      │  kj (GPU)  ben (storage) │   │
│  │  pihost  lilpig                │      └──────────────────────────┘   │
│  │                                │                                      │
│  └────────────────────────────────┘                                      │
│  ┌────────────────────────────────┐                                      │
│  │  Hypervisors (Proxmox)         │                                      │
│  │  sugihara (Vancouver)          │                                      │
│  │  fred (Chicago / II)           │                                      │
│  └────────────────────────────────┘                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

Nodes come in four classes: **anchor** (multi-org ingest + replication
policy), **active** (ingest + replicate), **archive** (long-term backstop,
gets all commits), and **storage** (contribute capacity, respects trust
matching). Partner nodes are owned and operated by their respective
organizations; HRDAG coordinates but does not administer them.

Two **hypervisors** (`sugihara`, `fred`) sit outside these classes: they run
Proxmox and host service VMs rather than pipeline data, and will take over
infrastructure roles such as `gate`.

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
| [server-documentation](https://github.com/HRDAG/server-documentation) | Documents every machine we operate: hardware, network, storage, operational notes |
| [hrdag-ansible](https://github.com/HRDAG/hrdag-ansible) | Configures TFC machines: tailnet onboarding, SSH hardening, pipeline service deployment |
| [hrdag-monitor](https://github.com/HRDAG/hrdag-monitor) | Daily infrastructure health reports: vendor-researched thresholds, GREEN/YELLOW/RED classification |
| [sugihara-builds](https://github.com/HRDAG/sugihara-builds) | Build recipes + ops docs for the `sugihara` Proxmox host (Vancouver): immutable service VMs |
| [fred-builds](https://github.com/HRDAG/fred-builds) | Build recipes + ops docs for the `fred` Proxmox host (Chicago / II): immutable service VMs |
| [filelister](https://github.com/HRDAG/filelister) | First pipeline stage: scans filesystems, catalogs file metadata into PostgreSQL |
| [ntx](https://github.com/HRDAG/ntx) | Second stage: packages files into encrypted, signed, Bitcoin-timestamped commits |
| [tfcs](https://github.com/HRDAG/tfcs) | Third stage: replicates commits across the coalition until every commit survives any single failure |
| [TFC](https://github.com/HRDAG/TFC) (this repo) | Infrastructure overview + real-time replication dashboard |

---

## The Archival Pipeline

```
  filelister — knows where your files are
  ────────────────────────────────────────
  Scans filesystem, tracks what's new or changed
  Catalogs file paths → PostgreSQL (per-org database)
        │
        ▼  new/changed paths
        │
  ntx — bundles files into sealed, provable commits
  ──────────────────────────────────────────────────
  Reads new paths from filelister's database
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
          │   HRDAG ←──────→ DataCívica ←──────→ II     │
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
│ archive  │   │  storage  │    │  cloud   │   │ IPFS / Filecoin  │
│  nodes   │   │  nodes    │    │ storage  │   │    (planned)     │
│  chll    │   │ snowball  │    │ S3       │   │ decentralized    │
│  ben     │   │ meerkat   │    │ (planned)│   │ permanent        │
│          │   │ pihost    │    │          │   │ storage          │
│          │   │ lilpig    │    │          │   │                  │
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
  how the archival pipeline seals files into encrypted, timestamped commits

- **[tfcs README](https://github.com/HRDAG/tfcs/blob/main/README.md)** —
  how the replication cluster coordinates, and what the HTTP API exposes

- **[hrdag-monitor architecture](https://github.com/HRDAG/hrdag-monitor/blob/main/docs/ARCHITECTURE.md)** —
  how infrastructure health monitoring is structured and what each layer does

- **The TUI** — run `uv run tfcs-tui -c config/tfcs-tui.toml` from a tailnet
  machine to watch cluster state in real time

---

## Real-Time Dashboard

If you want to watch our dashboard running in real time, clone this
repository to a machine that is authenticated to our tailnet, `cd` into
this directory, and run this.

```bash
uv run tfcs-tui -c config/tfcs-tui.toml
```

The dashboard shows replication progress, node health, per-org breakdown,
traffic heatmaps, and heartbeat freshness across all cluster nodes.

---

## Fleet Health Dashboard

A second TUI focused on host-level health rather than pipeline traffic:
one row per machine, one column per signal (last-scrape, up, load, CPU /
HDD / SSD / NVMe / NIC temperatures, root and data filesystem fullness,
and the count of active tfcs pulls).

```bash
uv run tfcs-fleet-tui
```

It pulls metrics from Prometheus on `scott` and queries each tfcs node's
`/status` endpoint directly. Hosts that genuinely don't expose a given
sensor (no spinning HDDs, no NIC hwmon chip) render `--`; cells render
`?` only when the metric is expected but missing. For ZFS hosts, the
data column reports pool fullness aggregated across all datasets sharing
the pool, since per-dataset `node_filesystem_*` samples under-report
(every dataset reports the same `avail` and a near-zero used).

Configured in `config/tfcs-fleet-tui.toml`. Until Prometheus on scott is
bound to its tailnet IP (tracked in
[hrdag-ansible#474](https://github.com/HRDAG/hrdag-ansible/issues/474)),
this TUI needs an SSH tunnel:

```bash
ssh -L 9090:127.0.0.1:9090 scott
```

---

## `/tfcs-status` — Replication Convergence Report (Claude skill)

Unlike the two dashboards above, this is **not an app you run** — it is a
[Claude Code](https://docs.claude.com/en/docs/claude-code) **skill**. From a
Claude Code session in this repo (or in the
[tfcs](https://github.com/HRDAG/tfcs) repo, which carries a thin pointer to
the same skill), invoke:

```
/tfcs-status            # all orgs, 6/12/24/48h windows
/tfcs-status ii         # one org (ii = hrdag, km0 = datacivica)
/tfcs-status 6,24       # custom windows, in hours
```

Claude SSHes to `scott`, runs the analyzer over the snapshot series, and
writes a **convergence report**: per-org single-copy (single-holder)
replication rate, whether it is accelerating or stalling (recent windows vs
the 48h average), an ETA to clear the at-risk backlog, anchor seeding, and
per-puller transfer volume.

**You need SSH access to `scott`** (tailnet membership + your key) — the
skill reads cluster state there. It is **read-only**: it pulls the latest
tooling, runs the analyzer, and reads the series; it never repairs, deletes,
re-pulls, or otherwise mutates the cluster.

### Associated files

| File | Role |
|------|------|
| `.claude/skills/tfcs-status/SKILL.md` | The skill — run command, report shape, interpretation rules |
| `scripts/progress-windows.py` | Analyzer — reads the series, emits per-org/per-window deltas (stdlib-only) |
| `scripts/tfcs-monitor` | Collector — snapshots cluster state; installed on scott at `/usr/local/bin/tfcs-monitor`, run as `tfcs` via a systemd timer every 30 min |
| `deploy/tfcs-monitor.{service,timer}` | systemd units for the collector |
| `docs/runbooks/network-progress.md` | Runbook — how to read the report, plus SSH drill-down into node logs |
| `Makefile` | `make install` (host-detecting) / `migrate` / `verify` — deploy and operate the collector on scott |

The collector writes a world-readable JSONL time series to
`scott:/var/lib/tfcs-monitor/replication-progress.jsonl`; the analyzer reads
that file. It is a single-machine tool (scott only), installed via the
Makefile rather than ansible.
