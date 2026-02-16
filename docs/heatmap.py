#!/usr/bin/env python3
"""
Network traffic heat map animation for terminal.
10x10 matrix: rows=senders, cols=receivers.
Diagonal cells show a placeholder pattern.
Off-diagonal cells colored by traffic intensity (0-40M).

IMPLEMENTATION NOTES FOR INTEGRATION
=====================================

Context: this is a standalone curses prototype. Target deployment is as a
window/widget in a Textual TUI, driven by claude-code on a linux server.

1. LOG SCALING
   Real network traffic is heavy-tailed. Linear color mapping will pin most
   cells cold with a few outliers blazing. Replace the linear mapping in
   traffic_color_pair() with:
       t = math.log1p(value) / math.log1p(MAX_TRAFFIC)
   This spreads the gradient across the perceptually interesting range.
   If you have a known baseline (e.g., most links idle at ~500K), consider
   a piecewise or quantile-based mapping instead.

2. DATA FEED
   Replace evolve_traffic() with your actual data source. The matrix is
   just matrix[i][j] = int, where i=sender, j=receiver, value in [0, 40M].
   Sources might be SNMP counters, netflow aggregates, /proc/net/dev deltas,
   prometheus scrapes, etc. The refresh loop doesn't care where the numbers
   come from — just write into the matrix between frames.

3. NODE NAMES
   Change NODE_NAMES to actual hostnames or short identifiers. If names are
   longer than 3-4 chars, increase LEFT_MARGIN and possibly TOP_MARGIN to
   keep alignment. Column headers may need rotation or abbreviation at >5ch.

4. TEXTUAL INTEGRATION
   This prototype uses curses directly. For Textual:
   - The color gradient logic (make_gradient, traffic_color_pair) ports
     directly — Textual supports Rich-style truecolor.
   - Replace curses drawing with a Textual Widget subclass. Use Rich Text
     objects with background colors for cells, or a Static/DataTable variant.
   - Textual's set_interval() replaces the sleep/timeout loop.
   - The matrix state and evolve logic are framework-independent.
   - Consider using Rich's Color.from_rgb() for the gradient cells and
     rendering each cell as a Rich Text span with a background color.
   - Textual's reactive attributes can trigger redraws when matrix updates.

5. REFRESH RATE
   Currently 150ms (~6.7fps). For real monitoring:
   - Poll interval should match your data source granularity (typically 1-5s
     for SNMP, sub-second for netflow).
   - Decouple data acquisition from rendering: feed data via asyncio queue
     or shared state, render on a fixed timer.
   - If the TUI has other widgets competing for attention, 500ms-1s refresh
     is plenty for a heat map — the eye tracks color drift, not frame rate.

6. CELL SIZING
   Currently CELL_W=6, CELL_H=2, fitting 10x10 in ~65x25 chars. If this
   is one pane of a multi-pane TUI, you may need to shrink to CELL_W=4,
   CELL_H=1 (still readable as color blocks). At CELL_H=1, drop the
   diagonal animation to a single static glyph.

7. COLOR SUPPORT
   This assumes 256-color terminal support (curses.init_color). Most modern
   terminals (gnome-terminal, kitty, alacritish, iTerm2) handle this fine.
   If running over SSH to a remote tmux, verify TERM is set to something
   that advertises color support (xterm-256color or better). Textual/Rich
   handle truecolor natively, so this is mainly a concern for the curses
   prototype.

8. GRADIENT PALETTE
   Current gradient: black → blue → cyan → green → yellow → red.
   For accessibility or preference, easy to swap — just edit the stops list
   in make_gradient(). A sequential single-hue gradient (black → orange, or
   black → white) is often easier to read than a rainbow. The perceptually
   uniform colormaps from matplotlib (viridis, inferno, magma) are good
   references if you want to port one.

Press 'q' or ESC to quit.
"""

import curses
import time
import random
import math

NUM_NODES = 10
MAX_TRAFFIC = 40_000_000
NODE_NAMES = [f"n{i:02d}" for i in range(NUM_NODES)]

# Cell dimensions in characters
CELL_W = 6
CELL_H = 2

# Layout offsets (leave room for labels)
LEFT_MARGIN = 5
TOP_MARGIN = 3


def make_gradient():
    """Build a gradient: black -> blue -> cyan -> green -> yellow -> red -> white."""
    stops = [
        (0.0,  (0, 0, 0)),
        (0.15, (0, 0, 180)),
        (0.3,  (0, 140, 180)),
        (0.45, (0, 180, 0)),
        (0.65, (200, 200, 0)),
        (0.85, (220, 80, 0)),
        (1.0,  (255, 60, 60)),
    ]
    gradient = []
    n_colors = 64
    for i in range(n_colors):
        t = i / (n_colors - 1)
        # find surrounding stops
        for si in range(len(stops) - 1):
            t0, c0 = stops[si]
            t1, c1 = stops[si + 1]
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
                r = int(c0[0] + frac * (c1[0] - c0[0]))
                g = int(c0[1] + frac * (c1[1] - c0[1]))
                b = int(c0[2] + frac * (c1[2] - c0[2]))
                gradient.append((r, g, b))
                break
    return gradient


def init_colors(gradient):
    """Set up curses color pairs from gradient. Pairs 1..64 for gradient,
    pair 65 for diagonal, pair 66 for labels."""
    curses.start_color()
    curses.use_default_colors()
    for i, (r, g, b) in enumerate(gradient):
        # curses RGB is 0-1000
        cid = 16 + i  # avoid clobbering default colors
        curses.init_color(cid, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
        curses.init_pair(i + 1, cid, cid)  # fg=bg so block is solid

    # diagonal: dim gray on dark gray
    curses.init_color(90, 300, 300, 300)
    curses.init_color(91, 150, 150, 150)
    curses.init_pair(65, 90, 91)

    # labels: white on default
    curses.init_color(92, 800, 800, 800)
    curses.init_pair(66, 92, 0)

    # header
    curses.init_color(93, 500, 500, 600)
    curses.init_pair(67, 93, 0)

    # legend text
    curses.init_pair(68, 92, 0)


def traffic_color_pair(value):
    """Map a traffic value (0..MAX_TRAFFIC) to a curses color pair index (1..64)."""
    t = max(0.0, min(1.0, value / MAX_TRAFFIC))
    idx = int(t * 63)
    return idx + 1


def init_traffic():
    """Initialize traffic matrix with random values."""
    matrix = []
    for i in range(NUM_NODES):
        row = []
        for j in range(NUM_NODES):
            if i == j:
                row.append(0)
            else:
                row.append(random.randint(0, MAX_TRAFFIC))
        matrix.append(row)
    return matrix


def evolve_traffic(matrix):
    """Random walk the traffic values with autocorrelation."""
    for i in range(NUM_NODES):
        for j in range(NUM_NODES):
            if i == j:
                continue
            old = matrix[i][j]
            # drift: biased random walk with momentum
            delta = random.gauss(0, MAX_TRAFFIC * 0.08)
            # occasional spikes
            if random.random() < 0.02:
                delta += random.choice([-1, 1]) * MAX_TRAFFIC * 0.4
            new = old + delta
            # soft clamp with bounce
            new = max(0, min(MAX_TRAFFIC, new))
            matrix[i][j] = int(new)
    return matrix


def draw_cell(win, row, col, pair_idx):
    """Draw a single cell as a solid color block."""
    y = TOP_MARGIN + row * CELL_H
    x = LEFT_MARGIN + col * CELL_W
    block = " " * CELL_W
    for dy in range(CELL_H):
        try:
            win.addstr(y + dy, x, block, curses.color_pair(pair_idx))
        except curses.error:
            pass


def draw_diagonal_cell(win, row, col, frame):
    """Draw a diagonal cell with an animated dot pattern."""
    y = TOP_MARGIN + row * CELL_H
    x = LEFT_MARGIN + col * CELL_W
    pair = curses.color_pair(65)
    patterns = ["·•·•·•", "•·•·•·"]
    for dy in range(CELL_H):
        pat = patterns[(frame + dy) % 2]
        try:
            win.addstr(y + dy, x, pat[:CELL_W], pair)
        except curses.error:
            pass


def draw_labels(win):
    """Draw row and column labels."""
    label_pair = curses.color_pair(66)
    # column headers
    for j in range(NUM_NODES):
        x = LEFT_MARGIN + j * CELL_W + 1
        try:
            win.addstr(TOP_MARGIN - 1, x, NODE_NAMES[j], label_pair)
        except curses.error:
            pass
    # row labels
    for i in range(NUM_NODES):
        y = TOP_MARGIN + i * CELL_H + (CELL_H // 2)
        try:
            win.addstr(y, 0, NODE_NAMES[i], label_pair)
        except curses.error:
            pass


def draw_legend(win, gradient):
    """Draw a color legend below the matrix."""
    y = TOP_MARGIN + NUM_NODES * CELL_H + 2
    label_pair = curses.color_pair(68)
    try:
        win.addstr(y, LEFT_MARGIN, "0", label_pair)
        # draw gradient bar
        bar_len = min(40, len(gradient))
        for i in range(bar_len):
            gi = int(i * (len(gradient) - 1) / (bar_len - 1))
            win.addstr(y, LEFT_MARGIN + 2 + i, " ", curses.color_pair(gi + 1))
        win.addstr(y, LEFT_MARGIN + 2 + bar_len + 1, "40M", label_pair)
    except curses.error:
        pass


def draw_header(win):
    """Draw title."""
    pair = curses.color_pair(67)
    try:
        win.addstr(0, LEFT_MARGIN, "Network Traffic: sender (row) → receiver (col)", pair)
    except curses.error:
        pass


def main(stdscr):
    curses.curs_set(0)  # hide cursor
    stdscr.nodelay(True)  # non-blocking input
    stdscr.timeout(150)   # refresh interval ms

    gradient = make_gradient()
    init_colors(gradient)

    matrix = init_traffic()
    frame = 0

    while True:
        # check for quit
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):  # q or ESC
            break

        stdscr.erase()
        draw_header(stdscr)
        draw_labels(stdscr)
        draw_legend(stdscr, gradient)

        for i in range(NUM_NODES):
            for j in range(NUM_NODES):
                if i == j:
                    draw_diagonal_cell(stdscr, i, j, frame)
                else:
                    pair = traffic_color_pair(matrix[i][j])
                    draw_cell(stdscr, i, j, pair)

        stdscr.refresh()
        evolve_traffic(matrix)
        frame += 1


if __name__ == "__main__":
    curses.wrapper(main)
