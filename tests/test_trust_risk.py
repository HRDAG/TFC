# Author: PB and cx-tfc
# Date: 2026-06-30
# License: (c) HRDAG, 2026, GPL-2 or newer
#
# ---
# tests/test_trust_risk.py

from __future__ import annotations

import asyncio
import math
import unittest
from unittest.mock import patch

from tfcs_tui.data import NodeDataStore, SourceFreshness, poll_ntx_statuses
from tfcs_tui.risk import classify_risk, valid_velocity


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FreshnessTests(unittest.TestCase):
    def test_boundaries_and_attempt_success_are_distinct(self) -> None:
        source = SourceFreshness(30, 120)
        source.attempted(0, True)
        source.attempted(20, False)
        self.assertEqual(source.last_attempt, 20)
        self.assertEqual(source.last_success, 0)
        self.assertEqual(source.state(29.9), "fresh")
        self.assertEqual(source.state(30), "stale")
        self.assertEqual(source.state(120), "expired")

    def test_successful_empty_replication_is_not_missing(self) -> None:
        store = NodeDataStore(Clock())
        store.update_global({}, {}, {}, site_distribution={})
        self.assertEqual(store.source_state("replication"), "fresh")

    def test_expired_status_suppresses_claims_but_retains_safety_evidence(self) -> None:
        clock = Clock()
        store = NodeDataStore(clock)
        store.update_node("lost.example", {
            "node_id": "lost.example", "claims": [{"commit": "abc"}],
            "sole_holder_count": 2,
        }, None)
        clock.now = 120
        status = store.statuses[0]
        self.assertEqual(status["claims"], [])
        self.assertEqual(status["sole_holder_count"], 2)
        self.assertEqual(status["_freshness"], "expired")

    def test_partial_heartbeat_outcomes_remain_distinct(self) -> None:
        clock = Clock()
        store = NodeDataStore(clock)
        store.update_global(
            {}, {}, {}, heartbeat_matrix={"one": {}},
            heartbeat_outcomes={"one": True, "two": False},
        )
        self.assertEqual(store.observational_state("heartbeats"), "missing")

    def test_failed_heartbeat_poll_preserves_last_success_until_expiry(self) -> None:
        clock = Clock()
        store = NodeDataStore(clock)
        store.update_global(
            {}, {}, {}, heartbeat_matrix={"one": {"two": 4}},
            heartbeat_outcomes={"one": True},
        )
        clock.now = 20
        store.update_global(
            {}, {}, {}, heartbeat_matrix={},
            heartbeat_outcomes={"one": False},
        )
        self.assertEqual(store.heartbeat_matrix["one"]["two"], 4)
        clock.now = 120
        self.assertNotIn("one", store.heartbeat_matrix)


class IngestPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_hosts_are_in_flight_concurrently_with_partial_failure(self) -> None:
        started: set[str] = set()
        all_started = asyncio.Event()

        async def fake_fetch(session, host, port):
            started.add(host)
            if len(started) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 0.2)
            return None if host == "b" else {"node_id": host}

        with patch("tfcs_tui.data.fetch_ntx_status", fake_fetch):
            results = await poll_ntx_statuses(object(), ["a", "b", "c"], 9401)
        self.assertEqual(started, {"a", "b", "c"})
        self.assertEqual([host for host, _ in results], ["a", "b", "c"])
        self.assertIsNone(results[1][1])


class VelocityTests(unittest.TestCase):
    def test_validation(self) -> None:
        self.assertIsNone(valid_velocity(None))
        self.assertIsNone(valid_velocity({}))
        self.assertIsNone(valid_velocity({"copies_per_min": -1, "bytes_per_min": 0}))
        self.assertIsNone(valid_velocity({"copies_per_min": math.inf, "bytes_per_min": 0}))
        value = valid_velocity({"copies_per_min": 0.1, "bytes_per_min": 600})
        self.assertIsNotNone(value)
        self.assertEqual(value.copies_per_min, 0.1)
        self.assertEqual(value.bytes_per_sec, 10)


class RiskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.store = NodeDataStore(self.clock)

    def update_global(
        self, replication=None, sites=None, nodes=None, velocity=None,
    ) -> None:
        self.store.update_global(
            nodes if nodes is not None else {}, {},
            replication if replication is not None else {4: 10},
            velocity=velocity,
            site_distribution=sites if sites is not None else {2: 10},
            heartbeat_matrix={"observer": {}},
            heartbeat_outcomes={"observer": True},
        )

    def test_no_replication_data_is_unknown(self) -> None:
        self.assertEqual(classify_risk(self.store, 4).severity, "UNKNOWN")

    def test_missing_site_distribution_is_unknown(self) -> None:
        self.store.update_global({}, {}, {4: 10}, site_distribution=None)
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "UNKNOWN")
        self.assertIn("site-distribution", risk.message)

    def test_zero_site_precedes_missing_reachability(self) -> None:
        self.update_global(replication={1: 5}, sites={0: 1, 1: 4})
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "CRITICAL")
        self.assertIn("zero sites", risk.message)

    def test_expired_safe_replication_is_unknown(self) -> None:
        self.update_global()
        self.clock.now = 120
        self.assertEqual(classify_risk(self.store, 4).severity, "UNKNOWN")

    def test_expired_zero_site_evidence_remains_critical_and_aged(self) -> None:
        self.update_global(sites={0: 1})
        self.clock.now = 120
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "CRITICAL")
        self.assertIn("last known", risk.message)

    def test_unreachable_sole_holder_is_critical(self) -> None:
        self.store.update_node("lost.example", {
            "node_id": "lost.example", "sole_holder_count": 3,
        }, None)
        self.update_global(nodes={"lost.example": "unreachable"})
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "CRITICAL")
        self.assertIn("lost", risk.message)

    def test_backlog_with_missing_velocity_does_not_report_zero(self) -> None:
        self.update_global(replication={2: 3}, sites={2: 3})
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "WARN")
        self.assertIn("activity unavailable", risk.message)

    def test_backlog_with_malformed_velocity_is_unavailable(self) -> None:
        self.update_global(
            replication={2: 3}, sites={2: 3},
            velocity={"copies_per_min": "bad", "bytes_per_min": 60},
        )
        self.assertEqual(self.store.source_state("velocity"), "missing")
        self.assertIn("activity unavailable", classify_risk(self.store, 4).message)

    def test_velocity_threshold_language(self) -> None:
        self.update_global(
            replication={2: 3}, sites={2: 3},
            velocity={"copies_per_min": 0.1, "bytes_per_min": 600},
        )
        risk = classify_risk(self.store, 4)
        self.assertIn("replication active", risk.message)
        self.assertIn("10 Bytes/s", risk.message)

    def test_stale_safe_evidence_warns(self) -> None:
        self.update_global()
        self.clock.now = 30
        risk = classify_risk(self.store, 4)
        self.assertEqual(risk.severity, "WARN")
        self.assertIn("stale", risk.message)


if __name__ == "__main__":
    unittest.main()
