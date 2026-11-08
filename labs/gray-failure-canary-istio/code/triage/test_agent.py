import json
import os
import tempfile
import unittest

from agent import ShadowAgent
from detector import Window
from prom import PromClient, p95_query, parse_groups, requests_query

FEATURES = ["dashboard", "heavy-reports"]


def w(n=100, err=0.0, p95=50.0, mean=0.0):
    return Window(n=n, err_pct=err, p95_ms=p95, baseline_p95_ms=0.0, mean_ms=mean)


def healthy_snapshot():
    # heavy-reports é naturalmente lento (~3 s) nas duas versões
    return {
        ("v1", "dashboard"): w(p95=40.0), ("v2", "dashboard"): w(p95=45.0),
        ("v1", "heavy-reports"): w(p95=3100.0), ("v2", "heavy-reports"): w(p95=3200.0),
    }


class FakeSource:
    def __init__(self, clusters=("a", "b")):
        self.snaps = {c: healthy_snapshot() for c in clusters}
        self.fail = set()

    def __call__(self, cluster):
        if cluster in self.fail:
            raise ConnectionError("prometheus indisponível")
        return self.snaps[cluster]


class ShadowAgentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = os.path.join(self.tmp.name, "events.jsonl")
        self.source = FakeSource()

    def tearDown(self):
        self.tmp.cleanup()

    def read_events(self):
        if not os.path.exists(self.events):
            return []
        with open(self.events) as f:
            return [json.loads(line) for line in f]

    def agent(self, clusters=("a",), mode="shadow"):
        return ShadowAgent(list(clusters), FEATURES, self.source, self.events, mode)

    def test_healthy_traffic_writes_nothing(self):
        agent = self.agent(("a", "b"))
        for _ in range(10):
            agent.tick()
        self.assertEqual(self.read_events(), [])

    def test_naturally_slow_feature_is_not_degraded(self):
        # heavy-reports com p95 de 3 s nas duas versões: razão ~1, não degrada
        agent = self.agent()
        for _ in range(5):
            agent.tick()
        self.assertEqual(self.read_events(), [])

    def test_only_the_degraded_feature_is_flagged(self):
        agent = self.agent()
        self.source.snaps["a"][("v2", "heavy-reports")] = w(err=30.0, p95=3200.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        self.assertEqual([(e["event"], e["feature"]) for e in events],
                         [("would_apply", "heavy-reports")])
        self.assertEqual(events[0]["mode"], "shadow")
        self.assertEqual(events[0]["window_stats"]["baseline_p95_ms"], 3100.0)

    def test_latency_regression_uses_per_feature_baseline(self):
        agent = self.agent()
        # 9 s contra baseline de 3,1 s da MESMA feature: > 1,3x, > +500 ms e > 1000 ms
        self.source.snaps["a"][("v2", "heavy-reports")] = w(p95=9000.0)
        for _ in range(3):
            agent.tick()
        self.assertEqual([e["feature"] for e in self.read_events()], ["heavy-reports"])

    def test_partial_regression_detected_by_default_rule_b(self):
        # p95 4500 contra baseline 3100: 1,45x, acima do limiar de B (1,3x e
        # +500 ms) mas abaixo do da regra A (2x = 6200 ms). É o caso do teste
        # de falha parcial: com A como padrão, este evento nunca saía.
        agent = self.agent()
        self.source.snaps["a"][("v2", "heavy-reports")] = w(p95=4500.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        self.assertEqual([(e["event"], e["feature"]) for e in events],
                         [("would_apply", "heavy-reports")])

    def test_rule_c_recorded_alongside_without_own_action(self):
        # B dispara no p95 (4500 > 1,3x3100 e > 3100+500); C dispara na média
        # (4200 > 1,3x3000 e > 3000+500) e fica registrada ao lado, sem ação.
        agent = self.agent()
        self.source.snaps["a"][("v1", "heavy-reports")] = w(p95=3100.0, mean=3000.0)
        self.source.snaps["a"][("v2", "heavy-reports")] = w(p95=4500.0, mean=4200.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        self.assertEqual([(e["event"], e["feature"]) for e in events],
                         [("would_apply", "heavy-reports"),
                          ("c_detected", "heavy-reports")])
        self.assertEqual(events[1]["reason"], "regra C (média), registro apenas")
        self.assertEqual(events[1]["window_stats"]["mean_ms"], 4200.0)
        self.assertEqual(events[1]["window_stats"]["baseline_mean_ms"], 3000.0)

    def test_rule_c_stays_silent_when_mean_healthy(self):
        # Falha parcial medida em 2026-10-27: o p95 sobe (B dispara) mas a
        # média fica diluída (3300 < 1,3x3050), então C não dispara.
        agent = self.agent()
        self.source.snaps["a"][("v1", "heavy-reports")] = w(p95=3100.0, mean=3050.0)
        self.source.snaps["a"][("v2", "heavy-reports")] = w(p95=4600.0, mean=3300.0)
        for _ in range(3):
            agent.tick()
        self.assertEqual([e["event"] for e in self.read_events()], ["would_apply"])

    def test_both_clusters_degraded_is_blocked(self):
        agent = self.agent(("a", "b"))
        for c in "ab":
            self.source.snaps[c][("v2", "dashboard")] = w(err=30.0, p95=45.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        blocked = [e for e in events if e["event"] == "blocked"]
        self.assertEqual(len(blocked), 2)
        self.assertEqual(blocked[0]["reason"], "guardrail:both_clusters_degraded")
        self.assertFalse(any(e["event"] == "would_apply" for e in events))

    def test_other_feature_in_other_cluster_does_not_block(self):
        agent = self.agent(("a", "b"))
        self.source.snaps["a"][("v2", "dashboard")] = w(err=30.0, p95=45.0)
        self.source.snaps["b"][("v2", "heavy-reports")] = w(err=30.0, p95=3200.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        self.assertEqual(sorted((e["cluster"], e["feature"], e["event"]) for e in events),
                         [("a", "dashboard", "would_apply"),
                          ("b", "heavy-reports", "would_apply")])

    def test_recovery_is_recorded(self):
        agent = self.agent()
        self.source.snaps["a"][("v2", "dashboard")] = w(err=30.0, p95=45.0)
        for _ in range(3):
            agent.tick()
        self.source.snaps["a"][("v2", "dashboard")] = w(p95=45.0)
        for _ in range(3):
            agent.tick()
        self.assertEqual([e["event"] for e in self.read_events()],
                         ["would_apply", "recovered"])

    def test_missing_traffic_does_not_advance_detection(self):
        agent = self.agent()
        bad = w(err=30.0, p95=45.0)
        self.source.snaps["a"][("v2", "dashboard")] = bad
        agent.tick()
        agent.tick()
        del self.source.snaps["a"][("v2", "dashboard")]
        agent.tick()
        self.source.snaps["a"][("v2", "dashboard")] = bad
        agent.tick()
        self.assertEqual(agent.detectors[("a", "dashboard")].degraded_streak, 3)

    def test_source_error_takes_no_action(self):
        agent = self.agent(("a", "b"))
        self.source.fail.add("a")
        self.source.snaps["b"][("v2", "dashboard")] = w(err=30.0, p95=45.0)
        for _ in range(3):
            agent.tick()
        events = self.read_events()
        self.assertTrue(any(e["event"] == "source_error" and e["cluster"] == "a" for e in events))
        # b degradou sozinho; a não respondeu, então não conta como degradado
        self.assertEqual([e["event"] for e in events if e["cluster"] == "b"], ["would_apply"])

    def test_off_mode_does_nothing(self):
        agent = self.agent(mode="off")
        self.source.snaps["a"][("v2", "dashboard")] = w(err=30.0, p95=45.0)
        for _ in range(5):
            agent.tick()
        self.assertEqual(self.read_events(), [])

    def test_auto_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.agent(mode="auto")


class PromTest(unittest.TestCase):
    def test_parse_groups_by_version_and_feature(self):
        payload = {
            "status": "success",
            "data": {"result": [
                {"metric": {"destination_canonical_revision": "v1", "feature": "dashboard"},
                 "value": [0, "120.5"]},
                {"metric": {"destination_canonical_revision": "v2", "feature": "other"},
                 "value": [0, "3"]},
            ]},
        }
        self.assertEqual(parse_groups(payload),
                         {("v1", "dashboard"): 120.5, ("v2", "other"): 3.0})

    def test_parse_groups_raises_on_error_status(self):
        with self.assertRaises(ValueError):
            parse_groups({"status": "error", "error": "bad query"})

    def test_queries_use_client_side_probe_series_grouped_by_feature(self):
        for q in (requests_query(), p95_query()):
            self.assertIn('reporter="source"', q)
            self.assertIn('job="probe-generator"', q)
            self.assertIn("feature", q)

    def test_windows_computes_error_pct_and_handles_nan(self):
        def vec(rows):
            return {"status": "success", "data": {"result": [
                {"metric": {"destination_canonical_revision": v, "feature": f}, "value": [0, val]}
                for (v, f), val in rows.items()]}}

        class Fake(PromClient):
            def query(self, promql):
                if "histogram_quantile" in promql:
                    return vec({("v2", "dashboard"): "NaN", ("v1", "dashboard"): "40"})
                if "5.." in promql:
                    return vec({("v2", "dashboard"): "15"})
                return vec({("v2", "dashboard"): "60", ("v1", "dashboard"): "80",
                            ("v2", "other"): "0"})

        wins = Fake("http://x").windows()
        self.assertAlmostEqual(wins[("v2", "dashboard")].err_pct, 25.0)
        self.assertEqual(wins[("v2", "dashboard")].p95_ms, 0.0)  # NaN tratado
        self.assertEqual(wins[("v1", "dashboard")].err_pct, 0.0)
        self.assertNotIn(("v2", "other"), wins)  # n=0 descartado
        self.assertEqual(wins[("v2", "dashboard")].mean_ms, 60.0)  # média preenchida


if __name__ == "__main__":
    unittest.main()
