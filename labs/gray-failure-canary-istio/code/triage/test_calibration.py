"""Testes da etapa de calibração. cd triage && python3 -m unittest -q test_calibration"""
import math
import random
import unittest

import decision_curve as dc
import noise_sim
from calib_lib import (RelativeRule, clopper_pearson, learn_threshold, poisson_upper, quantile,
                       run_detector)
from detector import RULE_B, SubsetDetector, Window


def rand_windows(rng, n):
    out = []
    for _ in range(n):
        base = rng.choice([800.0, 3400.0, 3500.0, 3600.0])
        out.append(Window(n=rng.choice([10, 30, 80]), err_pct=rng.choice([0.0, 0.0, 0.0, 6.0]),
                          p95_ms=base * rng.uniform(0.95, 1.4), baseline_p95_ms=base))
    return out


class RuleEquivalence(unittest.TestCase):
    def test_rule_b_equals_relative_rule(self):
        rng = random.Random(7)
        rule = RelativeRule(ratio=1.15, floor_ms=1000.0, delta_ms=500.0)
        from detector import is_degraded
        for w in rand_windows(rng, 3000):
            self.assertEqual(is_degraded(w, RULE_B), rule.degraded(w))

    def test_state_machine_equals_subset_detector(self):
        rng = random.Random(11)
        rule = RelativeRule(ratio=1.15, floor_ms=1000.0, delta_ms=500.0)
        for _ in range(40):
            ws = rand_windows(rng, 120)
            det = SubsetDetector("c", "f", rule=RULE_B)
            ref = [(i, e) for i, w in enumerate(ws) if (e := det.observe(w))]
            self.assertEqual(ref, run_detector(ws, rule))

    def test_relative_delta_is_looser_than_fixed(self):
        w = Window(n=80, err_pct=0.0, p95_ms=3400 * 1.10, baseline_p95_ms=3400.0)
        self.assertTrue(RelativeRule(ratio=1.08, delta_ms=0.0).degraded(w))
        self.assertFalse(RelativeRule(ratio=1.08, delta_ms=500.0).degraded(w))


class Stats(unittest.TestCase):
    def test_clopper_pearson_known_values(self):
        lo, hi = clopper_pearson(10, 10)
        self.assertAlmostEqual(lo, 0.6915, places=3)
        self.assertEqual(hi, 1.0)
        lo1, _ = clopper_pearson(10, 10, two_sided=False)
        self.assertAlmostEqual(lo1, 0.05 ** 0.1, places=4)  # ~0,741: o "74%" do post
        lo0, hi0 = clopper_pearson(0, 10)
        self.assertEqual(lo0, 0.0)
        self.assertAlmostEqual(hi0, 0.3085, places=3)
        lo, hi = clopper_pearson(3, 6)
        self.assertAlmostEqual(lo, 0.1181, places=3)
        self.assertAlmostEqual(hi, 0.8819, places=3)

    def test_poisson_upper(self):
        self.assertAlmostEqual(poisson_upper(0, 1.0), 2.9957, places=3)
        self.assertAlmostEqual(poisson_upper(0, 8.0), 0.3745, places=3)  # o "0,37" do post
        self.assertAlmostEqual(poisson_upper(1, 1.0), 4.7439, places=3)

    def test_quantile(self):
        self.assertEqual(quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(quantile([5], 0.99), 5)

    def test_learn_threshold_recovers_lognormal_tail(self):
        rng = random.Random(3)
        sd = 0.04
        xs = [rng.lognormvariate(0, sd) for _ in range(40000)]
        info = learn_threshold(xs, alpha=1e-3)
        want = math.exp(3.0902 * sd)
        self.assertTrue(info["estimable_by_sample"])
        self.assertAlmostEqual(info["threshold"], max(want, 1.05), delta=0.02)

    def test_learn_threshold_small_sample_uses_fit(self):
        rng = random.Random(5)
        xs = [rng.lognormvariate(0, 0.05) for _ in range(300)]
        info = learn_threshold(xs, alpha=1e-3)
        self.assertFalse(info["estimable_by_sample"])
        self.assertGreaterEqual(info["threshold"], info["max"] * 0.0 + info["lognormal_q"] - 1e-9)

    def test_learn_threshold_never_below_min_ratio(self):
        info = learn_threshold([1.0] * 50 + [1.001], alpha=1e-3)
        self.assertEqual(info["threshold"], 1.05)
        self.assertTrue(info["binding_min_ratio"])


class Simulation(unittest.TestCase):
    def test_fast_quantile_matches_noise_sim(self):
        rng = random.Random(1)
        for _ in range(60):
            lat = [rng.choice([rng.uniform(2800, 3900), 5000 + rng.uniform(0, 2500), 10000.0])
                   for _ in range(rng.randint(30, 200))]
            self.assertAlmostEqual(dc.fast_quantile(sorted(lat), 0.95),
                                   noise_sim.histogram_quantile(0.95, lat), places=9)

    def test_deterministic(self):
        a = dc.simulate(random.Random(9), dc.NOISES["ln0.1"], 20, 80)
        b = dc.simulate(random.Random(9), dc.NOISES["ln0.1"], 20, 80)
        self.assertEqual(a, b)

    def test_no_noise_no_false_alarm_and_detects(self):
        rng = random.Random(2)
        nz = dc.NOISES["none"]
        rule = RelativeRule(ratio=1.15, floor_ms=1000.0, delta_ms=500.0)
        self.assertEqual(dc.alarms_in_healthy(dc.healthy_runs(rng, nz, 6, 80), rule), 0)
        hits, ttd = dc.detections(dc.fault_runs(rng, nz, 20, 80, frac=0.2, extra_s=1.5), rule)
        self.assertGreaterEqual(hits, 18)
        self.assertTrue(all(1 <= t <= dc.FAULT_WINDOWS for t in ttd))

    def test_slow_pod_raises_v2_ratio(self):
        rng = random.Random(4)
        nz = dc.NOISES["ln0.1_pods3"]
        ws = dc.simulate(rng, nz, 13, 80, pre=5, pod_extra_s=1.0)
        before = sum(w.p95_ms / w.baseline_p95_ms for w in ws[:5]) / 5
        after = sum(w.p95_ms / w.baseline_p95_ms for w in ws[5:]) / 8
        self.assertGreater(after, before + 0.15)

    def test_all_noise_presets_run(self):
        for name, nz in dc.NOISES.items():
            ws = dc.simulate(random.Random(1), nz, 6, 40)
            self.assertEqual(len(ws), 6, name)


if __name__ == "__main__":
    unittest.main()
