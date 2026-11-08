import os
import tempfile
import unittest

import agent
from agent import ShadowAgent
from detector import RULE_A, RULE_B, RULE_C, RULE_D, Window

FEATURES = ["dashboard", "heavy-reports"]


def w(n=100, p95=50.0, err=0.0, mean=0.0, slow=-1):
    return Window(n=n, err_pct=err, p95_ms=p95, baseline_p95_ms=0.0, mean_ms=mean, slow_n=slow)


def snap(heavy_v1, heavy_v2, **kw):
    return {("v1", "dashboard"): w(p95=2.0), ("v2", "dashboard"): w(p95=2.0),
            ("v1", "heavy-reports"): heavy_v1, ("v2", "heavy-reports"): heavy_v2}


class Src:
    def __init__(self):
        self.s = {}

    def __call__(self, cluster):
        return self.s[cluster]


class AgentRuleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ev = os.path.join(self.tmp.name, "e.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, **kw):
        self.src = Src()
        self.src.s = {"a": snap(w(p95=3000.0), w(p95=4500.0))}
        return ShadowAgent(["a"], FEATURES, self.src, self.ev, **kw)

    def ticks(self, a, n):
        out = []
        for _ in range(n):
            out += a.tick()
        return out

    def test_default_rule_is_still_b_and_watch_is_c(self):
        a = self.make()
        self.assertEqual(a.detectors[("a", "heavy-reports")].rule, RULE_B)
        self.assertEqual(a.watch[("a", "heavy-reports")].rule, RULE_C)
        self.assertEqual(agent.DEFAULT_RULE, RULE_B)

    def test_rule_a_does_not_detect_the_moderate_regression_but_b_does(self):
        names_a = [e["event"] for e in self.ticks(self.make(rule=RULE_A), 4)]
        names_b = [e["event"] for e in self.ticks(self.make(rule=RULE_B), 4)]
        self.assertNotIn("would_apply", names_a)
        self.assertIn("would_apply", names_b)

    def test_rule_d_receives_baseline_counts_from_v1(self):
        a = self.make(rule=RULE_D)
        base = Window(n=100, err_pct=0.0, p95_ms=3000.0, baseline_p95_ms=0.0, slow_n=2)
        cand = Window(n=100, err_pct=0.0, p95_ms=3000.0, baseline_p95_ms=0.0, slow_n=40)
        self.src.s = {"a": snap(base, cand)}
        names = [e["event"] for e in self.ticks(a, 3)]
        self.assertEqual(names.count("would_apply"), 1)

    def test_ratio_reaches_the_decision_and_watch_detectors(self):
        a = self.make(ratio=1.6)  # 4500/3000 = 1,5x: abaixo de 1,6
        self.assertEqual(a.detectors[("a", "heavy-reports")].ratio, 1.6)
        self.assertEqual(a.watch[("a", "heavy-reports")].ratio, 1.6)
        self.assertNotIn("would_apply", [e["event"] for e in self.ticks(a, 4)])
        self.assertIsNone(self.make().detectors[("a", "heavy-reports")].ratio)

    def test_rule_d_without_buckets_stays_silent(self):
        a = self.make(rule=RULE_D)  # slow_n = -1 nas duas
        self.assertNotIn("would_apply", [e["event"] for e in self.ticks(a, 6)])


class ResetStreaksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ev = os.path.join(self.tmp.name, "e.jsonl")
        self.src = Src()
        self.src.s = {"a": snap(w(p95=3000.0), w(p95=4500.0)), "b": snap(w(p95=3000.0), w(p95=3000.0))}
        self.a = ShadowAgent(["a", "b"], FEATURES, self.src, self.ev)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gap_breaks_the_streak(self):
        self.a.tick()
        self.a.tick()
        self.a.reset_streaks()
        names = [e["event"] for e in self.a.tick()]
        self.assertNotIn("would_apply", names)  # 2 + reset + 1 != 3 seguidas
        self.assertEqual(self.a.detectors[("a", "heavy-reports")].degraded_streak, 1)

    def test_without_reset_the_same_sequence_would_detect(self):
        self.a.tick()
        self.a.tick()
        names = [e["event"] for e in self.a.tick()]
        self.assertIn("would_apply", [n for n in names])

    def test_reset_keeps_a_degraded_state(self):
        for _ in range(3):
            self.a.tick()
        det = self.a.detectors[("a", "heavy-reports")]
        self.assertEqual(det.state, "degraded")
        self.a.reset_streaks()
        self.assertEqual(det.state, "degraded")
        self.assertEqual((det.degraded_streak, det.recovered_streak), (0, 0))

    def test_reset_also_clears_the_watch_detectors(self):
        self.src.s["a"] = snap(w(p95=3000.0, mean=3000.0), w(p95=4500.0, mean=4500.0))
        self.a.tick()
        self.a.tick()
        self.a.reset_streaks()
        self.assertEqual(self.a.watch[("a", "heavy-reports")].degraded_streak, 0)

    def test_reset_of_one_cluster_leaves_the_other(self):
        self.src.s["b"] = snap(w(p95=3000.0), w(p95=4500.0))
        self.a.tick()
        self.a.tick()
        self.a.reset_streaks("a")
        self.assertEqual(self.a.detectors[("a", "heavy-reports")].degraded_streak, 0)
        self.assertEqual(self.a.detectors[("b", "heavy-reports")].degraded_streak, 2)

    def test_reset_unknown_cluster_raises(self):
        with self.assertRaises(KeyError):
            self.a.reset_streaks("z")


if __name__ == "__main__":
    unittest.main()
