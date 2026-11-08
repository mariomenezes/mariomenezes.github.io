import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import detector
from replay import (DUP_S, GAP_S, first_detected, load_samples, replay)

T0 = datetime(2026, 10, 23, 22, 5, 13, tzinfo=timezone.utc)


def ts(sec):
    return (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%SZ")


def win(version, feature, n=100, p95=2.0, mean=1.0, err=0.0, buckets=None):
    w = {"version": version, "feature": feature, "n": n, "err_pct": err, "p95_ms": p95, "mean_ms": mean}
    if buckets is not None:
        w["buckets"] = buckets
    return w


def sample(sec, heavy_v2=3000.0, heavy_v1=3000.0, mean_v2=3050.0, mean_v1=3050.0, dash=2.0, buckets=None):
    b1, b2 = (buckets or (None, None))
    return {"ts": ts(sec), "windows": [
        win("v1", "dashboard", p95=dash), win("v2", "dashboard", p95=dash),
        win("v1", "heavy-reports", p95=heavy_v1, mean=mean_v1, buckets=b1),
        win("v2", "heavy-reports", p95=heavy_v2, mean=mean_v2, buckets=b2)],
        "p95_by_version": {}, "mean_by_version": {}}


def series(n, start=0, step=60, **kw):
    return [sample(start + i * step, **kw) for i in range(n)]


def write(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for x in lines:
        f.write((x if isinstance(x, str) else json.dumps(x)) + "\n")
    f.close()
    return f.name


class LoadTest(unittest.TestCase):
    def tearDown(self):
        for p in getattr(self, "paths", []):
            os.unlink(p)

    def load(self, lines):
        p = write(lines)
        self.paths = [p]
        return load_samples(p)

    def test_meta_error_and_blank_lines_are_separated(self):
        ld = self.load([{"meta": {"sigma": 0.1}}, sample(0), {"ts": ts(60), "error": "x"}, "", sample(120)])
        self.assertEqual(len(ld.samples), 2)
        self.assertEqual(ld.meta, {"sigma": 0.1})
        self.assertEqual(ld.errors, 1)

    def test_burst_duplicates_are_dropped_keeping_the_first(self):
        first = sample(0, heavy_v2=111.0)
        dup = [sample(s, heavy_v2=999.0) for s in (1, 2, 3, 10, 29)]
        ld = self.load([first] + dup + [sample(60)])
        self.assertEqual(len(ld.samples), 2)
        self.assertEqual(ld.duplicates, 5)
        self.assertEqual(ld.samples[0]["windows"][3]["p95_ms"], 111.0)

    def test_spacing_at_the_duplicate_threshold_is_kept(self):
        ld = self.load([sample(0), sample(DUP_S)])
        self.assertEqual(len(ld.samples), 2)

    def test_dup_threshold_is_frozen_at_55s(self):
        # janelas increase[1m] a Δ s uma da outra se sobrepõem em 60-Δ s; 55 s limita a
        # sobreposição a 5 s (8 %) e tolera jitter do coletor antigo (passo ~60,3 s)
        self.assertEqual(DUP_S, 55.0)

    def test_overlapping_windows_are_duplicates(self):
        # a 30-54 s, mais da metade a 1/12 da janela é a mesma: não são janelas novas
        for gap in (30, 45, 54):
            ld = self.load([sample(0), sample(gap), sample(60)])
            self.assertEqual((len(ld.samples), ld.duplicates), (2, 1), gap)

    def test_out_of_order_lines_are_sorted_by_time(self):
        # o coletor v2 preenche lacunas anexando minutos antigos no fim do arquivo
        ld = self.load([sample(0), sample(120), sample(60)])
        self.assertEqual([x["ts"] for x in ld.samples], [ts(0), ts(60), ts(120)])

    def test_minute_label_skips_from_clock_drift_are_not_gaps(self):
        # 60,3 s de passo: o rótulo do minuto pula, mas as janelas são consecutivas
        ld = self.load([sample(59.9 + 60.3 * i) for i in range(5)])
        self.assertEqual(len(ld.samples), 5)
        self.assertEqual(ld.duplicates, 0)


class ReplayTest(unittest.TestCase):
    def test_detects_after_three_consecutive_degraded_windows(self):
        res = replay(series(8, heavy_v2=4500.0), "a", rule="B", skip=1)
        self.assertEqual(first_detected(res, "heavy-reports"), 2)
        self.assertEqual(res.n_samples, 7)
        self.assertEqual(res.gaps, [])

    def test_skip_drops_the_first_samples(self):
        s = [sample(0, heavy_v2=4500.0)] + series(5, start=60)
        self.assertIsNone(first_detected(replay(s, "a", skip=1), "heavy-reports"))

    def test_gap_breaks_the_streak(self):
        # 2 ruins, buraco de 3 minutos, 1 ruim: não são 3 consecutivas
        s = [sample(0), sample(60, heavy_v2=4500.0), sample(120, heavy_v2=4500.0),
             sample(300, heavy_v2=4500.0)]
        res = replay(s, "a", rule="B", skip=1)
        self.assertIsNone(first_detected(res, "heavy-reports"))
        self.assertEqual(res.gaps, [2])

    def test_the_same_windows_without_gap_do_detect(self):
        s = [sample(0), sample(60, heavy_v2=4500.0), sample(120, heavy_v2=4500.0),
             sample(180, heavy_v2=4500.0)]
        res = replay(s, "a", rule="B", skip=1)
        self.assertEqual(first_detected(res, "heavy-reports"), 2)

    def test_gap_threshold_is_exclusive(self):
        s = [sample(0), sample(60), sample(60 + GAP_S, heavy_v2=4500.0)]
        self.assertEqual(replay(s, "a", skip=1).gaps, [])
        s = [sample(0), sample(60), sample(60 + GAP_S + 1, heavy_v2=4500.0)]
        self.assertEqual(replay(s, "a", skip=1).gaps, [1])

    def test_burst_duplicates_never_create_consecutive_windows(self):
        # o caso real dos 564 minutos repetidos: 1 janela ruim repetida 5x em 3 s
        bad = [sample(180 + i, heavy_v2=4500.0) for i in range(5)]
        s = [sample(0), sample(60), sample(120)] + bad
        p = write(s)
        try:
            ld = load_samples(p)
        finally:
            os.unlink(p)
        res = replay(ld.samples, "a", rule="B", skip=1)
        self.assertEqual(ld.duplicates, 4)
        self.assertIsNone(first_detected(res, "heavy-reports"))

    def test_rule_a_misses_what_rule_b_catches(self):
        s = series(8, heavy_v2=4500.0)
        self.assertIsNone(first_detected(replay(s, "a", rule="A"), "heavy-reports"))
        self.assertEqual(first_detected(replay(s, "a", rule="B"), "heavy-reports"), 2)

    def test_isolation_other_feature_stays_silent(self):
        res = replay(series(8, heavy_v2=4500.0), "a", rule="B")
        self.assertIsNone(first_detected(res, "dashboard"))

    def test_rule_c_comes_from_the_watch_channel(self):
        res = replay(series(8, heavy_v2=4500.0, mean_v2=4400.0), "a", rule="A")
        kinds = [(f, k) for _, f, k in res.watch]
        self.assertIn(("heavy-reports", "c_detected"), kinds)
        self.assertIsNone(first_detected(res, "heavy-reports"))

    def test_recovery_is_reported(self):
        s = series(5, heavy_v2=4500.0) + series(5, start=300)
        kinds = [k for _, f, k in replay(s, "a", rule="B", skip=0).events if f == "heavy-reports"]
        self.assertEqual(kinds, ["detected", "recovered"])

    def test_unknown_rule_raises(self):
        with self.assertRaises(ValueError):
            replay(series(3), "a", rule="Z")


class RatioTest(unittest.TestCase):
    def test_ratio_override_changes_the_decision_and_is_restored(self):
        s = series(8, heavy_v2=3600.0)  # 1,2x: B(1,15) detecta, B(1,3) não
        orig = detector.RELATIVE_RATIO_LIMIT
        self.assertEqual(first_detected(replay(s, "a", rule="B", ratio=1.15), "heavy-reports"), 2)
        self.assertIsNone(first_detected(replay(s, "a", rule="B", ratio=1.3), "heavy-reports"))
        self.assertEqual(detector.RELATIVE_RATIO_LIMIT, orig)

    def test_ratio_is_passed_explicitly_and_never_touches_the_global(self):
        s = series(8, heavy_v2=3600.0)
        orig = detector.RELATIVE_RATIO_LIMIT
        seen = []
        real = detector._relative_slow

        def spy(*a, **kw):
            seen.append(detector.RELATIVE_RATIO_LIMIT)
            return real(*a, **kw)
        detector._relative_slow = spy
        try:
            replay(s, "a", rule="B", ratio=1.3)
        finally:
            detector._relative_slow = real
        self.assertTrue(seen)
        self.assertEqual(set(seen), {orig})

    def test_result_reports_the_ratio_used(self):
        s = series(3)
        self.assertEqual(replay(s, "a", rule="B", ratio=1.3).ratio, 1.3)
        self.assertEqual(replay(s, "a", rule="B").ratio, detector.RELATIVE_RATIO_LIMIT)

    def test_concurrent_replays_with_different_ratios_do_not_interfere(self):
        import threading
        s = series(40, heavy_v2=3600.0)
        out = {}

        def run(r):
            for _ in range(20):
                out.setdefault(r, set()).add(first_detected(replay(s, "a", rule="B", ratio=r), "heavy-reports"))
        ts = [threading.Thread(target=run, args=(r,)) for r in (1.15, 1.3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(out, {1.15: {2}, 1.3: {None}})


def buckets(total, over_250):
    return {"100": total * 0.5, "250": total - over_250, "500": total * 0.99, "+Inf": float(total)}


L250 = {"heavy-reports": 250, "dashboard": 250}


class RuleDReplayTest(unittest.TestCase):
    def test_d_with_a_feature_missing_from_limits_raises_listing_it(self):
        with self.assertRaises(ValueError) as cm:
            replay(self.s_with_buckets(8, 30), "a", rule="D", limits={"heavy-reports": 250})
        self.assertIn("dashboard", str(cm.exception))
        self.assertNotIn("heavy-reports", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            replay(self.s_with_buckets(8, 30), "a", rule="D", limits={"outra": 250})
        self.assertIn("dashboard", str(cm.exception))
        self.assertIn("heavy-reports", str(cm.exception))

    def test_d_limits_only_need_the_replayed_features(self):
        res = replay(self.s_with_buckets(8, 30), "a", rule="D", limits={"heavy-reports": 250},
                     features=("heavy-reports",))
        self.assertEqual(first_detected(res, "heavy-reports"), 2)

    def test_partial_limits_are_fine_for_other_rules(self):
        replay(self.s_with_buckets(8, 30), "a", rule="B", limits={"heavy-reports": 250})

    def s_with_buckets(self, n, v2_over, v1_over=2, count=8):
        return [sample(60 * i, buckets=(buckets(100, v1_over), buckets(100, v2_over))) for i in range(count)]

    def test_d_detects_a_slow_fraction_with_limits(self):
        res = replay(self.s_with_buckets(8, v2_over=30), "a", rule="D", limits=L250)
        self.assertEqual(first_detected(res, "heavy-reports"), 2)
        self.assertIsNone(first_detected(res, "dashboard"))

    def test_d_requires_limits(self):
        with self.assertRaises(ValueError):
            replay(self.s_with_buckets(8, 30), "a", rule="D")

    def test_d_on_samples_without_buckets_is_silent_and_counted(self):
        res = replay(series(8, heavy_v2=9000.0), "a", rule="D", limits=L250)
        self.assertIsNone(first_detected(res, "heavy-reports"))
        self.assertGreater(res.no_bucket_windows, 0)

    def test_limit_not_a_bucket_edge_raises(self):
        with self.assertRaises(KeyError):
            replay(self.s_with_buckets(8, 30), "a", rule="D", limits={**L250, "heavy-reports": 300})

    def test_d_takes_n_from_the_bucket_total_not_from_requests(self):
        # n de istio_requests_total = 100 nas duas; o histograma da v2 tem 600 (+Inf).
        # Fração certa: 30/600 = 5 % contra 2 % (+3 pp < 5 pp): não dispara.
        # Com n = 100 seria 30 % e dispararia.
        s = [sample(60 * i, buckets=(buckets(100, 2), buckets(600, 30))) for i in range(8)]
        res = replay(s, "a", rule="D", limits=L250)
        self.assertIsNone(first_detected(res, "heavy-reports"))

    def test_d_takes_base_n_from_the_v1_bucket_total(self):
        # v1 com 100 requisições mas só 20 no histograma: base fraca, D não avalia
        s = [sample(60 * i, buckets=(buckets(20, 0), buckets(100, 40))) for i in range(8)]
        res = replay(s, "a", rule="D", limits=L250)
        self.assertIsNone(first_detected(res, "heavy-reports"))
        s = [sample(60 * i, buckets=(buckets(30, 0), buckets(100, 40))) for i in range(8)]
        res = replay(s, "a", rule="D", limits=L250)
        self.assertEqual(first_detected(res, "heavy-reports"), 2)

    def test_bucket_total_does_not_replace_n_for_other_rules(self):
        # B com limits: o histograma com 10 requisições não torna a janela insuficiente
        s = [sample(60 * i, heavy_v2=4500.0, buckets=(buckets(10, 0), buckets(10, 5)))
             for i in range(8)]
        res = replay(s, "a", rule="B", limits={"heavy-reports": 250})
        self.assertEqual(first_detected(res, "heavy-reports"), 2)

    def test_p95_rules_ignore_the_bucket_vector(self):
        res = replay(self.s_with_buckets(8, 30), "a", rule="B")
        self.assertIsNone(first_detected(res, "heavy-reports"))


if __name__ == "__main__":
    unittest.main()
