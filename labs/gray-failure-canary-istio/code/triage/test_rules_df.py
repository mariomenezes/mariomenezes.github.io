"""Contrato das regras B_f (piso/delta por feature) e D (fração lenta).

Escrito antes do código. Os valores de z estão calculados à mão:
  n=100/100, lenta 10 -> 20:  p1=.10 p2=.20 pooled=.15  se=sqrt(.15*.85*.02)=.050498  z=1.980
  n=100/100, lenta 10 -> 16:  p1=.10 p2=.16 pooled=.13  se=sqrt(.13*.87*.02)=.047560  z=1.262
"""
import unittest

import detector
from detector import (ALL_RULES, RULES, RULE_A, RULE_B, RULE_BF, RULE_C, RULE_D,
                      SubsetDetector, Window, is_degraded)


def win(p95, base, n=100, err=0.0, **kw):
    return Window(n=n, err_pct=err, p95_ms=p95, baseline_p95_ms=base, **kw)


def dwin(slow, base_slow, n=100, base_n=100, err=0.0):
    return Window(n=n, err_pct=err, p95_ms=0.0, baseline_p95_ms=0.0,
                  slow_n=slow, base_n=base_n, base_slow_n=base_slow)


class RegistryTest(unittest.TestCase):
    def test_original_rules_tuple_is_unchanged(self):
        # mix_test.compare e noise_sim iteram RULES: não pode ganhar regra nova
        self.assertEqual(RULES, (RULE_A, RULE_B, RULE_C))

    def test_all_rules_includes_new_ones(self):
        self.assertEqual(ALL_RULES, (RULE_A, RULE_B, RULE_C, RULE_BF, RULE_D))

    def test_unknown_rule_still_raises(self):
        with self.assertRaises(ValueError):
            is_degraded(win(1, 1), "Z")


class BFTest(unittest.TestCase):
    def test_bf_equals_b_for_features_without_override(self):
        for p95, base in [(4725, 2988), (3300, 2988), (3475, 2975), (900, 500), (1100, 500)]:
            w = win(p95, base)
            self.assertEqual(is_degraded(w, RULE_BF, "heavy-reports"),
                             is_degraded(w, RULE_B, "heavy-reports"), (p95, base))

    def test_bf_without_feature_uses_default_params(self):
        w = win(4725, 2988)
        self.assertTrue(is_degraded(w, RULE_BF))
        self.assertFalse(is_degraded(win(300, 1), RULE_BF))

    def test_dashboard_degradation_below_old_floor_is_detected_by_bf_not_b(self):
        # p95 de falha medido no teste de dashboard parcial: 447 a 909 ms, baseline ~1 ms
        for p95 in (447.0, 909.0):
            w = win(p95, 1.0)
            self.assertFalse(is_degraded(w, RULE_B, "dashboard"), p95)
            self.assertTrue(is_degraded(w, RULE_BF, "dashboard"), p95)

    def test_dashboard_floor_is_strict(self):
        self.assertFalse(is_degraded(win(250.0, 1.0), RULE_BF, "dashboard"))
        self.assertTrue(is_degraded(win(250.1, 1.0), RULE_BF, "dashboard"))

    def test_dashboard_healthy_noise_does_not_fire(self):
        # razão 3,29 observada no controle com latências de 1 a 4 ms (bucket)
        self.assertFalse(is_degraded(win(3.29, 1.0), RULE_BF, "dashboard"))
        self.assertFalse(is_degraded(win(4.8, 0.95), RULE_BF, "dashboard"))

    def test_bf_still_applies_error_rule(self):
        self.assertTrue(is_degraded(win(1.0, 1.0, err=5.01), RULE_BF, "dashboard"))

    def test_subset_detector_passes_its_feature_to_the_rule(self):
        d = SubsetDetector("a", "dashboard", rule=RULE_BF)
        slow = win(500.0, 1.0)
        self.assertIsNone(d.observe(slow))
        self.assertIsNone(d.observe(slow))
        self.assertEqual(d.observe(slow), "detected")
        # a mesma janela em heavy-reports (piso padrão 1000 ms) não degrada
        h = SubsetDetector("a", "heavy-reports", rule=RULE_BF)
        for _ in range(5):
            self.assertIsNone(h.observe(slow))


class RuleDTest(unittest.TestCase):
    def test_clear_increase_fires(self):
        self.assertTrue(is_degraded(dwin(20, 10), RULE_D))  # z = 1,980

    def test_increase_above_delta_but_not_significant_does_not_fire(self):
        # +6 pp (>= 5 pp) mas z = 1,262 < 1,645
        self.assertFalse(is_degraded(dwin(16, 10), RULE_D))

    def test_significant_but_below_delta_does_not_fire(self):
        # +3 pp (.13 contra .10) com amostra enorme: z = 6,65, mas a diferença é < 5 pp
        w = dwin(1300, 1000, n=10000, base_n=10000)
        self.assertFalse(is_degraded(w, RULE_D))

    def test_delta_boundary_is_inclusive(self):
        # exatamente +5 pp (.15 - .10); em float isso dá 0.04999999999999999.
        # A regra precisa tratar o limite como inclusivo apesar do arredondamento.
        self.assertLess(1500 / 10000 - 1000 / 10000, 0.05)  # prova o risco
        w = dwin(1500, 1000, n=10000, base_n=10000)
        self.assertTrue(is_degraded(w, RULE_D))

    def test_decrease_never_fires(self):
        self.assertFalse(is_degraded(dwin(5, 30), RULE_D))

    def test_equal_fractions_never_fire(self):
        self.assertFalse(is_degraded(dwin(40, 40), RULE_D))
        self.assertFalse(is_degraded(dwin(0, 0), RULE_D))
        self.assertFalse(is_degraded(dwin(100, 100), RULE_D))

    def test_unequal_sample_sizes_use_both_ns(self):
        # v2 com 80 requisições e v1 com 200: p2=.25, p1=.10, pooled=.1571
        w = dwin(20, 20, n=80, base_n=200)
        self.assertTrue(is_degraded(w, RULE_D))

    def test_without_bucket_data_it_never_fires(self):
        # amostras antigas (sem vetor de buckets): slow_n=-1 por padrão
        w = Window(n=100, err_pct=0.0, p95_ms=9000.0, baseline_p95_ms=100.0)
        self.assertFalse(is_degraded(w, RULE_D))

    def test_missing_baseline_never_fires(self):
        w = Window(n=100, err_pct=0.0, p95_ms=0.0, baseline_p95_ms=0.0, slow_n=90)
        self.assertFalse(is_degraded(w, RULE_D))

    def test_baseline_below_min_sample_never_fires(self):
        self.assertFalse(is_degraded(dwin(20, 3, base_n=10), RULE_D))

    def test_error_rule_applies(self):
        self.assertTrue(is_degraded(dwin(0, 0, err=6.0), RULE_D))

    def test_p95_does_not_matter(self):
        w = Window(n=100, err_pct=0.0, p95_ms=99999.0, baseline_p95_ms=1.0,
                   slow_n=10, base_n=100, base_slow_n=10)
        self.assertFalse(is_degraded(w, RULE_D))

    def test_parameters_are_module_level_and_provisional(self):
        self.assertEqual(detector.SLOW_FRAC_DELTA, 0.05)
        self.assertAlmostEqual(detector.SLOW_FRAC_Z, 1.645, places=3)

    def test_detector_needs_three_consecutive_windows(self):
        d = SubsetDetector("a", "dashboard", rule=RULE_D)
        w = dwin(25, 5)
        self.assertIsNone(d.observe(w))
        self.assertIsNone(d.observe(w))
        self.assertEqual(d.observe(w), "detected")


class ExplicitRatioTest(unittest.TestCase):
    """A razão relativa pode ser passada por chamada (replay em paralelo, sem global)."""

    def test_is_degraded_uses_the_explicit_ratio(self):
        w = win(3600, 3000)  # 1,2x
        self.assertTrue(is_degraded(w, RULE_B, ratio=1.15))
        self.assertFalse(is_degraded(w, RULE_B, ratio=1.3))
        self.assertFalse(is_degraded(w, RULE_BF, "heavy-reports", ratio=1.3))
        c = win(0, 0, mean_ms=3600.0, baseline_mean_ms=3000.0)
        self.assertTrue(is_degraded(c, RULE_C, ratio=1.15))
        self.assertFalse(is_degraded(c, RULE_C, ratio=1.3))

    def test_none_falls_back_to_the_module_value(self):
        w = win(3600, 3000)
        self.assertEqual(is_degraded(w, RULE_B, ratio=None), is_degraded(w, RULE_B))

    def test_subset_detector_carries_its_ratio(self):
        d = SubsetDetector("a", "heavy-reports", rule=RULE_B, ratio=1.3)
        for _ in range(4):
            self.assertIsNone(d.observe(win(3600, 3000)))


class RuleDWeakBaselineTest(unittest.TestCase):
    """Base da v1 fraca (base_n < 30 ou sem buckets) é janela insuficiente na regra D:
    não avança nem zera as contagens, igual a n < 30."""

    def test_weak_base_does_not_break_the_degraded_streak(self):
        for weak in (dwin(25, 5, base_n=29), dwin(25, -1)):
            d = SubsetDetector("a", "dashboard", rule=RULE_D)
            bad = dwin(25, 5)
            self.assertIsNone(d.observe(bad))
            self.assertIsNone(d.observe(bad))
            self.assertIsNone(d.observe(weak))
            self.assertEqual((d.degraded_streak, d.recovered_streak), (2, 0))
            self.assertEqual(d.observe(bad), "detected")

    def test_weak_base_does_not_advance_recovery(self):
        d = SubsetDetector("a", "dashboard", rule=RULE_D)
        for _ in range(3):
            d.observe(dwin(25, 5))
        self.assertEqual(d.state, "degraded")
        ok = dwin(5, 5)
        for _ in range(detector.WINDOWS_TO_RECOVER - 1):
            self.assertIsNone(d.observe(ok))
        streak = d.recovered_streak
        self.assertIsNone(d.observe(dwin(5, 5, base_n=10)))
        self.assertEqual(d.recovered_streak, streak)
        self.assertEqual(d.state, "degraded")
        self.assertEqual(d.observe(ok), "recovered")

    def test_base_at_min_sample_is_sufficient(self):
        d = SubsetDetector("a", "dashboard", rule=RULE_D)
        d.observe(dwin(25, 0, base_n=detector.MIN_SAMPLE))  # z = 3,05
        self.assertEqual(d.degraded_streak, 1)

    def test_weak_base_masks_the_error_channel_too(self):
        d = SubsetDetector("a", "dashboard", rule=RULE_D)
        self.assertIsNone(d.observe(dwin(0, 0, base_n=10, err=50.0)))
        self.assertEqual((d.degraded_streak, d.recovered_streak), (0, 0))

    def test_other_rules_ignore_the_base_counts(self):
        d = SubsetDetector("a", "heavy-reports", rule=RULE_B)
        d.observe(win(4725, 2988))  # base_n=0, base_slow_n=-1 por padrão
        self.assertEqual(d.degraded_streak, 1)


if __name__ == "__main__":
    unittest.main()
