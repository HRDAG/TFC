# Plan: Unified Datastore with Rolling Updates

## Context

### Original Request
Consolidate the two separate polling loops (cluster every 10s burst, traffic every 1s rolling) into a single rolling poller that hits one node at a time for ALL endpoints, feeding a unified in-memory datastore. All widgets update every second from accumulated data.

### Current Architecture (Problems)
1. **Split polling** -- `_refresh_cluster` polls ALL nodes simultaneously every 10 seconds for `/status`, `/nodes`, `/replication`. This creates burst load and 10-second staleness on the Overview tab.
2. **Rolling traffic** -- `_refresh_traffic_single_node` polls ONE node per second for `/traffic`. This is the correct pattern but only feeds the Traffic/Heatmap tabs.
3. **Two message types** -- `ClusterData` and `TrafficData` are separate messages with separate handlers, creating artificial separation.
4. **Redundant fetching** -- `poll_cluster()` hits ALL nodes for `/status`, then tries each node sequentially for `/nodes` and `/replication`. With 7 nodes, this is 7+ HTTP requests in a burst.
5. **Data inconsistency** -- Overview tab data can be up to 10 seconds old while Traffic tab data is at most ~7 seconds old (one full rolling cycle).

### Research Findings
- Codebase is small: 3 source files (~600 lines), 1 mock file, simple `pyproject.toml` with `uv` build.
- Widget `refresh_data()` signatures are the main API boundary.
- `poll_traffic_matrix()` (all-nodes concurrent) exists in `data.py` but is already unused -- the app uses `fetch_node_traffic()` directly.
- Heatmap freshness tracking uses `_cell_update_cycle` / `_current_cycle` counters keyed on `updated_node` -- this must be preserved.
- Mock mode bypasses polling entirely and posts static data once on startup.
- The `/nodes` and `/replication` endpoints are "global" views -- any single node can answer them. Currently fetched from "first responder" which is correct and should be preserved.
- No tests exist. No Makefile.

## Work Objectives

### Core Objective
Replace the dual-polling architecture with a unified datastore + single rolling poller, so ALL tabs update every second with accumulated data and no burst load occurs.

### Deliverables
1. **`NodeDataStore` class** in `data.py` -- in-memory accumulator for all per-node data
2. **Unified rolling poller** in `app.py` -- one node per second, ALL endpoints
3. **Single `NodeUpdated` message** replacing both `ClusterData` and `TrafficData`
4. **Updated widget `refresh_data()` calls** -- all widgets read from the datastore
5. **Updated mock mode** -- populates the datastore directly

### Definition of Done
- Single `set_interval(1.0, ...)` timer in `on_mount` (no 10-second timer)
- All three tabs update every second
- Heatmap freshness dimming still works (tracks which node was just polled)
- `--mock` mode still works
- No burst polling of all nodes simultaneously
- `/nodes` and `/replication` fetched once per full cycle (not every tick)

## Guardrails

### Must Have
- Rolling one-node-at-a-time polling pattern
- All widgets update on every tick (1 second)
- Heatmap freshness dimming preserved
- Mock mode preserved
- Graceful handling of node fetch failures (skip, try next tick)
- `/nodes` and `/replication` fetched only once per full N-node cycle

### Must NOT Have
- No new dependencies
- No new files (all changes in existing `data.py`, `app.py`, `widgets.py`, `mock.py`)
- No changes to the TOML config format
- No changes to widget visual appearance
- No concurrent/burst polling of multiple nodes
- Do NOT remove `poll_cluster()` or `poll_traffic_matrix()` from `data.py` -- they may be useful for forced full-refresh (the `r` key)

## Task Flow

```
Task 1: NodeDataStore class
    |
    v
Task 2: Unified fetch function (per-node, all endpoints)
    |
    v
Task 3: Refactor app.py polling loop + new message type
    |
    v
Task 4: Update widget refresh_data calls
    |
    v
Task 5: Update mock mode
    |
    v
Task 6: Manual smoke test
```

All tasks are sequential -- each depends on the previous.

## Detailed Tasks

### Task 1: Add `NodeDataStore` class to `data.py`

**What:** Add a `NodeDataStore` class that accumulates per-node data from rolling polls.

**Design:**
```python
import time
from dataclasses import dataclass, field

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
        self._cycle_count: int = 0                  # Increments each poll

    def update_node(self, node_id: str, status: dict | None, traffic: dict | None) -> None:
        """Update data for a single node after polling it."""
        ...

    def update_global(self, node_status: dict[str, str],
                      heartbeat_age: dict[str, float],
                      replication: dict[int, int]) -> None:
        """Update global data (from /nodes and /replication endpoints)."""
        ...

    @property
    def statuses(self) -> list[dict]:
        """All accumulated /status responses (for Overview tab widgets)."""
        ...

    @property
    def replication(self) -> dict[int, int]:
        ...

    @property
    def node_status(self) -> dict[str, str]:
        ...

    @property
    def heartbeat_age(self) -> dict[str, float]:
        ...

    @property
    def traffic_reports(self) -> list[dict]:
        """All accumulated /traffic responses (for Traffic/Heatmap widgets)."""
        ...

    @property
    def cycle_count(self) -> int:
        ...
```

**Acceptance criteria:**
- Class exists in `data.py`
- Properties return accumulated data in the same shapes widgets already expect
- `update_node()` stores/overwrites per-node data
- `update_global()` stores /nodes and /replication data
- Thread-safe not required (Textual is single-threaded event loop)

### Task 2: Add `fetch_node_all()` to `data.py`

**What:** A single async function that fetches ALL endpoints from ONE node.

**Design:**
```python
async def fetch_node_all(
    session: aiohttp.ClientSession,
    host: str,
    http_port: int,
    include_global: bool = False,
    target_copies: int = 3,
) -> tuple[dict | None, dict | None, list[dict] | None, dict[int, int] | None]:
    """Fetch /status and /traffic from a single node.

    If include_global is True, also fetch /nodes and /replication
    (these are cluster-wide views, so only needed once per cycle).

    Returns: (status, traffic, nodes_list, replication)
    """
```

**Key decisions:**
- Fetch `/status` and `/traffic` concurrently with `asyncio.gather` (both go to same host)
- Only fetch `/nodes` and `/replication` when `include_global=True` (once per cycle)
- On failure of any individual endpoint, return None for that endpoint (don't fail the whole fetch)
- Reuse the existing `fetch_status()`, `fetch_node_traffic()`, `fetch_nodes()`, `fetch_replication()` functions internally

**Acceptance criteria:**
- Function exists in `data.py`
- Uses existing per-endpoint fetchers
- Returns tuple of (status, traffic, nodes, replication) with None for failures
- `include_global` flag controls whether /nodes and /replication are fetched

### Task 3: Refactor `app.py` polling and messages

**What:** Replace dual polling with single rolling loop + unified message.

**Changes:**
1. Replace `ClusterData` and `TrafficData` messages with single `NodeUpdated` message
2. Replace `_refresh_cluster` + `_refresh_traffic_single_node` with single `_poll_next_node`
3. Add `NodeDataStore` instance to `TfcsDashboard.__init__`
4. Single `set_interval(1.0, self._poll_next_node)` in `on_mount`
5. `_poll_next_node` determines if this tick is the "global fetch" tick (first node of each cycle)
6. Single `on_node_updated` handler that refreshes ALL widgets

**New message:**
```python
class NodeUpdated(Message):
    """Posted when a single node poll completes."""
    def __init__(self, updated_node: str) -> None:
        super().__init__()
        self.updated_node = updated_node
```

**Polling logic:**
```python
def _poll_next_node(self) -> None:
    host = self._peer_hosts[self._current_node_index]
    # Fetch global data on first node of each cycle
    include_global = (self._current_node_index == 0)
    self._current_node_index = (self._current_node_index + 1) % len(self._peer_hosts)
    self.run_worker(lambda: self._do_poll(host, include_global), exclusive=False)
```

**Handler:**
```python
def on_node_updated(self, message: NodeUpdated) -> None:
    """Update ALL widgets from the datastore."""
    store = self._store
    # Overview widgets
    self.query_one(ReplicationChart).refresh_data(store.replication, self._target_copies)
    self.query_one(NodesTable).refresh_data(store.statuses, store.node_status, store.heartbeat_age)
    self.query_one(TransfersTable).refresh_data(store.statuses)
    # Traffic widgets
    self.query_one(TrafficMatrixTable).refresh_data(store.traffic_reports)
    self.query_one(TrafficHeatmap).refresh_data(store.traffic_reports, message.updated_node)
    # Title bar
    self._update_title_bar()
```

**Manual refresh (`r` key):** Keep `action_refresh` but have it do a full burst poll via the existing `poll_cluster()` + `poll_traffic_matrix()` to populate the datastore immediately, then post `NodeUpdated`. This is the one case where burst polling is acceptable (explicit user action).

**Acceptance criteria:**
- Only one `set_interval` call in `on_mount` (1-second rolling)
- No 10-second timer
- All widgets update on every tick
- `updated_node` passed through for heatmap freshness
- `r` key does a full immediate refresh
- Import of `poll_cluster` retained for `action_refresh`
- Remove `_traffic_data` dict (replaced by datastore)

### Task 4: Update widget `refresh_data()` signatures (if needed)

**What:** Verify and adjust widget APIs. Based on analysis, NO signature changes should be needed because:
- `ReplicationChart.refresh_data(repl, target_copies)` -- same data shape from `store.replication`
- `NodesTable.refresh_data(statuses, node_status, heartbeat_age)` -- same shapes from store properties
- `TransfersTable.refresh_data(statuses)` -- same
- `TrafficMatrixTable.refresh_data(reports)` -- same
- `TrafficHeatmap.refresh_data(reports, updated_node)` -- same

The only potential issue: `NodesTable` and `TransfersTable` currently call `self.clear()` and rebuild from scratch every refresh. With 1-second updates instead of 10-second, this may cause visible flicker. If flicker is observed, consider optimizing to update-in-place rather than clear+rebuild. But this is an optimization to evaluate during smoke testing, not a requirement for this task.

**Acceptance criteria:**
- All widgets receive data in the format they expect
- No widget signature changes required (verify only)
- If flicker is observed, note it as a follow-up task (do not fix in this plan)

### Task 5: Update mock mode

**What:** Update `action_refresh` mock path to populate the `NodeDataStore` instead of posting the old message types.

**Changes to `action_refresh`:**
```python
if self._mock:
    from tfcs_tui.mock import (HEARTBEAT_AGE, NODE_STATUS, REPLICATION,
                                STATUSES, TRAFFIC_REPORTS)
    # Populate the datastore
    for s in STATUSES:
        self._store.update_node(s["node_id"], status=s, traffic=None)
    for r in TRAFFIC_REPORTS:
        self._store.update_node(r["node_id"], status=None, traffic=r)
    self._store.update_global(NODE_STATUS, HEARTBEAT_AGE, REPLICATION)
    self.post_message(NodeUpdated(updated_node="mock"))
```

**Acceptance criteria:**
- `--mock` flag still launches app with data displayed
- All three tabs show data in mock mode
- No polling timers started in mock mode (existing behavior preserved)

### Task 6: Manual smoke test

**What:** Verify all three modes work.

**Test procedure:**
1. `uv run tfcs-tui --mock` -- verify all 3 tabs display correctly
2. `uv run tfcs-tui -c config/tfcs-tui.toml` -- verify live rolling updates on all tabs
3. Press `r` -- verify immediate full refresh
4. Switch between tabs with `1`, `2`, `3` -- verify title bar updates
5. On heatmap tab, observe freshness dimming -- verify cells dim for nodes not recently polled

**Acceptance criteria:**
- All 3 tabs render correctly in mock mode
- Live mode shows rolling updates on all tabs
- No Python tracebacks
- Heatmap dimming works
- `r` key triggers immediate full refresh

## Commit Strategy

Single commit after all tasks complete and smoke test passes:

```
Consolidate polling into unified datastore with rolling updates

Replace dual-timer architecture (10s burst + 1s rolling) with single
1-second rolling poller that fetches all endpoints from one node per
tick. NodeDataStore accumulates data; all widgets update every second.

By PB & Claude
```

## Success Criteria

1. **Uniform 1-second updates** -- All three tabs refresh every second
2. **No burst load** -- Only one node polled per tick (except manual `r` refresh)
3. **Data freshness** -- Overview tab data now at most ~7 seconds old (one full cycle) instead of 10 seconds
4. **Heatmap dimming** -- Still tracks per-node freshness correctly
5. **Behavioral parity** -- Mock mode, `r` key, tab switching, title bar all work as before
6. **Code reduction** -- Net fewer lines (two message types collapse to one, two handlers collapse to one, two timers collapse to one)

## Risk Assessment

**Low risk:**
- Widget signatures unchanged -- no cascading breakage
- Rolling pattern already proven for traffic -- extending it to cluster data
- Small codebase with clear boundaries

**Medium risk:**
- 1-second NodesTable/TransfersTable rebuilds may cause flicker (mitigation: observe during smoke test, defer optimization if needed)
- `/nodes` and `/replication` only refresh once per cycle (~7 seconds with 7 nodes). This is slightly slower than current 10-second burst for these specific endpoints, but the tradeoff is correct: uniform freshness across all data is more valuable than slightly faster global-view updates.

**Mitigated:**
- `poll_cluster()` and `poll_traffic_matrix()` preserved for `r` key full-refresh, so no loss of immediate-refresh capability.
