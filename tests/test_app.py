# Author: PB and cx-tfc
# Date: 2026-06-30
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# tests/test_app.py

from __future__ import annotations

from pathlib import Path
import unittest

from textual.app import App, ComposeResult
from textual.widgets import Static, TabbedContent

from tfcs_fleet_tui.config import FleetConfig, Host
from tfcs_fleet_tui.model import ABSENT, Cell, FleetNode
from tfcs_fleet_tui.source import FleetDataSource
from tfcs_fleet_tui.widgets import FleetTable, _compact_temp_cell
from tfcs_tui.app import NodeUpdated, TfcsDashboard
from tfcs_tui.widgets import (
    LatencyHeatmap,
    NodesTable,
    RiskBanner,
    SourceUtilization,
    TrafficHeatmap,
    TransfersTable,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class PilotDashboard(TfcsDashboard):
    def on_mount(self) -> None:
        """Disable network timers for deterministic pilot tests."""


class FleetTablePilot(App):
    def compose(self) -> ComposeResult:
        yield FleetTable()


class DashboardPilotTests(unittest.IsolatedAsyncioTestCase):
    def test_retired_configured_node_is_not_live(self) -> None:
        app = PilotDashboard(
            ["one.example", "retired.example"],
            retired_peers=["retired.example"],
        )
        self.assertEqual(app._peer_hosts, ["one.example"])

    async def test_banner_age_transition_and_configured_node_count(self) -> None:
        clock = Clock()
        app = PilotDashboard(["one.example", "two.example"], clock=clock)
        async with app.run_test() as pilot:
            app._store.update_node("one.example", {
                "node_id": "one.example", "claims": [], "free_gb": 100,
            }, {"node_id": "one.example", "traffic": {}})
            app._store.update_global(
                {"one.example": "alive"}, {"one.example": 1}, {4: 1},
                site_distribution={2: 1},
            )
            app.post_message(NodeUpdated("one.example"))
            await pilot.pause()

            banner = app.query_one(RiskBanner)
            self.assertIn("OK:", str(banner.render()))
            self.assertLessEqual(banner.size.height, 2)
            table = app.query_one(NodesTable)
            self.assertEqual(table.row_count, 2)
            self.assertIn("Seen", str(table.columns["seen"].label))

            app.query_one(TabbedContent).active = "tab-nodes"
            app._update_title_bar()
            title = app.query_one("#title-bar", Static)
            self.assertIn("2 nodes", str(title.render()))

            clock.now = 30
            app.post_message(NodeUpdated("clock"))
            await pilot.pause()
            self.assertIn("WARN:", str(banner.render()))
            self.assertIn("stale", str(banner.render()))

    async def test_movement_mode_toggle_switches_heatmaps(self) -> None:
        app = PilotDashboard(["one.example"])
        async with app.run_test():
            app.query_one(TabbedContent).active = "tab-movement"
            traffic = app.query_one(TrafficHeatmap)
            latency = app.query_one(LatencyHeatmap)

            self.assertFalse(traffic.has_class("hidden"))
            self.assertTrue(latency.has_class("hidden"))
            self.assertIn("bandwidth", str(app.query_one("#movement-mode", Static).render()))

            app.action_toggle_movement_mode()
            self.assertTrue(traffic.has_class("hidden"))
            self.assertFalse(latency.has_class("hidden"))
            self.assertIn("latency", str(app.query_one("#movement-mode", Static).render()))

            app._update_title_bar()
            title = app.query_one("#title-bar", Static)
            self.assertIn("latency", str(title.render()))

    async def test_movement_tab_orders_overview_before_detail(self) -> None:
        app = PilotDashboard(["one.example"])
        async with app.run_test():
            movement = app.query_one("#tab-movement")
            child_types = [type(child) for child in movement.children]

            self.assertLess(child_types.index(TrafficHeatmap), child_types.index(SourceUtilization))
            self.assertLess(child_types.index(TrafficHeatmap), child_types.index(TransfersTable))
            self.assertLess(child_types.index(LatencyHeatmap), child_types.index(SourceUtilization))
            self.assertLess(child_types.index(LatencyHeatmap), child_types.index(TransfersTable))

    def test_compact_temp_cell_uses_lowercase_tags(self) -> None:
        cell = _compact_temp_cell(
            FleetNode(
                host="one",
                cpu_temp=Cell.of(45, "45C", status="safe"),
                hdd_temp=ABSENT,
                nvme_temp=Cell.of(55, "55C", status="warn"),
                nic=Cell.missing(),
            )
        )

        self.assertEqual(cell.plain, "c45 h-- n55 i?")

    def test_oob_cell_keeps_vpn_gated_methods_plain(self) -> None:
        cell = FleetDataSource._oob_cell(
            Host(name="one", instance="one:9100", oob_kind="ipmi"), {}
        )

        self.assertEqual(cell.value, "ipmi")
        self.assertEqual(cell.status, "ok")

    def test_oob_cell_colors_pikvm_reachability(self) -> None:
        host = Host(
            name="one",
            instance="one:9100",
            oob_kind="PiKVM",
            oob_instances=("onekvm:9100",),
        )

        self.assertEqual(
            FleetDataSource._oob_cell(host, {"onekvm:9100": 1}).status, "safe"
        )
        self.assertEqual(
            FleetDataSource._oob_cell(host, {"onekvm:9100": 0}).status, "crit"
        )

    def test_configured_host_note_reaches_snapshot(self) -> None:
        source = FleetDataSource(
            FleetConfig(
                prometheus_url="http://example.invalid:9090",
                refresh_seconds=10,
                stale_after_seconds=120,
                server_documentation_path=Path("."),
                hosts={
                    "one": Host(
                        name="one",
                        instance="one:9100",
                        note="NICs hot ok; crit 100C",
                    )
                },
                tfcs_port=8099,
                enabled_columns=(),
                sort="fixed",
                temperature_unit="celsius",
            )
        )

        snapshot = source.build_snapshot("source")

        self.assertIn("NICs hot ok; crit 100C", snapshot.nodes[0].note)

    def test_unmatched_instance_label_flagged_distinctly(self) -> None:
        source = FleetDataSource(
            FleetConfig(
                prometheus_url="http://example.invalid:9090",
                refresh_seconds=10,
                stale_after_seconds=120,
                server_documentation_path=Path("."),
                hosts={"one": Host(name="one", instance="one-typo:9100")},
                tfcs_port=8099,
                enabled_columns=(),
                sort="fixed",
                temperature_unit="celsius",
            )
        )
        source.last["known_instances"] = {"other.example:9100"}

        snapshot = source.build_snapshot("source")

        self.assertIn("bad instance label", snapshot.nodes[0].note)

    def test_matched_instance_label_gets_no_data_note(self) -> None:
        source = FleetDataSource(
            FleetConfig(
                prometheus_url="http://example.invalid:9090",
                refresh_seconds=10,
                stale_after_seconds=120,
                server_documentation_path=Path("."),
                hosts={"one": Host(name="one", instance="one:9100")},
                tfcs_port=8099,
                enabled_columns=(),
                sort="fixed",
                temperature_unit="celsius",
            )
        )
        source.last["known_instances"] = {"one:9100"}

        snapshot = source.build_snapshot("source")

        self.assertIn("no prom data", snapshot.nodes[0].note)
        self.assertNotIn("bad instance label", snapshot.nodes[0].note)

    def test_no_prom_data_note_fires_with_absent_sensors(self) -> None:
        """A host with some sensors absent (not just missing) still gets flagged."""
        source = FleetDataSource(
            FleetConfig(
                prometheus_url="http://example.invalid:9090",
                refresh_seconds=10,
                stale_after_seconds=120,
                server_documentation_path=Path("."),
                hosts={
                    "one": Host(
                        name="one",
                        instance="one:9100",
                        sensors={"hdd": False, "nvme": False, "nic": False},
                    )
                },
                tfcs_port=8099,
                enabled_columns=(),
                sort="fixed",
                temperature_unit="celsius",
            )
        )
        source.last["hdd_temps"] = {"one": ABSENT}
        source.last["nvme_temps"] = {"one": ABSENT}
        source.last["nic_temps"] = {"one": ABSENT}

        snapshot = source.build_snapshot("source")

        self.assertIn("no prom data", snapshot.nodes[0].note)

    async def test_fleet_table_initial_row_column_order(self) -> None:
        app = FleetTablePilot()
        node = FleetNode(
            host="one",
            last_update=Cell.from_str("7s"),
            up=Cell.from_str("ok"),
            load=Cell.from_str("0.1/4"),
            cpu_temp=Cell.of(45, "45C"),
            root=Cell.from_str("10%"),
            data=Cell.from_str("20%"),
            pulls=Cell.from_str("0"),
            oob=Cell.from_str("ipmi"),
            note="note",
        )
        async with app.run_test():
            table = app.query_one(FleetTable)
            table.refresh_data(type("Snapshot", (), {"nodes": (node,)})())

            self.assertEqual(str(table.get_cell("one", "last")), "7s")
            self.assertEqual(str(table.get_cell("one", "up")), "ok")
            self.assertEqual(table.get_cell("one", "temp").plain, "c45 h-- n-- i--")
            self.assertEqual(str(table.get_cell("one", "oob")), "ipmi")

    async def test_fleet_table_add_and_update_agree_on_column_values(self) -> None:
        """Guards against add-row and update-row column lists drifting apart."""
        app = FleetTablePilot()
        node = FleetNode(
            host="one",
            last_update=Cell.from_str("7s"),
            up=Cell.from_str("ok"),
            load=Cell.from_str("0.1/4"),
            cpu_temp=Cell.of(45, "45C"),
            root=Cell.from_str("10%"),
            data=Cell.from_str("20%"),
            pulls=Cell.from_str("0"),
            oob=Cell.from_str("ipmi"),
            note="note",
        )
        async with app.run_test():
            table = app.query_one(FleetTable)
            snapshot = type("Snapshot", (), {"nodes": (node,)})()
            table.refresh_data(snapshot)
            added = {key: str(table.get_cell("one", key)) for key in table.columns}

            table.refresh_data(snapshot)
            updated = {key: str(table.get_cell("one", key)) for key in table.columns}

            self.assertEqual(added, updated)

    async def test_fleet_tab_mounts_when_configured(self) -> None:
        fleet_config = FleetConfig(
            prometheus_url="http://example.invalid:9090",
            refresh_seconds=10,
            stale_after_seconds=120,
            server_documentation_path=Path("."),
            hosts={},
            tfcs_port=8099,
            enabled_columns=(),
            sort="fixed",
            temperature_unit="celsius",
        )
        app = PilotDashboard(["one.example"], fleet_config=fleet_config)
        async with app.run_test():
            app.query_one(TabbedContent).active = "tab-fleet"
            self.assertIsNotNone(app.query_one(FleetTable))
            app.action_tab_fleet()
            title = app.query_one("#title-bar", Static)
            self.assertIn("tfcs fleet health", str(title.render()))


if __name__ == "__main__":
    unittest.main()
