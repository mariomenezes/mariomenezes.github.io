"""Contrato do analisador da avaliação v5 (escrito antes dos dados de cluster)."""
import os
import unittest

import eval_v5 as ev

HERE = os.path.dirname(os.path.abspath(__file__))


class DecisionTest(unittest.TestCase):
    def test_h1_threshold_allows_two_misses_in_thirty(self):
        self.assertTrue(ev.h1_pass(28, 30))
        self.assertFalse(ev.h1_pass(27, 30))
        self.assertFalse(ev.h1_pass(0, 0))

    def test_h3_is_strict_on_the_poisson_upper_bound(self):
        self.assertTrue(ev.h3_pass(0, 30 * 60))     # 0 em 30 h: UB95 0,0999
        self.assertFalse(ev.h3_pass(0, 29 * 60))    # 0 em 29 h: UB95 0,103
        self.assertFalse(ev.h3_pass(1, 30 * 60))

    def test_holm(self):
        adj = ev.holm({"a": 0.01, "b": 0.04, "c": 0.03})
        self.assertAlmostEqual(adj["a"], 0.03)
        self.assertAlmostEqual(adj["c"], 0.06)
        self.assertAlmostEqual(adj["b"], 0.06)  # monotônico: nunca menor que o anterior
        self.assertEqual(ev.holm({"x": 0.6, "y": 0.5})["x"], 1.0)

    def test_h5_rejects_by_the_holm_adjusted_p(self):
        h5 = {"x": {"p": 0.04}, "y": {"p": 0.03}, "z": {"p": 0.001}}  # brutos todos < 0,05
        ev.apply_holm(h5)
        self.assertEqual({k: v["reject"] for k, v in h5.items()}, {"x": False, "y": False, "z": True})
        self.assertAlmostEqual(h5["y"]["p_holm"], 0.06)

    def test_primary_rules_come_from_the_phase2_selection(self):
        self.assertEqual(ev.PRIMARY, {"heavy-reports": "B", "dashboard": "D"})
        self.assertEqual(ev.PRIMARY_SCENARIOS, ("heavy10", "dash10"))


@unittest.skipUnless(os.path.exists(os.path.join(HERE, "results", "pilot-b1", "a", "runs.jsonl")), "sem piloto")
class PilotSmokeTest(unittest.TestCase):
    def setUp(self):
        self.r = ev.analyze(os.path.join(HERE, "results", "pilot-b1"),
                            os.path.join(HERE, "plans", "PILOTO-B1.json"))

    def test_pilot_numbers(self):
        s = self.r["scenarios"]
        self.assertEqual((s["dash10"]["primary"]["hits"], s["dash10"]["primary"]["n"]), (2, 2))
        self.assertEqual(s["dash10"]["methods"]["agg_b"]["hits"], 0)
        self.assertEqual(s["heavy10"]["methods"]["agg_b"]["hits"], 2)
        self.assertEqual(self.r["control"]["windows"], 20)
        self.assertEqual(self.r["control"]["alarms"], {"heavy-reports": 0, "dashboard": 0})
        self.assertEqual(self.r["isolation"]["violations"], [])
        # H5 no dashboard: 2 discordantes a favor da análise por feature
        h5 = self.r["h5"]["dash10/agg_b"]
        self.assertEqual((h5["b"], h5["c"]), (2, 0))
        self.assertAlmostEqual(h5["p"], 0.25)
        self.assertEqual((self.r["h5"]["heavy10/agg_b"]["b"], self.r["h5"]["heavy10/agg_b"]["c"]), (0, 0))

    def test_report_mentions_every_hypothesis(self):
        md = ev.render(self.r)
        for k in ("H1", "H2", "H3", "H5"):
            self.assertIn(k, md)


if __name__ == "__main__":
    unittest.main()
