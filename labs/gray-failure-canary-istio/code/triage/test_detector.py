import unittest

from detector import (
    RULE_A,
    RULE_B,
    RULE_C,
    RULES,
    SubsetDetector,
    Window,
    both_clusters_degraded,
    is_degraded,
)

OK = Window(n=100, err_pct=0.0, p95_ms=500.0, baseline_p95_ms=400.0)
HIGH_ERR = Window(n=100, err_pct=20.0, p95_ms=500.0, baseline_p95_ms=400.0)
SLOW = Window(n=100, err_pct=0.0, p95_ms=8000.0, baseline_p95_ms=3000.0)
LOW_SAMPLE_BAD = Window(n=5, err_pct=100.0, p95_ms=9000.0, baseline_p95_ms=400.0)


class IsDegradedTest(unittest.TestCase):
    def test_error_rate_above_limit(self):
        self.assertTrue(is_degraded(HIGH_ERR))

    def test_healthy_window(self):
        self.assertFalse(is_degraded(OK))

    def test_slow_needs_both_ratio_and_absolute(self):
        # 1500 ms é 3x a baseline de 500 e acima de 1000 ms.
        self.assertTrue(is_degraded(Window(100, 0.0, 1500.0, 500.0)))
        # 1200 ms com baseline 1000: razão 1.2, não degrada.
        self.assertFalse(is_degraded(Window(100, 0.0, 1200.0, 1000.0)))
        # 2100 ms com baseline 1000: razão 2.1, mas já é > 1000 ms, então degrada.
        self.assertTrue(is_degraded(Window(100, 0.0, 2100.0, 1000.0)))
        # 900 ms com baseline 300: razão 3x, mas abaixo do limite absoluto.
        self.assertFalse(is_degraded(Window(100, 0.0, 900.0, 300.0)))

    def test_error_threshold_is_strict(self):
        self.assertFalse(is_degraded(Window(100, 5.0, 500.0, 400.0)))
        self.assertTrue(is_degraded(Window(100, 5.01, 500.0, 400.0)))


class LatencyRulesTest(unittest.TestCase):
    def test_default_rule_is_a(self):
        w = Window(100, 0.0, 4500.0, 3000.0)
        self.assertEqual(is_degraded(w), is_degraded(w, RULE_A))
        self.assertFalse(is_degraded(w))

    def test_regression_3s_to_4_5s_only_b_fires(self):
        # o caso da proposta: abaixo do timeout de 5 s, ~1.5x do baseline
        w = Window(100, 0.0, 4500.0, 3000.0)
        self.assertFalse(is_degraded(w, RULE_A))
        self.assertTrue(is_degraded(w, RULE_B))

    def test_b_does_not_fire_on_bucket_border_jump(self):
        # p95 oscila 2975 <-> 3475 por borda de bucket (~17%)
        self.assertFalse(is_degraded(Window(100, 0.0, 3475.0, 2975.0), RULE_B))
        self.assertFalse(is_degraded(Window(100, 0.0, 2975.0, 3475.0), RULE_B))

    def test_b_keeps_absolute_floor(self):
        # 1.5x e +500 ms, mas abaixo de 1000 ms
        self.assertFalse(is_degraded(Window(100, 0.0, 900.0, 500.0), RULE_B))
        self.assertTrue(is_degraded(Window(100, 0.0, 1100.0, 500.0), RULE_B))

    def test_b_needs_absolute_delta_and_ratio(self):
        # 1.13x com baseline 3000: 3400 ms, abaixo de 1.15x (3450) e de +500 ms (3500)
        self.assertFalse(is_degraded(Window(100, 0.0, 3400.0, 3000.0), RULE_B))
        # 1.2x e +600 ms: acima dos dois limites
        self.assertTrue(is_degraded(Window(100, 0.0, 3600.0, 3000.0), RULE_B))
        # 1.1x com baseline 6000: 6600 ms, +600 ms mas abaixo de 1.15x (6900)
        self.assertFalse(is_degraded(Window(100, 0.0, 6600.0, 6000.0), RULE_B))
        # 1.4x com baseline 500: 700 ms, +200 ms, abaixo do piso e do delta
        self.assertFalse(is_degraded(Window(100, 0.0, 700.0, 500.0), RULE_B))

    def test_c_uses_mean_and_same_thresholds(self):
        # média 1000 -> 1600: 1.6x, +600 ms, acima de 1000 ms
        w = Window(100, 0.0, 0.0, 0.0, mean_ms=1600.0, baseline_mean_ms=1000.0)
        self.assertTrue(is_degraded(w, RULE_C))
        self.assertFalse(is_degraded(w, RULE_B))  # p95 zerado, não degrada por B
        w = Window(100, 0.0, 0.0, 0.0, mean_ms=1200.0, baseline_mean_ms=1000.0)
        self.assertFalse(is_degraded(w, RULE_C))

    def test_c_without_mean_baseline_never_fires(self):
        w = Window(100, 0.0, 0.0, 0.0, mean_ms=9000.0, baseline_mean_ms=0.0)
        self.assertFalse(is_degraded(w, RULE_C))

    def test_error_rule_applies_to_every_rule(self):
        for rule in (RULE_A, RULE_B, RULE_C):
            self.assertTrue(is_degraded(HIGH_ERR, rule))

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            is_degraded(OK, "Z")

    def test_subset_detector_uses_its_rule(self):
        d = SubsetDetector("a", "heavy-reports", rule=RULE_B)
        slow = Window(100, 0.0, 4500.0, 3000.0)
        for _ in range(2):
            d.observe(slow)
        self.assertEqual(d.observe(slow), "detected")


class PartialFailureTest(unittest.TestCase):
    """Falha parcial (gray failure): fração das requisições degrada.

    A cauda sobe (p95 cai no grupo lento) mas a média mal muda, porque a
    maioria das requisições continua no nível da baseline. Base: heavy-reports
    com SLOW_DELAY_S=3 (p95 ~2988 ms, média ~3000 ms), fração com +1500 ms.
    """

    # 10% de lentas: p95 no grupo lento, média 0.9*3000 + 0.1*4500 = 3150 ms
    PARTIAL_10 = Window(
        120, 0.0, 4500.0, 2988.0, mean_ms=3150.0, baseline_mean_ms=3000.0)
    # 20% de lentas: média 0.8*3000 + 0.2*4500 = 3300 ms
    PARTIAL_20 = Window(
        120, 0.0, 4500.0, 2988.0, mean_ms=3300.0, baseline_mean_ms=3000.0)
    # 5% de lentas: média 0.95*3000 + 0.05*4500 = 3075 ms
    PARTIAL_05 = Window(
        120, 0.0, 4500.0, 2988.0, mean_ms=3075.0, baseline_mean_ms=3000.0)

    def test_partial_10_percent_b_fires_c_and_a_do_not(self):
        self.assertTrue(is_degraded(self.PARTIAL_10, RULE_B))
        self.assertFalse(is_degraded(self.PARTIAL_10, RULE_C))
        self.assertFalse(is_degraded(self.PARTIAL_10, RULE_A))

    def test_partial_20_percent_b_fires_c_and_a_do_not(self):
        self.assertTrue(is_degraded(self.PARTIAL_20, RULE_B))
        self.assertFalse(is_degraded(self.PARTIAL_20, RULE_C))
        self.assertFalse(is_degraded(self.PARTIAL_20, RULE_A))

    def test_partial_5_percent_is_borderline_for_b(self):
        # com 5% de lentas, o p95 pode cair no grupo lento (dispara) ou no
        # rápido, dependendo da amostra e da resolução do bucket
        slow_p95 = self.PARTIAL_05
        fast_p95 = Window(
            120, 0.0, 3000.0, 2988.0, mean_ms=3075.0, baseline_mean_ms=3000.0)
        self.assertTrue(is_degraded(slow_p95, RULE_B))
        self.assertFalse(is_degraded(fast_p95, RULE_B))
        # a média não muda o suficiente em nenhum dos casos
        self.assertFalse(is_degraded(slow_p95, RULE_C))
        self.assertFalse(is_degraded(fast_p95, RULE_C))

    def test_detector_b_detects_partial_c_stays_healthy(self):
        b = SubsetDetector("a", "heavy-reports", rule=RULE_B)
        c = SubsetDetector("a", "heavy-reports", rule=RULE_C)
        for _ in range(2):
            self.assertIsNone(b.observe(self.PARTIAL_10))
            self.assertIsNone(c.observe(self.PARTIAL_10))
        self.assertEqual(b.observe(self.PARTIAL_10), "detected")
        self.assertIsNone(c.observe(self.PARTIAL_10))
        self.assertEqual(c.state, "healthy")

    def test_dashboard_partial_is_blind_to_all_rules(self):
        # lacuna 2: dashboard com p95 de 1-5 ms; 20% das requisições com +500 ms.
        # p95 ~500 ms e média ~102 ms: piso de 1000 ms e delta de 500 ms cegam
        # as três regras.
        w = Window(140, 0.0, 500.0, 4.0, mean_ms=102.0, baseline_mean_ms=4.0)
        for rule in RULES:
            self.assertFalse(is_degraded(w, rule), rule)


class SubsetDetectorTest(unittest.TestCase):
    def test_detects_after_three_consecutive_degraded_windows(self):
        d = SubsetDetector("a", "heavy-reports")
        self.assertIsNone(d.observe(HIGH_ERR))
        self.assertIsNone(d.observe(HIGH_ERR))
        self.assertEqual(d.observe(HIGH_ERR), "detected")
        self.assertEqual(d.state, "degraded")

    def test_detected_only_once(self):
        d = SubsetDetector("a", "heavy-reports")
        for _ in range(3):
            d.observe(HIGH_ERR)
        self.assertIsNone(d.observe(HIGH_ERR))

    def test_healthy_window_resets_streak(self):
        d = SubsetDetector("a", "heavy-reports")
        d.observe(HIGH_ERR)
        d.observe(HIGH_ERR)
        d.observe(OK)
        d.observe(HIGH_ERR)
        self.assertEqual(d.state, "healthy")
        self.assertIsNone(d.observe(HIGH_ERR))
        self.assertEqual(d.observe(HIGH_ERR), "detected")

    def test_insufficient_sample_does_not_reset_or_advance(self):
        d = SubsetDetector("a", "heavy-reports")
        d.observe(HIGH_ERR)
        d.observe(HIGH_ERR)
        self.assertIsNone(d.observe(LOW_SAMPLE_BAD))
        self.assertEqual(d.degraded_streak, 2)
        self.assertEqual(d.observe(HIGH_ERR), "detected")

    def test_recovers_after_three_healthy_windows(self):
        d = SubsetDetector("a", "heavy-reports")
        for _ in range(3):
            d.observe(HIGH_ERR)
        self.assertIsNone(d.observe(OK))
        self.assertIsNone(d.observe(OK))
        self.assertEqual(d.observe(OK), "recovered")
        self.assertEqual(d.state, "healthy")

    def test_degraded_window_during_recovery_resets_recovery(self):
        d = SubsetDetector("a", "heavy-reports")
        for _ in range(3):
            d.observe(HIGH_ERR)
        d.observe(OK)
        d.observe(OK)
        d.observe(HIGH_ERR)
        self.assertEqual(d.state, "degraded")
        self.assertEqual(d.recovered_streak, 0)

    def test_healthy_traffic_never_emits_events(self):
        d = SubsetDetector("a", "dashboard")
        events = [d.observe(OK) for _ in range(30)]
        self.assertEqual([e for e in events if e], [])


class ClusterGuardTest(unittest.TestCase):
    def test_blocks_when_both_degraded(self):
        a = SubsetDetector("a", "heavy-reports")
        b = SubsetDetector("b", "heavy-reports")
        for _ in range(3):
            a.observe(HIGH_ERR)
            b.observe(HIGH_ERR)
        self.assertTrue(both_clusters_degraded(a, b))

    def test_single_cluster_degraded_is_not_blocked(self):
        a = SubsetDetector("a", "heavy-reports")
        b = SubsetDetector("b", "heavy-reports")
        for _ in range(3):
            a.observe(HIGH_ERR)
        self.assertFalse(both_clusters_degraded(a, b))


if __name__ == "__main__":
    unittest.main()
