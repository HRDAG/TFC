# TFC — TODO

## Done

- [x] Remove mock mode (`--mock`, `mock.py`, and all mock data references in `app.py`)

## In progress

### Peer auto-discovery — make every window honor `/nodes` (TFC#3)

Tracks https://github.com/HRDAG/TFC/issues/3 — dwight (and any other non-bootstrap node) is currently invisible across most TUI tabs because every per-node widget is keyed off the static `bootstrap_peers` list instead of the live node set.

**Plumbing**
- [ ] Return raw nodes list from `poll_cluster` return tuple
- [ ] Add `_merge_discovered_peers()` to `TfcsDashboard`; call from `_do_poll` and `do_full_refresh`
- [ ] Hybrid model: config bootstrap peers never evicted; discovered peers can be added/evicted
- [ ] Track consecutive failures per host; back off after 3, evict after 10
- [ ] Re-run `load_tailscale_ip_map` after merging new peers
- [ ] Fix `load_tailscale_ip_map` to build `short → FQDN` from discovered FQDNs too, not just bootstrap (so traffic/latency/heartbeats can resolve dwight's IP back to a FQDN)

**Per-widget fixes** (verify each by removing dwight from `bootstrap_peers` and confirming it still renders)

| Tab | Widget | What needs to change |
|---|---|---|
| 2 Nodes | `NodesTable` | Drive from `node_status` ∪ `statuses` keys, not just `statuses` |
| 2 Nodes | `TransfersTable` | Allow non-bootstrap node as destination (today dest = polled peer only) |
| 3 Orgs | `OrgNodeTable` | Rebuild columns on node-list change (DataTable columns are structural) |
| 4 Traffic | `TrafficHeatmap` | Make `BaseHeatmap.node_names` updatable; rebuild axes on node-list change |
| 5 Latency | `LatencyHeatmap` | Same as TrafficHeatmap (shares `BaseHeatmap`) |
| 6 Heartbeats | `HeartbeatMatrix` | Same — and also expand the observer set used by `fetch_heartbeat_matrix` |
| 7 Ingest | `IngestOverview` / `IngestNodeTable` / `IngestPipeline` | Drive ntx host list from discovered nodes with `node_class == 'active'`, not bootstrap |

**Config cleanup (after auto-discovery lands)**
- [ ] Remove explicit `ntx_hosts` from `config/tfcs-tui.toml` to let `_get_ntx_hosts()` auto-discover active nodes

## External / waiting

- **hrdag/tfcs#110** — API contract for `heartbeat_age_seconds: null` on copy-only `/nodes` rows. Once cc-tfcs decides the contract, replace the defensive `... or 0.0` patch in `data.py:165, 569` and `app.py:294` with the correct treatment (probably `float('inf')` for sort/color so copy-only nodes render as stale, not fresh).
