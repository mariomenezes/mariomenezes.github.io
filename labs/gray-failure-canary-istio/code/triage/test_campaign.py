import unittest

from campaign import (SCENARIOS, aggregate_window, build_plan, classify,
                      events_after, summarize)
from detector import Window


def ev(cluster, event, feature="dashboard", ts="2026-10-21T20:00:00Z"):
    return {"ts": ts, "cluster": cluster, "event": event, "feature": feature}


class PlanTest(unittest.TestCase):
    def test_default_plan_reaches_20_events(self):
        self.assertGreaterEqual(len(build_plan(3)), 20)

    def test_plan_is_round_robin_over_repetitions(self):
        plan = build_plan(2)
        first_round = [s.name for s, r in plan if r == 1]
        self.assertEqual(first_round, [s.name for s in SCENARIOS])
        self.assertEqual([r for _, r in plan[:len(SCENARIOS)]], [1] * len(SCENARIOS))

    def test_only_filter(self):
        plan = build_plan(3, ["dash_err3_a_control"])
        self.assertEqual({s.name for s, _ in plan}, {"dash_err3_a_control"})
        self.assertEqual(len(plan), 3)

    def test_there_is_a_negative_control_and_a_blocked_case(self):
        expects = {s.expect for s in SCENARIOS}
        self.assertTrue({"none", "blocked", "would_apply"} <= expects)


class ClassifyTest(unittest.TestCase):
    def test_detected(self):
        out, ts = classify("would_apply", ("a",), "dashboard", [ev("a", "would_apply")])
        self.assertEqual(out, "detected")
        self.assertEqual(list(ts), ["a"])

    def test_missed_when_no_event(self):
        self.assertEqual(classify("would_apply", ("a",), "dashboard", [])[0], "missed")

    def test_other_feature_does_not_count(self):
        out, _ = classify("would_apply", ("a",), "dashboard",
                          [ev("a", "would_apply", feature="heavy-reports")])
        self.assertEqual(out, "missed")

    def test_other_cluster_does_not_count(self):
        out, _ = classify("would_apply", ("a",), "dashboard", [ev("b", "would_apply")])
        self.assertEqual(out, "missed")

    def test_blocked_requires_both_clusters(self):
        both = [ev("a", "blocked"), ev("b", "blocked")]
        self.assertEqual(classify("blocked", ("a", "b"), "dashboard", both)[0], "blocked_ok")
        self.assertEqual(classify("blocked", ("a", "b"), "dashboard", [ev("a", "blocked")])[0], "missed")

    def test_would_apply_instead_of_blocked_is_flagged(self):
        evs = [ev("a", "would_apply"), ev("b", "blocked")]
        self.assertEqual(classify("blocked", ("a", "b"), "dashboard", evs)[0], "would_apply_instead")

    def test_control_with_action_is_false_positive(self):
        self.assertEqual(classify("none", ("a",), "dashboard", [ev("a", "would_apply")])[0], "false_positive")
        self.assertEqual(classify("none", ("a",), "dashboard", [])[0], "ok_none")

    def test_recovered_and_errors_are_not_detections(self):
        evs = [ev("a", "recovered"), ev("a", "source_error")]
        self.assertEqual(classify("none", ("a",), "dashboard", evs)[0], "ok_none")


class EventsAfterTest(unittest.TestCase):
    def test_filters_by_timestamp(self):
        evs = [ev("a", "x", ts="2026-10-21T19:59:59Z"), ev("a", "y", ts="2026-10-21T20:00:00Z")]
        self.assertEqual([e["event"] for e in events_after(evs, "2026-10-21T20:00:00Z")], ["y"])


class AggregateTest(unittest.TestCase):
    def test_dilution_of_error_across_features(self):
        snap = {
            ("v2", "dashboard"): Window(n=70, err_pct=8.0, p95_ms=1.0, baseline_p95_ms=0.0),
            ("v2", "heavy-reports"): Window(n=30, err_pct=0.0, p95_ms=3000.0, baseline_p95_ms=0.0),
            ("v1", "dashboard"): Window(n=70, err_pct=0.0, p95_ms=1.0, baseline_p95_ms=0.0),
        }
        w = aggregate_window(snap, "v2")
        self.assertEqual(w.n, 100)
        self.assertAlmostEqual(w.err_pct, 5.6)  # 8% x 70% diluído em v2 inteira
        self.assertEqual(w.p95_ms, 0.0)  # p95 agregado não é reconstruível

    def test_no_traffic_returns_none(self):
        self.assertIsNone(aggregate_window({}, "v2"))


class SummarizeTest(unittest.TestCase):
    def rec(self, name, expect, outcome, detect, recover, agg):
        return {"scenario": name, "expect": expect, "outcome": outcome,
                "detect_s": detect, "recover_s": recover, "agg_detected": agg}

    def test_totals_and_comparison(self):
        recs = [
            self.rec("x", "would_apply", "detected", {"a": 160.0}, {"a": 200.0}, True),
            self.rec("x", "would_apply", "detected", {"a": 200.0}, {"a": 220.0}, False),
            self.rec("x", "would_apply", "missed", {}, {}, False),
            self.rec("ctl", "none", "ok_none", {}, {}, False),
            self.rec("ctl", "none", "false_positive", {"a": 190.0}, {"a": 200.0}, False),
        ]
        out = summarize(recs)
        self.assertIn("Eventos totais: 5 (com degradação: 3; controles negativos: 2)", out)
        self.assertIn("Detecção por (cluster, feature): 2/3", out)
        self.assertIn("Detecção agregada por versão (só regra de erro): 1/3", out)
        self.assertIn("Falsos positivos nos controles: 1/2", out)
        self.assertIn("| x | would_apply | 3 |", out)


if __name__ == "__main__":
    unittest.main()
