"""Contrato da Fase 2 (decision_curve: dashboard, regras BF e D, seleção e portão).

Escrito antes do código. Nenhum teste fala com cluster."""
import random
import unittest
from dataclasses import replace

import decision_curve as dc
import detector
from detector import RULE_B, RULE_BF, RULE_D, SubsetDetector, Window


def rand_window(rng, n_lo=20, n_hi=120):
    n, bn = rng.randint(n_lo, n_hi), rng.randint(n_lo, n_hi)
    return Window(n=n, err_pct=rng.choice([0.0, 0.0, 0.0, 6.0]), p95_ms=rng.uniform(0, 5000),
                  baseline_p95_ms=rng.uniform(0, 5000), slow_n=rng.randint(-1, n),
                  base_n=bn, base_slow_n=rng.randint(-1, bn))


class SlowCountTest(unittest.TestCase):
    def test_slow_count_is_strictly_above_the_edge_like_the_le_bucket(self):
        lat = sorted([100.0, 250.0, 250.0, 250.1, 400.0])
        self.assertEqual(dc.slow_above(lat, 250.0), 2)  # le="250" conta <= 250
        self.assertEqual(dc.slow_above(lat, 500.0), 0)
        self.assertEqual(dc.slow_above(lat, 99.0), 5)

    def test_limits_must_be_real_bucket_edges(self):
        with self.assertRaises(ValueError):
            dc.check_edges([300.0])
        dc.check_edges([250.0, 3750.0, 100.0, 500.0])


class FeatureModelTest(unittest.TestCase):
    def test_dashboard_healthy_p95_matches_the_bucket_of_each_cluster(self):
        # medido no controle: p95 0,9-1,0 ms (a, latência < 1 ms) e 4,8 ms (b, > 1 ms)
        for c, (lo, hi) in (("a", (0.85, 1.0)), ("b", (4.7, 4.9))):
            ws = dc.simulate_feature(random.Random(1), "dashboard", c, 0.1, 30)
            med = sorted(sw.w.p95_ms for sw in ws)[15]
            self.assertTrue(lo <= med <= hi, (c, med))
            self.assertTrue(all(sw.w.baseline_p95_ms > 0 for sw in ws))

    def test_dashboard_fault_moves_p95_to_the_500_1000_bucket(self):
        ws = dc.simulate_feature(random.Random(2), "dashboard", "a", 0.1, 40, pre=0, frac=0.2, extra_s=0.5)
        med = sorted(sw.w.p95_ms for sw in ws)[20]
        self.assertTrue(500 < med <= 1000, med)  # medido no lab: 447 a 909 ms

    def test_dashboard_fault_only_after_pre(self):
        ws = dc.simulate_feature(random.Random(9), "dashboard", "b", 0.1, 8, pre=5, frac=1.0, extra_s=0.5)
        self.assertTrue(all(x.counts[250.0][0] == 0 for x in ws[:5]))
        self.assertTrue(all(x.counts[250.0][0] == x.w.n for x in ws[5:]))

    def test_sigma_does_not_touch_dashboard(self):
        a = dc.simulate_feature(random.Random(3), "dashboard", "b", 0.1, 20)
        b = dc.simulate_feature(random.Random(3), "dashboard", "b", 0.3, 20)
        self.assertEqual([x.w.p95_ms for x in a], [x.w.p95_ms for x in b])

    def test_counts_for_every_candidate_limit_and_n_from_the_same_requests(self):
        sw = dc.simulate_feature(random.Random(4), "heavy-reports", "a", 0.3, 1, frac=0.0)[0]
        for lim in dc.LIMIT_GRID["heavy-reports"]:
            s2, s1 = sw.counts[lim]
            self.assertTrue(0 <= s2 <= sw.w.n and 0 <= s1 <= sw.w.base_n)
        for lim in (3500.0, 3750.0, 4000.0):
            w = dc.window_for(dc.RuleSpec("D", RULE_D, limit=lim), sw)
            self.assertEqual((w.slow_n, w.base_slow_n), sw.counts[lim])
        self.assertNotEqual(sw.counts[3500.0], sw.counts[4000.0])  # σ=0,3: as bordas diferem

    def test_fault_only_after_pre_and_only_on_v2(self):
        ws = dc.simulate_feature(random.Random(5), "heavy-reports", "b", 0.1, 10, pre=5, frac=1.0, extra_s=1.5)
        self.assertTrue(all(x.counts[3750.0][1] < x.w.base_n for x in ws))   # v1 nunca toda lenta
        self.assertTrue(all(x.counts[3750.0][0] == x.w.n for x in ws[5:]))  # v2 toda lenta na falha
        self.assertTrue(all(x.counts[3750.0][0] < x.w.n for x in ws[:5]))


class DeciderTest(unittest.TestCase):
    def test_default_specs_delegate_to_the_real_detector(self):
        rng = random.Random(6)
        for feat in ("heavy-reports", "dashboard"):
            for spec in dc.primary_specs(feat):
                dec, insuf = dc.make_decider(spec, feat)
                for _ in range(400):
                    w = rand_window(rng)
                    self.assertEqual(dec(w), detector.is_degraded(w, spec.rule, feat), spec)
                    self.assertEqual(insuf(w), detector.is_insufficient(w, spec.rule), spec)

    def test_variants_at_default_params_equal_the_detector(self):
        rng = random.Random(7)
        floor = detector.PER_FEATURE_LATENCY["dashboard"][0]
        cases = [(dc.RuleSpec("x", RULE_BF, floor=floor, variant=True), RULE_BF),
                 (dc.RuleSpec("y", RULE_D, limit=250.0, delta=detector.SLOW_FRAC_DELTA, variant=True), RULE_D)]
        for spec, rule in cases:
            dec, insuf = dc.make_decider(spec, "dashboard")
            checked = 0
            for _ in range(3000):
                w = rand_window(rng)
                self.assertEqual(insuf(w), detector.is_insufficient(w, rule))
                if not insuf(w):  # só janelas que contam para a sequência
                    checked += 1
                    self.assertEqual(dec(w), detector.is_degraded(w, rule, "dashboard"), (spec, w))
            self.assertGreater(checked, 300)

    def test_variant_parameters_change_the_decision(self):
        w = Window(n=100, err_pct=0.0, p95_ms=300.0, baseline_p95_ms=1.0)
        lo = dc.make_decider(dc.RuleSpec("x", RULE_BF, floor=100.0, variant=True), "dashboard")[0]
        hi = dc.make_decider(dc.RuleSpec("x", RULE_BF, floor=500.0, variant=True), "dashboard")[0]
        self.assertTrue(lo(w))
        self.assertFalse(hi(w))
        d = Window(n=100, err_pct=0.0, p95_ms=0, baseline_p95_ms=0, slow_n=13, base_n=100, base_slow_n=0)
        # +13 pp, z = 3,7: passa com delta 10 pp, não com... (13 >= 10) e falha com 15 pp
        self.assertTrue(dc.make_decider(dc.RuleSpec("d", RULE_D, delta=0.10, variant=True), "x")[0](d))
        self.assertFalse(dc.make_decider(dc.RuleSpec("d", RULE_D, delta=0.15, variant=True), "x")[0](d))

    def test_streak_events_equal_subset_detector(self):
        rng = random.Random(8)
        for rule in (RULE_B, RULE_D):
            for _ in range(30):
                seq = [rand_window(rng, 25, 60) for _ in range(40)]
                det = SubsetDetector("a", "dashboard", rule=rule)
                want = [(i, e) for i, w in enumerate(seq) for e in [det.observe(w)] if e]
                dec, insuf = dc.make_decider(dc.RuleSpec("s", rule), "dashboard")
                self.assertEqual(dc.streak_events(seq, dec, insuf), want)


def cell(fa_ub, f10, f05=0.5, ttd=3.0):
    return {"fa_ub95": fa_ub, "faults": {"f10": {"rate": f10, "ttd_med": ttd}, "f05": {"rate": f05, "ttd_med": ttd}}}


class SelectionTest(unittest.TestCase):
    NAMES = ("B", "BF", "D")

    def table(self, **per):
        # per[name] = lista de células (uma por cluster)
        return {n: per[n] for n in self.NAMES}

    def test_ineligible_rules_are_excluded_even_if_they_detect_more(self):
        t = self.table(B=[cell(0.05, 0.9), cell(0.05, 0.9)], BF=[cell(0.05, 0.9), cell(0.05, 0.9)],
                       D=[cell(0.05, 1.0), cell(0.2, 1.0)])
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "B")

    def test_fa_target_is_strict(self):
        t = self.table(B=[cell(0.1, 1.0)] * 2, BF=[cell(0.1, 1.0)] * 2, D=[cell(0.0999, 0.5)] * 2)
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "D")

    def test_score_is_the_worst_cluster(self):
        t = self.table(B=[cell(0, 1.0), cell(0, 0.6)], BF=[cell(0, 0.8), cell(0, 0.8)], D=[cell(0, 0.7), cell(0, 0.7)])
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "BF")

    def test_ties_go_to_f05_then_ttd_then_simplicity(self):
        t = self.table(B=[cell(0, 1.0, 0.3)] * 2, BF=[cell(0, 1.0, 0.4)] * 2, D=[cell(0, 1.0, 0.4)] * 2)
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "BF")
        t = self.table(B=[cell(0, 1.0, 0.4, 4.0)] * 2, BF=[cell(0, 1.0, 0.4, 4.0)] * 2, D=[cell(0, 1.0, 0.4, 3.0)] * 2)
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "D")
        t = self.table(B=[cell(0, 1.0, 0.4, 3.0)] * 2, BF=[cell(0, 1.0, 0.4, 3.0)] * 2, D=[cell(0, 1.0, 0.4, 3.0)] * 2)
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "B")

    def test_no_eligible_rule_returns_none(self):
        t = self.table(B=[cell(0.5, 1.0)] * 2, BF=[cell(0.5, 1.0)] * 2, D=[cell(0.5, 1.0)] * 2)
        self.assertIsNone(dc.select_rule(t, self.NAMES)[0])

    def test_missing_ttd_ranks_last(self):
        t = self.table(B=[cell(0, 1.0, 0.4, None)] * 2, BF=[cell(0, 1.0, 0.4, 5.0)] * 2, D=[cell(0, 1.0, 0.4, None)] * 2)
        self.assertEqual(dc.select_rule(t, self.NAMES)[0], "BF")


class GateConsequenceTest(unittest.TestCase):
    def cal(self, d_ok=True):
        good, bad = cell(0.04, 0.98, 0.2), cell(1.2, 0.5, 0.3)
        out = {}
        for c in ("a", "b"):
            out[f"heavy-reports|{c}|0.1"] = {"B": good, "BF": good, "D": cell(0.04, 0.99, 0.3)}
            out[f"heavy-reports|{c}|0.3"] = {"B": bad, "BF": bad, "D": cell(0.06, 0.05, 0.0)}
            for sg in ("0.1", "0.3"):
                out[f"dashboard|{c}|{sg}"] = {"B": cell(0.04, 0.0, 0.0), "BF": good, "D": cell(0.04, 0.98, 0.3)}
        return out

    def test_level_failure_removes_d_only_on_heavy_reports(self):
        sel = dc.final_selection(self.cal(), {"decision_ok": True, "level_ok": False},
                                 features=("heavy-reports", "dashboard"), sigmas=(0.1, 0.3), clusters=("a", "b"))
        self.assertEqual(sel["heavy-reports|0.1"]["rule"], "B")    # D venceria sem o portão
        self.assertEqual(sel["heavy-reports|0.3"]["rule"], "B")    # só D era elegível: nenhuma -> B
        self.assertTrue(sel["heavy-reports|0.3"]["predict_h3_fail"])
        self.assertEqual(sel["dashboard|0.1"]["rule"], "D")        # dashboard não é afetado
        self.assertFalse(sel["dashboard|0.1"]["predict_h3_fail"])

    def test_decision_failure_falls_back_to_b_everywhere(self):
        sel = dc.final_selection(self.cal(), {"decision_ok": False, "level_ok": True},
                                 features=("heavy-reports", "dashboard"), sigmas=(0.1,), clusters=("a", "b"))
        self.assertEqual({v["rule"] for v in sel.values()}, {"B"})

    def test_passing_gate_keeps_the_calibration_choice(self):
        sel = dc.final_selection(self.cal(), {"decision_ok": True, "level_ok": True},
                                 features=("heavy-reports",), sigmas=(0.1, 0.3), clusters=("a", "b"))
        self.assertEqual((sel["heavy-reports|0.1"]["rule"], sel["heavy-reports|0.3"]["rule"]), ("D", "D"))


class CalibrationOnlyTest(unittest.TestCase):
    def test_selection_never_sees_the_evaluation_seed(self):
        kw = dict(features=("dashboard",), clusters=("a",), sigmas=(0.1,), hours=1, runs=4)
        r1 = dc.run_phase2(seed=1, eval_seed=10, **kw)
        r2 = dc.run_phase2(seed=1, eval_seed=99, **kw)
        self.assertEqual(r1["selection"], r2["selection"])
        self.assertEqual(r1["calibration"], r2["calibration"])
        self.assertNotEqual(r1["evaluation"], r2["evaluation"])

    def test_calibration_and_evaluation_seeds_must_differ(self):
        with self.assertRaises(ValueError):
            dc.run_phase2(seed=3, eval_seed=3, features=("dashboard",), clusters=("a",), sigmas=(0.1,),
                          hours=1, runs=2)


class GateTest(unittest.TestCase):
    def test_interval_is_the_central_95_percent_and_inclusive(self):
        lo, hi = dc.central_interval(list(range(1, 201)))
        self.assertEqual((lo, hi), (dc.quantile(list(range(1, 201)), 0.025), dc.quantile(list(range(1, 201)), 0.975)))
        res = dc.check_gate({"m": (1.0, 2.0)}, {"m": 2.0})
        self.assertTrue(res["m"]["ok"])
        self.assertTrue(dc.check_gate({"m": (1.0, 2.0)}, {"m": 1.0})["m"]["ok"])
        self.assertFalse(dc.check_gate({"m": (1.0, 2.0)}, {"m": 2.0001})["m"]["ok"])
        self.assertFalse(dc.check_gate({"m": (1.0, 2.0)}, {"m": 0.9999})["m"]["ok"])

    def test_a_metric_without_measurement_fails_closed(self):
        self.assertFalse(dc.check_gate({"m": (1.0, 2.0)}, {})["m"]["ok"])

    def test_verdict_splits_decision_and_level_metrics(self):
        pred = {"a/ratio_q99": (1, 2), "a/p95_v1_med": (1, 2)}
        v = dc.gate_verdict(dc.check_gate(pred, {"a/ratio_q99": 1.5, "a/p95_v1_med": 3}))
        self.assertEqual((v["decision_ok"], v["level_ok"]), (True, False))
        v = dc.gate_verdict(dc.check_gate(pred, {"a/ratio_q99": 3, "a/p95_v1_med": 1.5}))
        self.assertEqual((v["decision_ok"], v["level_ok"]), (False, True))

    def test_campaign_metrics_have_the_measured_keys(self):
        m = dc.gate_campaign(random.Random(1), "a", control_windows=20, reps=2)
        self.assertEqual(set(m), set(dc.GATE_METRICS))
        for k in ("b115_f20", "b115_f10", "b130_f20", "b130_f10", "b115_control_alarms"):
            self.assertIsInstance(m[k], int)

    def test_campaign_uses_both_ratios(self):
        # σ=0,1, falha de 10%: 1,15x detecta quase sempre, 1,3x quase nunca (medido: 10/10 e 1/10)
        tot = {"b115_f10": 0, "b130_f10": 0}
        for s in range(3):
            m = dc.gate_campaign(random.Random(s), "b", control_windows=5, reps=5)
            for k in tot:
                tot[k] += m[k]
        self.assertGreaterEqual(tot["b115_f10"], 12)
        self.assertLessEqual(tot["b130_f10"], 6)


class GateMeasureTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, rows):
        import json
        import os
        with open(os.path.join(self.tmp.name, name), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    @staticmethod
    def row(i, p1, p2, m1=3000.0):
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(1761000000 + 60 * i, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        w = lambda v, f, p, m: {"version": v, "feature": f, "n": 80, "err_pct": 0.0, "p95_ms": p, "mean_ms": m}  # noqa: E731
        return {"ts": ts, "windows": [w("v1", "dashboard", 1.0, 1.0), w("v2", "dashboard", 1.0, 1.0),
                                      w("v1", "heavy-reports", p1, m1), w("v2", "heavy-reports", p2, m1)]}

    def test_definitions_match_the_campaign(self):
        import gate_measure
        ctrl = [self.row(0, 9999, 1)] + [self.row(i, 3000.0, 3000.0 * (1 + 0.01 * (i % 5))) for i in range(1, 101)]
        self.write("ncontrol-a.jsonl", ctrl)
        bad = [self.row(i, 3000.0, 4500.0 if i >= 5 else 3000.0) for i in range(13)]
        weak = [self.row(i, 3000.0, 3600.0 if i >= 5 else 3000.0) for i in range(13)]  # 1,2x: só 1,15x
        self.write("np0.2r1-a.jsonl", bad)
        self.write("np0.2r2-a.jsonl", weak)
        self.write("np0.1r1-a.jsonl", ctrl[:13])
        m = gate_measure.measure(self.tmp.name, clusters=("a",))
        self.assertEqual(m["a/control_windows"], 100)  # pula a 1ª
        self.assertAlmostEqual(m["a/ratio_q50"], 1.02)
        self.assertEqual((m["a/p95_v1_med"], m["a/mean_v1_med"], m["a/b115_control_alarms"]), (3000.0, 3000.0, 0))
        self.assertEqual((m["a/b115_f20"], m["a/b130_f20"], m["a/runs_f20"]), (2, 1, 2))
        self.assertEqual((m["a/b115_f10"], m["a/b130_f10"], m["a/runs_f10"]), (0, 0, 1))


if __name__ == "__main__":
    unittest.main()
