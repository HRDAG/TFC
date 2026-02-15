# Traffic Matrix Enhancements Roadmap

**Author**: PB and Claude
**Date**: 2026-02-14
**Status**: Planning

---

## Current State (v0.1.0)

✅ **Implemented**:
- 7×7 bandwidth matrix (TX rate from row → column)
- Color gradient: cool→warm (blue/cyan/green/yellow/red)
- Tab switching (keybind `1`=Overview, `2`=Traffic)
- `/traffic` endpoint polling with mock data support
- IP→hostname mapping via `tailscale status`

📊 **Data Available** (from `/traffic` endpoint):
- `tx_rate_bytes_per_sec` / `rx_rate_bytes_per_sec` ✅ displayed
- `connections` - connection count per peer
- `retrans_per_sec` - TCP retransmit rate (congestion indicator)
- `avg_rtt_us`, `min_rtt_us`, `max_rtt_us` - latency metrics

---

## Phase 1: Network Quality Indicators

**Goal**: Add visual health indicators without cluttering bandwidth matrix

### 1.1 Cell Background Color by RTT
**What**: Color-code cell backgrounds by latency (green=fast, red=slow)
**Why**: Quick visual identification of slow links

```
Current:  "1.2M" [text color = bandwidth]
Enhanced: "1.2M" [text color = bandwidth, background = latency]

Background colors:
  Green:  < 50ms  (LAN, good)
  Yellow: 50-100ms (acceptable)
  Red:    > 100ms (slow, investigate)
```

**Implementation**:
- Add RTT thresholds to widget
- Modify `_format_cell()` to set background color
- Textual supports `bgcolor` in Text objects

**Decision needed**: Does background color interfere with text color readability?

---

### 1.2 Retransmission Warning Indicator
**What**: Show `!` suffix when packet loss detected
**Why**: Congestion/quality issues need immediate attention

```
Normal:  "1.2M"
Warning: "1.2M!"  (if retrans_per_sec > 1.0)
Alert:   "1.2M‼" (if retrans_per_sec > 5.0)
```

**Implementation**:
- Check `retrans_per_sec` in `_format_cell()`
- Append indicator to rate string
- Color indicator red for visibility

**Thresholds** (from backend spec):
- `0.0-1.0`: Normal (no indicator)
- `1.0-5.0`: Warning `!` (yellow)
- `>5.0`: Alert `‼` (red bold)

---

## Phase 2: Detailed Quality Table

**Goal**: Separate view for in-depth quality metrics

### 2.1 New Tab: "Quality" (keybind `3`)
**Layout**: Same 7×7 matrix, different metric

**Toggle modes** (keybind `m` to cycle):
1. **RTT view**: Show avg_rtt_us in ms
   ```
   From↓ To→   scott  chll  ipfs1
   scott          --   27ms  15ms
   chll         28ms    --   22ms
   ```

2. **Retrans view**: Show retrans_per_sec
   ```
   From↓ To→   scott  chll  ipfs1
   scott          --   0.0   0.0
   chll         0.1    --   0.0
   ```

3. **Connections view**: Show connection count
   ```
   From↓ To→   scott  chll  ipfs1
   scott          --    1     1
   ipfs1          1     1     --
   ```

**Color coding**:
- RTT: Green→Yellow→Red (fast→slow)
- Retrans: Green→Yellow→Red (clean→lossy)
- Connections: Blue→Cyan→Green (1→2→3+)

---

### 2.2 Combined Health Score
**What**: Single metric combining bandwidth, RTT, and retrans
**Why**: Overall link health at a glance

**Formula**:
```
health_score = (bandwidth_factor * 0.5) +
               (latency_factor * 0.3) +
               (loss_factor * 0.2)

Where:
  bandwidth_factor = min(tx_rate / 10MB, 1.0)  # >10MB = 1.0
  latency_factor = 1.0 - (rtt / 200ms)         # <200ms scaled
  loss_factor = 1.0 - min(retrans_per_sec / 5.0, 1.0)
```

**Display**: 0-100 score, color-coded
- 80-100: Green (excellent)
- 60-80: Yellow (acceptable)
- <60: Red (poor)

---

## Phase 3: Interactivity

### 3.1 Cell Selection & Details
**What**: Click/select cell to see detailed stats in footer
**Why**: Avoid cluttering matrix, show details on demand

**Footer panel when cell selected**:
```
scott → chll:
  Bandwidth: TX 1.2MB/s, RX 890KB/s
  Latency: 27ms avg (25-30ms range)
  Quality: 0.0 retrans/sec, 1 connection
  Status: ✓ Healthy
```

**Implementation**:
- Add cursor to TrafficMatrixTable
- Bind `Enter` or click to select
- Show detail panel below matrix or in footer

---

### 3.2 Time Series View
**What**: Line chart showing bandwidth over last 5 minutes
**Why**: Identify traffic patterns and spikes

**Future**: Requires backend to store historical data or TUI to buffer samples

---

## Phase 4: Advanced Features

### 4.1 Traffic Flow Diagram
**What**: Node graph showing traffic as arrows
**Why**: Visual representation of cluster traffic patterns

**Challenges**: ASCII art in terminal, or use Textual's Rich rendering

---

### 4.2 Alerts & Notifications
**What**: Highlight cells when thresholds exceeded
**Why**: Proactive monitoring

**Triggers**:
- Retrans > 5.0: Flash red
- RTT > 200ms: Flash yellow
- Bandwidth drops >50%: Warning

---

### 4.3 Export & Logging
**What**: Save traffic snapshots to CSV/JSON
**Why**: Historical analysis, debugging

---

## Implementation Priority

**Phase 1** (Quick wins, high value):
1. Retransmission warning indicator (`!`) - 1 hour
2. RTT background color - 2 hours

**Phase 2** (Moderate effort):
3. Quality tab with RTT/retrans views - 4 hours
4. Cell selection & detail panel - 3 hours

**Phase 3** (Future):
5. Combined health score - 4 hours
6. Time series view - 8+ hours (needs backend changes)

---

## Open Questions

1. **RTT background color**: Does it make text harder to read?
   - Test with actual data
   - May need to adjust text brightness

2. **Warning indicators**: Is `!` too subtle?
   - Alternative: Use emoji ⚠️
   - Or flash/blink the cell

3. **Quality tab**: Separate tab or overlay mode on traffic tab?
   - Separate = cleaner
   - Overlay = fewer keystrokes

4. **Historical data**: Should TUI buffer samples or rely on backend?
   - TUI buffer = simple, limited history (5-10 min)
   - Backend storage = complex, unlimited history

---

## Decision Log

**2026-02-14**: Decided to start with bandwidth matrix only, defer quality metrics to later phases. Focus on simple, clean display first.
