# TFC — TODO

- [x] Remove mock mode (`--mock`, `mock.py`, and all mock data references in `app.py`)
- [ ] Auto-discover peers from `/nodes` endpoint instead of requiring manual `bootstrap_peers` list
  - Add `_merge_discovered_peers()` to `TfcsDashboard`, called from `_do_poll` and `do_full_refresh`
  - Make `BaseHeatmap.node_names` updatable (axes rebuild every render, so just update the list)
  - Rebuild `OrgNodeTable` columns on node list change (DataTable columns are structural)
  - Re-run `load_tailscale_ip_map` after merging new peers
  - Return raw nodes list from `poll_cluster` return tuple
  - Track consecutive failures per host; back off after 3, evict after 10
  - Hybrid model: config bootstrap peers are never evicted, discovered peers can be added/evicted
  - Remove explicit `ntx_hosts` from config to let `_get_ntx_hosts()` auto-discover active nodes
