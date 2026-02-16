# Heatmap Extensions - Replication Activity & Data Freshness

## Current State
**Traffic Heatmap (implemented):**
- Shows bytes/sec between nodes (sender row → receiver col)
- Color scale: log-scaled from 0-80 MB/s
- Freshness dimming: cells dim when node not recently polled
- Data source: `/traffic` endpoint (tx_rate_bytes_per_sec, rx_rate_bytes_per_sec)

## Proposed Additional Heatmaps

### 1. RTT/Latency Heatmap ✓ READY TO BUILD

**What it shows:** Network round-trip time between nodes (health indicator)

**Data source:** `/traffic` endpoint already provides:
```json
{
  "traffic": {
    "peer_ip": {
      "avg_rtt_us": 1234,
      "min_rtt_us": 890,
      "max_rtt_us": 5678,
      ...
    }
  }
}
```

**Visualization:**
- Matrix: sender → receiver
- Metric: avg_rtt_us (microseconds)
- Color scale: Green (0-1ms) → Yellow (1-10ms) → Red (10-100ms) → Dark red (100ms+)
- Log scale: most LANs are <1ms, WANs are 10-100ms

**Implementation:**
- Reuse TrafficHeatmap widget structure
- Change metric extraction: `report["traffic"][peer_ip]["avg_rtt_us"]`
- Adjust color gradient for µs range
- Add "µs" suffix to labels

**Value:** Identify slow/congested network paths immediately

---

### 2. Connection Activity Heatmap ✓ READY TO BUILD

**What it shows:** Number of active TCP connections + aggregate bandwidth

**Data source:** `/traffic` endpoint provides:
```json
{
  "traffic": {
    "peer_ip": {
      "tx_rate_bytes_per_sec": 1500000,
      "rx_rate_bytes_per_sec": 800000,
      "connections": 3,  // ← number of active TCP connections
      ...
    }
  }
}
```

**Visualization:**
- Matrix: sender → receiver
- Metric: `connections` count (1-10+)
- Color scale: None (0) → Blue (1-2) → Cyan (3-5) → Green (6+)
- Or: Use bandwidth * connection_count as "activity score"

**Value:** See which node pairs have many parallel transfers (high activity)

---

### 3. Transfer Completion Rate Heatmap ⚠ NEEDS API ENHANCEMENT

**What it shows:** Success rate of transfers between nodes

**Data needed (not currently available):**
- Completed transfers per node-pair
- Failed transfers per node-pair
- Success rate = completed / (completed + failed)

**Would require tfcs changes:**
- Track transfer outcomes in state or separate log
- Expose via new `/transfer-stats` endpoint

**Visualization:**
- Matrix: sender → receiver
- Metric: success_rate (0.0-1.0)
- Color: Red (<80%) → Yellow (80-95%) → Green (>95%)

**Value:** Identify unreliable network paths or node pairs with issues

---

### 4. Claim Activity Heatmap ⚠ PARTIALLY AVAILABLE

**What it shows:** Which nodes are claiming commits from which sources

**Data currently available:** `/nodes` endpoint provides per-node aggregates:
```json
{
  "nodes": [
    {
      "node_id": "scott",
      "active_claims": 5,   // Total claims this node has
      "active_sends": 3,    // Total sources this node is pulling from
      ...
    }
  ]
}
```

**Problem:** No breakdown by source! We know "scott has 5 active claims" but not "scott is claiming 3 from meerkat, 2 from chll".

**Workaround:**
- Show aggregate "activity level" (claims count) per node
- Not a proper node-to-node heatmap without per-source breakdown

**Would need tfcs enhancement:**
- Expose claims with source information: `/claims` → `{claimer: {source: count}}`

---

### 5. Heartbeat Freshness Heatmap ⚠ NEEDS API ENHANCEMENT

**What it shows:** How recently each node heard from each peer (gossip health)

**Data currently available:** `/nodes` provides:
```json
{
  "nodes": [
    {
      "node_id": "scott",
      "status": "alive",
      "heartbeat_age_seconds": 2.3,  // ← This node's view of scott
      ...
    }
  ]
}
```

**Problem:** This is the **querying node's** view of all peers, not a peer-to-peer matrix.

**What we'd need:**
- Each node reports: "I last heard from X at time T"
- Aggregate into matrix: node_i's view of node_j's heartbeat age
- Endpoint: `/heartbeat-matrix` returning NxN age matrix

**Visualization:**
- Matrix: observer row → observed peer col
- Metric: seconds since last heartbeat
- Color: Green (0-5s) → Yellow (5-15s) → Red (15-300s) → Black (dead)

**Value:** Detect gossip issues (some nodes not hearing from others)

---

## Implementation Priority

### Phase 1: Build with existing data (no tfcs changes)
1. **RTT/Latency heatmap** - Easy win, immediate network health visibility
2. **Connection count heatmap** - Shows activity level, uses existing data

### Phase 2: Aggregate visualizations (partial data)
3. **Per-node activity widget** - Show active_claims and active_sends as bars/chart
   - Not a heatmap, but useful interim visualization

### Phase 3: Requires tfcs API enhancements
4. **Transfer completion rate heatmap** - Need transfer outcome tracking
5. **Claim activity heatmap** - Need per-source claim breakdown
6. **Heartbeat freshness heatmap** - Need peer-to-peer heartbeat matrix

---

## Concrete Next Steps

**Immediate (this session):**
1. Add RTT/latency as 4th tab (Heatmap-RTT)
2. Reuse TrafficHeatmap code, change metric and colors
3. Test with live data

**Short-term (next session):**
4. Design per-node activity widget for Overview tab
5. Show active_claims and active_sends as horizontal bars
6. Add to Overview below velocity widget

**Medium-term (future):**
7. Propose tfcs API enhancements for richer heatmaps
8. Design /claims endpoint (per-source breakdown)
9. Design /heartbeat-matrix endpoint

---

## Data Structures for New Endpoints (proposal)

**GET /claims** - Claim activity breakdown
```json
{
  "claims": {
    "scott": {          // claimer
      "meerkat": 3,     // source → count
      "chll": 2
    },
    "lizo": {
      "scott": 1
    }
  }
}
```

**GET /heartbeat-matrix** - Peer-to-peer heartbeat ages
```json
{
  "matrix": {
    "scott": {         // observer
      "meerkat": 2.3,  // observed → age_seconds
      "chll": 1.8,
      "lizo": 300.0    // stale/dead
    },
    "meerkat": {
      "scott": 2.5,
      "chll": 1.9
    }
  }
}
```

These would enable much richer replication and freshness visualizations.
