# Author: PB and Claude
# Date: 2026-02-14
# License: (c) HRDAG, 2025, GPL-2 or newer
#
# ---
# src/tfcs_tui/app.py

"""tfcs cluster dashboard — textual TUI app.

Production: tfcs-tui                                (reads /etc/hrdag/tfcs-tui.toml)
Dev:        tfcs-tui -c config/tfcs-tui.toml
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from tfcs_fleet_tui.config import FleetConfig, load_config as load_fleet_config
from tfcs_fleet_tui.source import FleetDataSource
from tfcs_fleet_tui.widgets import FleetTable
from tfcs_tui.data import (
    DEFAULT_CONFIG,
    NodeDataStore,
    fetch_nodes,
    fetch_node_all,
    fetch_replication,
    load_config,
    load_tailscale_ip_map,
    load_velocity_history,
    poll_cluster,
    poll_ntx_statuses,
    poll_traffic_matrix,
    save_snapshot,
    short,
)
from tfcs_tui.risk import classify_risk
from tfcs_tui.widgets import (
    ClusterOverview,
    HeartbeatMatrix,
    IngestNodeTable,
    IngestOverview,
    IngestPipeline,
    LatencyHeatmap,
    NodesTable,
    OrgNodeTable,
    OrgsTable,
    ReplicationChart,
    ReplicationVelocity,
    RiskBanner,
    SourceUtilization,
    TrafficHeatmap,
    TransfersTable,
    VelocityChart,
)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class NodeUpdated(Message):
    """Posted when a single node poll completes."""
    def __init__(self, updated_node: str) -> None:
        super().__init__()
        self.updated_node = updated_node


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class TfcsDashboard(App):
    """Cluster dashboard TUI — window 1."""

    TITLE = "tfcs dashboard"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_replication", "Replication", show=False),
        Binding("2", "tab_nodes", "Nodes", show=False),
        Binding("3", "tab_orgs", "Orgs", show=False),
        Binding("4", "tab_movement", "Movement", show=False),
        Binding("5", "tab_ingest", "Ingest", show=False),
        Binding("6", "tab_fleet", "Fleet", show=False),
        Binding("7", "tab_debug", "Debug", show=False),
        Binding("m", "toggle_movement_mode", "Movement mode"),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
    ]

    DEFAULT_CSS = """
    Screen {
        layout: vertical;
    }
    #title-bar {
        background: blue;
        color: white;
        text-style: bold;
        padding: 0 1;
        height: 1;
    }
    .tab-desc {
        color: $text-muted;
        padding: 0 1;
        height: 1;
    }
    .source-stale {
        opacity: 60%;
    }
    .hidden {
        display: none;
    }
    """

    def __init__(
        self,
        peer_hosts: list[str],
        http_port: int = 8099,
        ntx_port: int = 9401,
        target_copies: int = 3,
        refresh_seconds: int = 10,
        ntx_hosts: list[str] | None = None,
        retired_peers: list[str] | None = None,
        backoff_failures: int = 3,
        evict_failures: int = 10,
        fleet_config: FleetConfig | None = None,
        clock=None,
    ) -> None:
        super().__init__()
        # Bootstrap hosts come from config and are never evicted. Discovered
        # hosts are added via /nodes responses and may be backed off / evicted
        # when they stop responding. _peer_hosts is the live union (property).
        self._retired_hosts: set[str] = set(retired_peers or ())
        self._bootstrap_hosts: list[str] = [
            host for host in peer_hosts if host not in self._retired_hosts
        ]  # preserve config order
        self._discovered_hosts: set[str] = set()
        self._evicted_hosts: set[str] = set()
        self._host_failures: dict[str, int] = {}
        self._backoff_failures = backoff_failures
        self._evict_failures = evict_failures
        self._fleet_config = fleet_config
        self._fleet_source = (
            FleetDataSource(fleet_config) if fleet_config is not None else None
        )
        self._fleet_status_line = ""
        self._movement_mode = "bandwidth"

        self._http_port = http_port
        self._ntx_port = ntx_port
        self._target_copies = target_copies
        self._refresh_seconds = refresh_seconds
        self._ntx_hosts_config = ntx_hosts
        self._store = NodeDataStore(clock or time.monotonic)

        # Rolling updates (one node at a time)
        self._current_node_index = 0
        self._last_global_poll = float("-inf")

        self._ip_map = load_tailscale_ip_map(self._peer_hosts)
        self._velocity_history = load_velocity_history()

    @property
    def _peer_hosts(self) -> list[str]:
        """Live peer list: bootstrap (config order) + discovered (sorted, minus evicted)."""
        bootstrap_set = set(self._bootstrap_hosts)
        extras = sorted(self._discovered_hosts - bootstrap_set - self._evicted_hosts)
        return self._bootstrap_hosts + extras

    def _is_bootstrap(self, host: str) -> bool:
        return host in self._bootstrap_hosts

    def _record_poll_result(self, host: str, ok: bool) -> bool:
        """Track success/failure for a host. Returns True if peer set changed (eviction)."""
        if ok:
            self._host_failures[host] = 0
            return False
        self._host_failures[host] = self._host_failures.get(host, 0) + 1
        if (
            not self._is_bootstrap(host)
            and self._host_failures[host] >= self._evict_failures
            and host not in self._evicted_hosts
        ):
            self._evicted_hosts.add(host)
            self._discovered_hosts.discard(host)
            return True
        return False

    def _should_skip_poll(self, host: str) -> bool:
        """Discovered hosts in backoff are skipped; bootstrap hosts are always polled."""
        if self._is_bootstrap(host):
            return False
        return self._host_failures.get(host, 0) >= self._backoff_failures

    def _merge_discovered_peers(self, nodes_list: list[dict]) -> bool:
        """Merge node_ids from /nodes into discovered_hosts. Returns True on change."""
        if not nodes_list:
            return False
        bootstrap_set = set(self._bootstrap_hosts)
        new_hosts: set[str] = set()
        for n in nodes_list:
            nid = n.get("node_id")
            if (
                not nid
                or nid in bootstrap_set
                or nid in self._evicted_hosts
                or nid in self._retired_hosts
            ):
                continue
            if nid not in self._discovered_hosts:
                new_hosts.add(nid)
        if not new_hosts:
            return False
        self._discovered_hosts.update(new_hosts)
        self._ip_map = load_tailscale_ip_map(self._peer_hosts)
        return True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="title-bar")
        yield RiskBanner(id="risk-banner")
        with TabbedContent(initial="tab-replication"):
            with TabPane("Replication", id="tab-replication"):
                yield ClusterOverview(self._target_copies)
                yield ReplicationChart()
                yield ReplicationVelocity()
                yield VelocityChart()
            with TabPane("Nodes", id="tab-nodes"):
                yield NodesTable()
            with TabPane("Orgs", id="tab-orgs"):
                yield OrgsTable(self._target_copies)
                yield OrgNodeTable(self._peer_hosts)
            with TabPane("Movement", id="tab-movement"):
                yield SourceUtilization()
                yield TransfersTable()
                yield TrafficHeatmap(self._peer_hosts, self._ip_map)
                yield LatencyHeatmap(self._peer_hosts, self._ip_map)
            with TabPane("Ingest", id="tab-ingest"):
                yield IngestOverview()
                yield IngestNodeTable()
                yield IngestPipeline()
            if self._fleet_source is not None:
                with TabPane("Fleet", id="tab-fleet"):
                    yield FleetTable()
            with TabPane("Debug", id="tab-debug"):
                yield HeartbeatMatrix(self._peer_hosts)
        yield Footer()

    def on_mount(self) -> None:
        self._apply_movement_mode()
        self.action_refresh()
        self.set_interval(1.0, self._poll_next_node)
        self.set_interval(1.0, self._refresh_for_clock)
        self.set_interval(120.0, self._poll_ntx_nodes)
        if self._fleet_config is not None:
            self.set_interval(self._fleet_config.refresh_seconds, self._poll_fleet)

    def _refresh_for_clock(self) -> None:
        """Render freshness transitions even when no network worker completes."""
        self.post_message(NodeUpdated(updated_node="clock"))

    def action_refresh(self) -> None:
        """Initial refresh on startup (or manual refresh with 'r' key)."""
        async def do_full_refresh():
            result = await poll_cluster(
                self._peer_hosts, self._http_port, self._target_copies
            )

            node_status = {
                nid: status for nid, status in result.node_status.items()
                if nid not in self._retired_hosts
            }
            heartbeat_age = {
                nid: age for nid, age in result.heartbeat_age.items()
                if nid not in self._retired_hosts
            }

            # Promote any /nodes-known FQDNs we don't already have to discovered.
            self._merge_discovered_peers(
                [{"node_id": nid} for nid in node_status]
            )

            traffic_results = await poll_traffic_matrix(
                self._peer_hosts, self._http_port
            )

            # Populate datastore
            for host, status in result.status_by_host.items():
                node_id = status.get("node_id", host) if status is not None else host
                self._store.update_node(
                    node_id, status, None, traffic_attempted=False,
                )

            for host, traffic in traffic_results:
                node_id = traffic.get("node_id", host) if traffic is not None else host
                self._store.update_node(
                    node_id, None, traffic, status_attempted=False,
                )

            import aiohttp
            from tfcs_tui.data import fetch_heartbeat_matrix
            async with aiohttp.ClientSession() as heartbeat_session:
                heartbeats = await fetch_heartbeat_matrix(
                    self._peer_hosts, self._http_port, heartbeat_session,
                )

            self._store.update_global(
                node_status, heartbeat_age, result.replication,
                heartbeat_matrix=heartbeats.matrix,
                velocity=result.velocity,
                site_distribution=result.site_distribution,
                cluster_sole_holders=result.sole_holders,
                by_org=result.by_org,
                nodes_succeeded=result.nodes_succeeded,
                replication_succeeded=result.replication_succeeded,
                heartbeat_outcomes=heartbeats.succeeded_by_host,
            )

            self.post_message(NodeUpdated(updated_node="refresh"))

            # Burst-fetch ntx from active nodes (now that statuses are populated)
            ntx_hosts = self._get_ntx_hosts()
            if ntx_hosts:
                async with aiohttp.ClientSession() as ntx_session:
                    results = await poll_ntx_statuses(ntx_session, ntx_hosts, self._ntx_port)
                    for ntx_host, ntx_data in results:
                        self._store.update_ntx(short(ntx_host), ntx_data)

            self.post_message(NodeUpdated(updated_node="ntx"))

        self.run_worker(do_full_refresh, exclusive=False)
        if self._fleet_source is not None:
            self._poll_fleet()

    def _poll_fleet(self) -> None:
        """Refresh the integrated fleet-health tab."""
        if self._fleet_source is None:
            return

        async def do_fleet_refresh() -> None:
            assert self._fleet_source is not None
            statuses = await self._fleet_source.refresh_prometheus()
            await self._fleet_source.refresh_vms()
            self._fleet_status_line = self._fleet_source.status_line(
                statuses, "checking",
            )
            self.query_one(FleetTable).refresh_data(
                self._fleet_source.build_snapshot(self._fleet_status_line)
            )

            tfcs_status = await self._fleet_source.refresh_pulls()
            self._fleet_status_line = self._fleet_source.status_line(
                statuses, tfcs_status,
            )
            self.query_one(FleetTable).update_pulls(
                self._fleet_source.last.get("pulls", {})
            )
            if self.query_one(TabbedContent).active == "tab-fleet":
                self._update_title_bar()

        self.run_worker(do_fleet_refresh, exclusive=False)

    def _apply_movement_mode(self) -> None:
        """Show the selected Movement heatmap and hide the alternate view."""
        self.query_one(TrafficHeatmap).set_class(
            self._movement_mode != "bandwidth", "hidden",
        )
        self.query_one(LatencyHeatmap).set_class(
            self._movement_mode != "latency", "hidden",
        )

    _INGEST_CLASSES = frozenset({"active", "anchor"})

    def _get_ntx_hosts(self) -> list[str]:
        """Return FQDNs of ntx ingest nodes.

        Uses ntx_hosts from config if present (backwards compat). Otherwise
        derives from polled /status responses by node_class -- both 'active'
        and 'anchor' nodes run the ntx pipeline (see TFC README node classes).
        """
        if self._ntx_hosts_config:
            return list(self._ntx_hosts_config)
        return [
            s["node_id"]
            for s in self._store.statuses
            if s.get("node_class") in self._INGEST_CLASSES
        ]

    def _poll_ntx_nodes(self) -> None:
        """Poll all ntx ingest nodes concurrently every 120 seconds."""
        ntx_hosts = self._get_ntx_hosts()
        if not ntx_hosts:
            return

        async def do_ntx_poll():
            import aiohttp
            async with aiohttp.ClientSession() as session:
                results = await poll_ntx_statuses(session, ntx_hosts, self._ntx_port)
                for host, ntx_data in results:
                    self._store.update_ntx(short(host), ntx_data)
                self.post_message(NodeUpdated(updated_node="ntx"))

        self.run_worker(do_ntx_poll, exclusive=False)

    def _poll_next_node(self) -> None:
        """Poll next node in rolling sequence (1 node per second).

        Skips hosts in backoff (>= backoff_failures consecutive failures).
        Bootstrap hosts are never skipped.
        """
        peers = self._peer_hosts  # snapshot for this tick (property)
        if not peers:
            return

        # Walk forward up to len(peers) slots looking for one that isn't in backoff.
        n = len(peers)
        host: str | None = None
        for _ in range(n):
            candidate = peers[self._current_node_index % n]
            self._current_node_index = (self._current_node_index + 1) % n
            if not self._should_skip_poll(candidate):
                host = candidate
                break
        if host is None:
            return  # every host in backoff — nothing to poll this tick

        now = time.monotonic()
        include_global = now - self._last_global_poll >= self._refresh_seconds
        if include_global:
            self._last_global_poll = now

        async def do_poll():
            await self._do_poll(host, include_global)

        self.run_worker(do_poll, exclusive=False)

    async def _do_poll(self, host: str, include_global: bool) -> None:
        """Background worker: poll single node for all endpoints."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            status, traffic, nodes_list, replication, velocity, site_dist, sole_holders, by_org = await fetch_node_all(
                session, host, self._http_port, include_global, self._target_copies
            )

            ok = status is not None or traffic is not None
            self._record_poll_result(host, ok)

            # Extract node_id from status or traffic
            node_id = None
            if status:
                node_id = status.get("node_id")
            elif traffic:
                node_id = traffic.get("node_id")

            if not node_id:
                node_id = host

            # Update datastore
            self._store.update_node(node_id, status, traffic)

            if include_global:
                # A global endpoint may be unavailable on the selected rolling
                # host while remaining available elsewhere. Fall back across
                # the other peers concurrently, preserving empty successes.
                others = [peer for peer in self._peer_hosts if peer != host]
                if nodes_list is None and others:
                    node_results = await asyncio.gather(*(
                        fetch_nodes(session, peer, self._http_port)
                        for peer in others
                    ))
                    nodes_list = next(
                        (value for value in node_results if value is not None), None,
                    )
                if replication is None and others:
                    replication_results = await asyncio.gather(*(
                        fetch_replication(
                            session, peer, self._http_port, self._target_copies,
                        )
                        for peer in others
                    ))
                    repl_result = next(
                        (value for value in replication_results if value is not None),
                        None,
                    )
                    if repl_result is not None:
                        replication, velocity, site_dist, sole_holders, by_org = repl_result

                # Promote /nodes-known FQDNs to discovered before anything reads _peer_hosts
                self._merge_discovered_peers(nodes_list or [])

                # Parse nodes_list into node_status and heartbeat_age dicts
                node_status = {}
                heartbeat_age = {}
                for node_info in nodes_list or []:
                    nid = node_info.get("node_id")
                    if nid and nid not in self._retired_hosts:
                        node_status[nid] = node_info.get("status", "unknown")
                        heartbeat_age[nid] = node_info.get("heartbeat_age_seconds") or 0.0

                # Fetch heartbeat matrix from all peers
                from tfcs_tui.data import fetch_heartbeat_matrix
                heartbeats = await fetch_heartbeat_matrix(
                    self._peer_hosts, self._http_port, session,
                )

                self._store.update_global(node_status, heartbeat_age, replication or {}, heartbeats.matrix,
                                          velocity=velocity,
                                          site_distribution=site_dist,
                                          cluster_sole_holders=sole_holders,
                                          by_org=by_org,
                                          nodes_succeeded=nodes_list is not None,
                                          replication_succeeded=replication is not None,
                                          heartbeat_outcomes=heartbeats.succeeded_by_host)

            self.post_message(NodeUpdated(updated_node=node_id))

    def on_node_updated(self, message: NodeUpdated) -> None:
        """Update ALL widgets from the datastore."""
        import time
        store = self._store

        replication_stale = store.source_state("replication") in {"stale", "expired"}
        for widget_type in (ReplicationChart, ClusterOverview, OrgsTable, OrgNodeTable):
            self.query_one(widget_type).set_class(replication_stale, "source-stale")

        self.query_one(RiskBanner).refresh_data(classify_risk(store, self._target_copies))

        # --- Replication tab (Tab 1) ---
        self.query_one(ReplicationChart).refresh_data(
            store.replication, self._target_copies, store.site_distribution,
        )

        # Server-supplied velocity (from /replication?window=N)
        vel = store.velocity
        self.query_one(ReplicationVelocity).refresh_data(vel)

        # Build vel_data for ClusterOverview: server velocity + TUI-computed ETA
        vel_data: dict | None = None
        if vel is not None:
            cpm = vel.get("copies_per_min", 0)
            if cpm > 0:
                repl = store.replication
                target = self._target_copies
                below_target_copies = sum(k * v for k, v in repl.items() if k < target)
                below_target_count = sum(v for k, v in repl.items() if k < target)
                eta_min = None
                if below_target_count > 0:
                    copies_needed = target * below_target_count - below_target_copies
                    eta_min = round(copies_needed / cpm, 1)
                vel_data = {**vel, "eta_satisfied_min": eta_min}

        # Compute per-node sole_holder_count map for ClusterOverview alarm
        sole_holder_nodes = {
            short(s["node_id"]): s.get("sole_holder_count", 0)
            for s in store.statuses
            if s.get("sole_holder_count", 0) > 0
        }

        self.query_one(ClusterOverview).refresh_data(
            store.replication, store.node_status, vel_data,
            store.site_distribution, sole_holder_nodes,
        )

        if vel_data is not None:
            from datetime import datetime
            save_snapshot(store.replication, vel_data, time.time())
            label = datetime.now().strftime("%H:%M")
            cpm = vel_data["copies_per_min"]
            if not self._velocity_history or self._velocity_history[-1][0] != label:
                self._velocity_history.append((label, cpm))

        self.query_one(VelocityChart).refresh_data(self._velocity_history)

        # --- Nodes tab (Tab 2) ---
        self.query_one(NodesTable).refresh_data(
            store.statuses, store.node_status, store.heartbeat_age, self._peer_hosts,
        )

        # --- Orgs tab (Tab 3) ---
        peers = self._peer_hosts  # snapshot (property)
        self.query_one(OrgsTable).refresh_data(store.by_org)
        self.query_one(OrgNodeTable).refresh_data(store.by_org, peers)

        # --- Movement tab (Tab 4) ---
        self.query_one(SourceUtilization).refresh_data(store.statuses)
        self.query_one(TransfersTable).refresh_data(store.statuses)

        # --- Movement + debug heatmaps ---
        # Push current peer list + ip_map so heatmap axes include discovered nodes.
        traffic_hm = self.query_one(TrafficHeatmap)
        latency_hm = self.query_one(LatencyHeatmap)
        heartbeat_hm = self.query_one(HeartbeatMatrix)
        traffic_stale = store.observational_state("traffic") != "fresh"
        traffic_hm.set_class(traffic_stale, "source-stale")
        latency_hm.set_class(traffic_stale, "source-stale")
        heartbeat_hm.set_class(
            store.observational_state("heartbeats") != "fresh", "source-stale",
        )
        traffic_hm.set_node_names(peers)
        traffic_hm.set_ip_map(self._ip_map)
        latency_hm.set_node_names(peers)
        latency_hm.set_ip_map(self._ip_map)
        self._apply_movement_mode()
        heartbeat_hm.set_node_names(peers)
        traffic_hm.refresh_data(store.traffic_reports, message.updated_node)
        latency_hm.refresh_data(store.traffic_reports, message.updated_node)
        heartbeat_hm.refresh_data(store.heartbeat_matrix, message.updated_node)

        # --- Ingest tab (Tab 7) ---
        ntx = store.ntx_statuses
        ingest_widgets = (
            self.query_one(IngestOverview),
            self.query_one(IngestNodeTable),
            self.query_one(IngestPipeline),
        )
        for widget in ingest_widgets:
            widget.set_class(
                store.observational_state("ntx") != "fresh", "source-stale",
            )
        ingest_widgets[0].refresh_data(ntx)
        ingest_widgets[1].refresh_data(ntx, store.statuses)
        ingest_widgets[2].refresh_data(ntx)

        # Update title bar
        self._update_title_bar()

    def _update_title_bar(self) -> None:
        """Update title bar based on active tab."""
        active_tab = self.query_one(TabbedContent).active
        title_bar = self.query_one("#title-bar", Static)

        if active_tab == "tab-replication":
            title_bar.update(" tfcs cluster dashboard")
        elif active_tab == "tab-nodes":
            n_nodes = len(set(self._peer_hosts) | set(self._store.node_status))
            n_transfers = sum(len(s.get("claims", [])) for s in self._store.statuses)
            title_bar.update(f" tfcs nodes    {n_nodes} nodes, {n_transfers} active transfers")
        elif active_tab == "tab-orgs":
            n_orgs = len(self._store.by_org)
            title_bar.update(f" tfcs orgs    {n_orgs} organizations")
        elif active_tab == "tab-movement":
            n_reporting = len(self._store.traffic_reports)
            freshness = self._store.observational_state("traffic")
            mode = "bandwidth" if self._movement_mode == "bandwidth" else "latency"
            n_transfers = sum(len(s.get("claims", [])) for s in self._store.statuses)
            title_bar.update(
                f" tfcs movement    {n_transfers} active transfers    {mode}    {n_reporting}/{len(self._peer_hosts)} reporting ({freshness})"
            )
        elif active_tab == "tab-debug":
            n_reporting = len(self._store.heartbeat_matrix)
            freshness = self._store.observational_state("heartbeats")
            title_bar.update(
                f" tfcs debug    heartbeat matrix    {n_reporting}/{len(self._peer_hosts)} nodes reporting ({freshness})"
            )
        elif active_tab == "tab-ingest":
            n_ntx = len(self._store.ntx_statuses)
            freshness = self._store.observational_state("ntx")
            title_bar.update(f" ntx ingest pipeline    {n_ntx} nodes reporting ({freshness})")
        elif active_tab == "tab-fleet":
            n_hosts = len(self._fleet_config.hosts) if self._fleet_config else 0
            title_bar.update(
                f" tfcs fleet health    {n_hosts} hosts    {self._fleet_status_line}"
            )

    def action_tab_replication(self) -> None:
        """Switch to replication tab."""
        self.query_one(TabbedContent).active = "tab-replication"
        self._update_title_bar()

    def action_tab_nodes(self) -> None:
        """Switch to nodes tab."""
        self.query_one(TabbedContent).active = "tab-nodes"
        self._update_title_bar()

    def action_tab_orgs(self) -> None:
        """Switch to orgs tab."""
        self.query_one(TabbedContent).active = "tab-orgs"
        self._update_title_bar()

    def action_tab_movement(self) -> None:
        """Switch to movement tab."""
        self.query_one(TabbedContent).active = "tab-movement"
        self._update_title_bar()

    def action_toggle_movement_mode(self) -> None:
        """Toggle Movement between bandwidth and latency heatmaps."""
        self._movement_mode = (
            "latency" if self._movement_mode == "bandwidth" else "bandwidth"
        )
        self._apply_movement_mode()
        self._update_title_bar()

    def action_tab_debug(self) -> None:
        """Switch to debug tab."""
        self.query_one(TabbedContent).active = "tab-debug"
        self._update_title_bar()

    def action_tab_ingest(self) -> None:
        """Switch to ingest tab."""
        self.query_one(TabbedContent).active = "tab-ingest"
        self._update_title_bar()

    def action_tab_fleet(self) -> None:
        """Switch to fleet tab."""
        if self._fleet_source is None:
            return
        self.query_one(TabbedContent).active = "tab-fleet"
        self._update_title_bar()

    def action_scroll_down(self) -> None:
        # Scrolls TransfersTable regardless of active tab (harmless when off-screen)
        table = self.query_one(TransfersTable)
        table.scroll_down()

    def action_scroll_up(self) -> None:
        # Scrolls TransfersTable regardless of active tab (harmless when off-screen)
        table = self.query_one(TransfersTable)
        table.scroll_up()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="tfcs cluster dashboard TUI")
    p.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG,
                   help=f"Path to TOML config (default: {DEFAULT_CONFIG})")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.config.exists():
        print(f"Config not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    cfg = load_config(args.config)
    app = TfcsDashboard(
        peer_hosts=cfg["peer_hosts"],
        http_port=cfg["http_port"],
        ntx_port=cfg["ntx_port"],
        target_copies=cfg["target_copies"],
        refresh_seconds=cfg["refresh_seconds"],
        ntx_hosts=cfg["ntx_hosts"],
        retired_peers=cfg["retired_peers"],
        backoff_failures=cfg["backoff_failures"],
        evict_failures=cfg["evict_failures"],
        fleet_config=load_fleet_config(),
    )

    app.run()


if __name__ == "__main__":
    main()
