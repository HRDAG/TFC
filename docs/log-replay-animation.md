# Log Replay Animation Feature

## Concept
Historical playback of cluster state over time by replaying aggregated JSONL state files.

## Architecture

### Data Collection
- **Source:** State files from all nodes (`{state_dir}/{node_id}.jsonl`)
- **Aggregation:**
  - Rsync all node state files to one machine
  - Merge-sort by timestamp (all records have `ts` field)
  - Create unified timeline: `merged-replay.jsonl`
- **Timeline reconstruction:**
  - Parse merged log chronologically
  - Build WorldState incrementally
  - Snapshot cluster state at intervals (e.g., every 10 seconds)

### Playback Engine
```python
class ReplayEngine:
    def __init__(self, merged_log_path: Path):
        self.events = self._load_timeline(merged_log_path)
        self.current_time = 0
        self.speed = 1.0  # 1x, 10x, 100x, 1000x

    def seek(self, timestamp: str) -> WorldState:
        """Jump to specific time and return cluster state."""

    def step(self, delta_seconds: float) -> WorldState:
        """Advance timeline and return updated state."""

    def get_state_at(self, timestamp: str) -> WorldState:
        """Reconstruct WorldState at specific point in time."""
```

### Animated Visualizations

**Replication Histogram Animation**
- Watch commits move through buckets (1→2→3→4+)
- Highlight ingestion bursts (0→1 spike)
- Show convergence toward target over hours/days

**Traffic Heatmap Animation**
- See transfer patterns during ingestion
- Identify bottlenecks (which nodes stay red longest)
- Observe network effects (failures, slowdowns)

**Node Status Timeline**
- Alive/suspect/dead transitions
- Correlate with traffic drops
- See cluster stability over time

**Velocity Over Time**
- Plot replication velocity as line chart
- Overlay with events (node failures, ingestion bursts)
- Identify periods of stall vs progress

### UI/UX Controls
- **Playback:** Play/Pause/Stop buttons
- **Speed:** 1x, 10x, 100x, 1000x slider
- **Scrubber:** Timeline with markers for key events
- **Time range:** Start/end date picker
- **Annotations:** Mark ingestion events, failures, interventions

### Implementation Phases

**Phase 1: Data Preparation**
- [ ] Script to rsync state files from all nodes
- [ ] Merge-sort utility (preserves seq numbers, deduplicates)
- [ ] Validate merged timeline (no gaps, monotonic timestamps)

**Phase 2: Replay Engine**
- [ ] Event parser (JSONL → typed records)
- [ ] WorldState reconstruction at arbitrary timestamp
- [ ] Efficient seeking (index checkpoints every N records)

**Phase 3: Minimal Playback UI**
- [ ] Command-line playback mode (step through manually)
- [ ] Render dashboard snapshots to text files
- [ ] Verify state accuracy vs known events

**Phase 4: Interactive TUI**
- [ ] Add playback controls to dashboard (new mode?)
- [ ] Real-time scrubbing
- [ ] Export animations to video/GIF

**Phase 5: Analysis Tools**
- [ ] Identify anomalies (sudden traffic drops, stalls)
- [ ] Generate reports (time to N copies, transfer rates)
- [ ] Compare expected vs actual convergence

## Data Requirements

**Minimum viable:**
- All node state files (*.jsonl)
- Timestamps must be synchronized (NTP critical!)

**Optional enhancements:**
- Traffic logs (if available separately)
- Application logs (correlate transfers with events)
- System metrics (CPU, disk, network from monitoring)

## Open Questions
- How to handle clock skew between nodes?
- Should we replay in wall-clock time or event time?
- How to visualize multi-hour runs in reasonable time?
- Store snapshots vs recompute on-the-fly?

## Next Steps
1. Prototype log merge script
2. Test WorldState reconstruction accuracy
3. Design playback control UX
4. Implement frame-by-frame rendering
