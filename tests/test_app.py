# Author: PB and cx-tfc
# Date: 2026-06-30
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# tests/test_app.py

from __future__ import annotations

import unittest

from textual.widgets import Static, TabbedContent

from tfcs_tui.app import NodeUpdated, TfcsDashboard
from tfcs_tui.widgets import NodesTable, RiskBanner


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class PilotDashboard(TfcsDashboard):
    def on_mount(self) -> None:
        """Disable network timers for deterministic pilot tests."""


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


if __name__ == "__main__":
    unittest.main()
