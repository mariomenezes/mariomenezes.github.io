"""Contrato da análise por versão (estilo mercado) e da detecção por execução (v5)."""
import unittest
from datetime import datetime, timezone

import market_emul as me

T0 = 1761000000


def ts(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def win(v, f, n, b, err=0.0, p95=0.0):
    return {"version": v, "feature": f, "n": n, "err_pct": err, "p95_ms": p95, "mean_ms": 0.0, "buckets": b}


HEAVY_OK = {"1": 0, "250": 0, "3000": 0, "3750": 70, "5000": 70, "+Inf": 70}
HEAVY_BAD = {"1": 0, "250": 0, "3000": 0, "3750": 49, "5000": 70, "+Inf": 70}   # 30% acima de 3750
DASH_OK = {"1": 100, "250": 100, "3000": 100, "3750": 100, "5000": 100, "+Inf": 100}
DASH_BAD = {"1": 80, "250": 80, "3000": 100, "3750": 100, "5000": 100, "+Inf": 100}  # 20% em 250-3000


def sample(t, h2=HEAVY_OK, d2=DASH_OK, err2=0.0):
    return {"ts": ts(t), "windows": [win("v1", "dashboard", 100, DASH_OK), win("v1", "heavy-reports", 70, HEAVY_OK),
                                     win("v2", "dashboard", 100, d2), win("v2", "heavy-reports", 70, h2, err=err2)]}


class AggregateTest(unittest.TestCase):
    def test_buckets_are_summed_over_features(self):
        a = me.aggregate(sample(T0), "v2")
        self.assertEqual(a["n"], 170)
        self.assertEqual(a["buckets"]["1"], 100)
        self.assertEqual(a["buckets"]["3750"], 170)

    def test_error_rate_is_weighted_by_n(self):
        a = me.aggregate(sample(T0, err2=10.0), "v2")
        self.assertAlmostEqual(a["err_pct"], 10.0 * 70 / 170)

    def test_quantile_interpolates_like_prometheus(self):
        b = {"1": 0, "100": 50, "200": 100, "+Inf": 100}
        self.assertAlmostEqual(me.histogram_quantile(0.5, b), 100.0)
        self.assertAlmostEqual(me.histogram_quantile(0.75, b), 150.0)
        self.assertAlmostEqual(me.histogram_quantile(0.99, {"1": 0, "100": 50, "+Inf": 100}), 100.0)  # +Inf: maior borda

    def test_missing_buckets_make_the_aggregate_unavailable(self):
        s = sample(T0)
        del s["windows"][3]["buckets"]
        self.assertIsNone(me.aggregate(s, "v2"))

    def test_dashboard_fault_is_invisible_in_the_aggregate_p99(self):
        ok, bad = me.aggregate(sample(T0), "v2"), me.aggregate(sample(T0, d2=DASH_BAD), "v2")
        self.assertAlmostEqual(me.histogram_quantile(0.99, ok["buckets"]), me.histogram_quantile(0.99, bad["buckets"]))


def run(fault_h=None, fault_d=None, n=14, t_on_idx=3, t_off_idx=11):
    """Execução do runner: rótulos t0, t0+60, ...; falha em [t0+180, t0+660)."""
    out = []
    for i in range(n):
        on = t_on_idx < i <= t_off_idx  # rótulos com falha: (t_on, t_off]
        out.append(sample(T0 + 60 * i, h2=fault_h if on and fault_h else HEAVY_OK,
                          d2=fault_d if on and fault_d else DASH_OK))
    return out, T0 + 180, T0 + 660


class DetectionTest(unittest.TestCase):
    def test_feature_rule_detects_inside_the_fault_labels(self):
        s, on, off = run(fault_d=DASH_BAD)
        r = me.detect(s, on, off, "feature:D", feature="dashboard", limits={"dashboard": 250, "heavy-reports": 3750})
        self.assertTrue(r["detected"])
        self.assertEqual(r["first_label"], T0 + 360)  # 3ª janela com falha: 240, 300, 360
        self.assertEqual(r["ttd_windows"], 3)

    def test_aggregate_misses_the_dashboard_fault(self):
        s, on, off = run(fault_d=DASH_BAD)
        for m in ("agg_b", "flagger_rel"):
            self.assertFalse(me.detect(s, on, off, m)["detected"], m)

    def test_aggregate_catches_a_large_heavy_fault(self):
        s, on, off = run(fault_h={"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70})
        self.assertTrue(me.detect(s, on, off, "agg_b")["detected"])
        self.assertTrue(me.detect(s, on, off, "flagger_rel")["detected"])

    def test_flagger_counts_failed_checks_cumulatively_to_five(self):
        bad = {"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70}
        s = [sample(T0 + 60 * i, h2=bad if i in (4, 6, 8, 10, 11) else HEAVY_OK) for i in range(14)]
        r = me.detect(s, T0 + 180, T0 + 660, "flagger_rel")
        self.assertTrue(r["detected"])           # 5 falhas não consecutivas
        self.assertEqual(r["first_label"], T0 + 660)
        s = [sample(T0 + 60 * i, h2=bad if i in (4, 6, 8, 10) else HEAVY_OK) for i in range(14)]
        self.assertFalse(me.detect(s, T0 + 180, T0 + 660, "flagger_rel")["detected"])  # 4 não bastam
        self.assertFalse(me.detect(s, T0 + 180, T0 + 660, "agg_b")["detected"])        # nunca 3 seguidas

    def test_detection_after_the_spill_window_does_not_count(self):
        bad = {"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70}
        s = [sample(T0 + 60 * i, h2=bad if i >= 11 else HEAVY_OK) for i in range(16)]
        # rótulos ruins 660, 720, 780: a 3ª (780) fica além de t_off + 60 = 720
        self.assertFalse(me.detect(s, T0 + 180, T0 + 660, "agg_b")["detected"])

    def test_detection_exactly_at_t_on_is_a_false_alarm(self):
        bad = {"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70}
        s = [sample(T0 + 60 * i, h2=bad if i in (1, 2, 3) else HEAVY_OK) for i in range(14)]
        r = me.detect(s, T0 + 180, T0 + 660, "agg_b")
        self.assertEqual(r["first_label"], T0 + 180)
        self.assertEqual((r["detected"], r["false_alarm_before"]), (False, True))

    def test_detection_before_the_fault_is_a_false_alarm_not_a_hit(self):
        bad = {"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70}
        s = [sample(T0 + 60 * i, h2=bad if i <= 3 else HEAVY_OK) for i in range(14)]
        r = me.detect(s, T0 + 180, T0 + 660, "agg_b")
        self.assertFalse(r["detected"])
        self.assertTrue(r["false_alarm_before"])


class FrozenTest(unittest.TestCase):
    def test_parameters(self):
        self.assertEqual((me.AGG_QUANTILE, me.FLAGGER_THRESHOLD, me.FLAGGER_MIN_SUCCESS_PCT, me.FLAGGER_MAX_RATIO),
                         (0.99, 5, 99.0, 1.15))

    def test_aggregate_uses_the_p99(self):
        # 3% da v2 acima de 5 s: o p95 agregado não vê, o p99 vê
        slow = {"1": 0, "250": 0, "3000": 0, "3750": 65, "5000": 65, "+Inf": 70}
        w = me._agg_windows([sample(T0, h2=slow)])[0]
        self.assertGreater(w.p95_ms / w.baseline_p95_ms, 1.15)
        self.assertEqual(w.p95_ms, me.histogram_quantile(0.99, me.aggregate(sample(T0, h2=slow), "v2")["buckets"]))


class McNemarTest(unittest.TestCase):
    def test_exact_one_sided(self):
        # 10 discordantes, todos a favor da análise por feature: p = 0,5^10
        self.assertAlmostEqual(me.mcnemar_one_sided(10, 0), 0.5 ** 10)
        self.assertAlmostEqual(me.mcnemar_one_sided(0, 0), 1.0)
        self.assertAlmostEqual(me.mcnemar_one_sided(1, 1), 0.75)


if __name__ == "__main__":
    unittest.main()
