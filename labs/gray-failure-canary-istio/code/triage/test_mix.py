import unittest

from detector import RULES
from mix_test import analyze, compare


def sample(dash_n, dash_p95, heavy_n, heavy_p95, agg_p95):
    return {
        "ts": "t",
        "windows": [
            {"version": "v2", "feature": "dashboard", "n": dash_n, "err_pct": 0.0, "p95_ms": dash_p95},
            {"version": "v2", "feature": "heavy-reports", "n": heavy_n, "err_pct": 0.0, "p95_ms": heavy_p95},
        ],
        "p95_by_version": {"v2": agg_p95},
    }


class MixTest(unittest.TestCase):
    def test_mix_shift_alarms_aggregate_only(self):
        # latência de cada feature fixa; só a proporção muda
        base = [sample(100, 200, 100, 200, 200) for _ in range(3)]
        shift = [sample(40, 200, 160, 200, 2300) for _ in range(3)]
        res = analyze(base + shift, "b")
        self.assertFalse(res.feature_alarm)
        self.assertTrue(res.agg_alarm)

    def test_real_degradation_alarms_both(self):
        base = [sample(100, 200, 100, 200, 200) for _ in range(3)]
        bad = [sample(100, 3000, 100, 200, 1500) for _ in range(3)]
        res = analyze(base + bad, "b")
        self.assertTrue(res.feature_alarm)
        self.assertTrue(res.agg_alarm)

    def test_low_volume_is_ignored(self):
        base = [sample(100, 200, 100, 200, 200) for _ in range(3)]
        thin = [sample(5, 3000, 5, 3000, 3000) for _ in range(5)]
        res = analyze(base + thin, "b")
        self.assertFalse(res.feature_alarm)
        self.assertFalse(res.agg_alarm)
        self.assertGreater(res.insufficient.get("dashboard", 0), 0)


def lat_sample(heavy_n, heavy_p95, heavy_mean, agg_p95=None, agg_mean=None):
    # latência de dashboard fixa; heavy-reports com p95/média controlados
    return {
        "ts": "t",
        "windows": [
            {"version": "v2", "feature": "dashboard", "n": 100, "err_pct": 0.0, "p95_ms": 200.0, "mean_ms": 150.0},
            {"version": "v2", "feature": "heavy-reports", "n": heavy_n, "err_pct": 0.0,
             "p95_ms": heavy_p95, "mean_ms": heavy_mean},
        ],
        "p95_by_version": {"v2": agg_p95 if agg_p95 is not None else heavy_p95},
        "mean_by_version": {"v2": agg_mean if agg_mean is not None else heavy_mean},
    }


class RuleTest(unittest.TestCase):
    def test_regression_detected_by_b_and_c_not_a(self):
        base = [lat_sample(100, 3000.0, 2000.0) for _ in range(3)]
        slow = [lat_sample(100, 4500.0, 3000.0) for _ in range(3)]
        samples = base + slow
        self.assertFalse(analyze(samples, "b", rule="A").feature_alarm)
        self.assertTrue(analyze(samples, "b", rule="B").feature_alarm)
        self.assertTrue(analyze(samples, "b", rule="C").feature_alarm)

    def test_bucket_border_jump_does_not_alarm_b(self):
        base = [lat_sample(100, 2975.0, 2000.0) for _ in range(3)]
        jump = [lat_sample(100, 3475.0, 2100.0) for _ in range(5)]
        res = analyze(base + jump, "b", rule="B")
        self.assertFalse(res.feature_alarm)
        self.assertFalse(res.agg_alarm)

    def test_compare_lists_all_rules(self):
        base = [lat_sample(100, 3000.0, 2000.0) for _ in range(3)]
        slow = [lat_sample(100, 4500.0, 3000.0) for _ in range(3)]
        out = compare(base + slow, "b")
        for line in ("A      não", "B      SIM", "C      SIM"):
            self.assertIn(line, out)

    def test_c_without_mean_in_samples_is_silent(self):
        # amostras antigas, sem mean_ms: a regra C não tem baseline e não dispara
        old = [sample(100, 3000, 100, 3000, 3000) for _ in range(3)]
        slow = [sample(100, 9000, 100, 9000, 9000) for _ in range(5)]
        self.assertFalse(analyze(old + slow, "b", rule="C").feature_alarm)


def dash_sample(dash_p95, dash_mean):
    # dashboard com p95/média controlados; heavy-reports na baseline (2988/3000)
    return {
        "ts": "t",
        "windows": [
            {"version": "v2", "feature": "dashboard", "n": 140, "err_pct": 0.0,
             "p95_ms": dash_p95, "mean_ms": dash_mean},
            {"version": "v2", "feature": "heavy-reports", "n": 100, "err_pct": 0.0,
             "p95_ms": 2988.0, "mean_ms": 3000.0},
        ],
        "p95_by_version": {"v2": 2988.0},
        "mean_by_version": {"v2": (140 * dash_mean + 100 * 3000.0) / 240.0},
    }


class PartialMixTest(unittest.TestCase):
    """Falha parcial por feature (gray failure): só a feature injetada alarma."""

    def test_partial_heavy_b_fires_c_and_a_do_not(self):
        # 10% das requisições de heavy-reports com +1500 ms: p95 no grupo
        # lento, média quase constante
        base = [lat_sample(100, 2988.0, 3000.0) for _ in range(3)]
        partial = [lat_sample(100, 4500.0, 3150.0) for _ in range(3)]
        samples = base + partial
        self.assertFalse(analyze(samples, "b", rule="A").feature_alarm)
        res_b = analyze(samples, "b", rule="B")
        self.assertTrue(res_b.feature_alarm)
        self.assertEqual(list(res_b.feature_events), ["heavy-reports"])
        self.assertFalse(analyze(samples, "b", rule="C").feature_alarm)

    def test_partial_heavy_only_injected_feature_alarms(self):
        # isolamento: dashboard (co-ocorrente na mesma v2) não pode alarmar
        base = [lat_sample(100, 2988.0, 3000.0) for _ in range(3)]
        partial = [lat_sample(100, 4500.0, 3150.0) for _ in range(3)]
        res = analyze(base + partial, "b", rule="B")
        self.assertNotIn("dashboard", res.feature_events)

    def test_partial_dashboard_blind_to_all_rules(self):
        # lacuna 2: 20% de fast-data com +500 ms (p95 ~500 ms, média ~102 ms);
        # piso de 1000 ms: nenhuma regra dispara
        base = [dash_sample(4.0, 4.0) for _ in range(3)]
        bad = [dash_sample(500.0, 102.0) for _ in range(3)]
        for rule in RULES:
            res = analyze(base + bad, "b", rule=rule)
            self.assertFalse(res.feature_alarm, rule)
            self.assertNotIn("dashboard", res.feature_events, rule)


class TransitionTest(unittest.TestCase):
    def test_transition_window_hides_alarm_unless_skipped(self):
        # janela 0: rollout ainda com heavy residual, p95 agregado alto
        transition = sample(100, 200, 100, 3000, 2300)
        clean = [sample(500, 5, 0, 0, 5) for _ in range(3)]
        mixed = [sample(330, 5, 40, 4875, 3700) for _ in range(3)]
        samples = [transition] + clean + mixed
        self.assertFalse(analyze(samples, "b").agg_alarm)
        self.assertTrue(analyze(samples, "b", skip=1).agg_alarm)


if __name__ == "__main__":
    unittest.main()
