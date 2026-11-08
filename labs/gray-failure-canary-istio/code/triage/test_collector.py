import json
import os
import tempfile
import unittest

from collector import code_fingerprint, collect
from detector import Window
from replay import load_samples, replay

START = 1761000000  # múltiplo de 60


class Clock:
    def __init__(self, t):
        self.t = float(t)
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class FakeProm:
    def __init__(self, fail_at=None, empty_at=None, fail_once=None, drop=None):
        self.calls = []
        self.drop = dict(drop or {})  # minuto -> chaves (versão, feature) ausentes
        self.fail_at = set(fail_at or [])
        self.empty_at = set(empty_at or [])
        self.fail_once = set(fail_once or [])

    def _check(self, at):
        self.calls.append(at)
        if at in self.fail_once:
            self.fail_once.discard(at)
            raise ConnectionError("Connection refused")
        if at in self.fail_at:
            raise ConnectionError("Connection refused")

    def windows(self, at=None):
        self._check(at)
        if at in self.empty_at:
            return {}
        w = {("v1", "dashboard"): Window(300, 0.0, 2.0, 0.0, mean_ms=1.0),
             ("v2", "dashboard"): Window(301, 0.0, 2.0, 0.0, mean_ms=1.0),
             ("v1", "heavy-reports"): Window(80, 0.0, 2987.5, 0.0, mean_ms=3049.0),
             ("v2", "heavy-reports"): Window(81, 0.0, 2987.5, 0.0, mean_ms=3050.0)}
        for k in self.drop.get(at, ()):
            w.pop(k)
        return w

    def buckets(self, at=None):
        return {("v1", "dashboard"): {"250": 300.0, "+Inf": 300.0},
                ("v2", "dashboard"): {"250": 301.0, "+Inf": 301.0},
                ("v1", "heavy-reports"): {"2500": 0.0, "3000": 76.0, "+Inf": 80.0},
                ("v2", "heavy-reports"): {"2500": 0.0, "3000": 77.0, "+Inf": 81.0}}

    def p95_by_version(self, at=None):
        return {"v1": 2958.0, "v2": 2960.0}

    def mean_by_version(self, at=None):
        return {"v1": 900.0, "v2": 910.0}


class CollectorBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "c.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def read(self):
        with open(self.out, encoding="utf-8") as f:
            return f.read()

    def rows(self):
        return [json.loads(x) for x in self.read().splitlines() if x.strip()]

    def run_collect(self, prom, minutes=3, clock=None, **kw):
        clock = clock or Clock(START - 10)
        stats = collect(prom, self.out, minutes, start=START, now=clock.now, sleep=clock.sleep, **kw)
        return stats, clock


class AlignmentTest(CollectorBase):
    def test_timestamps_are_minute_aligned_and_queried_at_that_instant(self):
        prom = FakeProm()
        stats, _ = self.run_collect(prom, 3)
        ts = [r["ts"] for r in self.rows()]
        self.assertTrue(all(t.endswith(":00Z") for t in ts), ts)
        self.assertEqual(prom.calls[0], START)
        self.assertEqual(sorted(set(prom.calls)), [START, START + 60, START + 120])
        self.assertEqual(stats.collected, 3)

    def test_sample_has_bucket_vector_and_aggregates(self):
        self.run_collect(FakeProm(), 1)
        r = self.rows()[0]
        heavy = next(w for w in r["windows"] if (w["version"], w["feature"]) == ("v2", "heavy-reports"))
        self.assertEqual(heavy["buckets"], {"2500": 0.0, "3000": 77.0, "+Inf": 81.0})
        self.assertEqual((heavy["n"], heavy["p95_ms"], heavy["mean_ms"]), (81, 2987.5, 3050.0))
        self.assertEqual(r["p95_by_version"], {"v1": 2958.0, "v2": 2960.0})
        self.assertEqual(r["src"], "live")

    def test_waits_for_the_minute_plus_margin_before_querying(self):
        clock = Clock(START - 10)
        self.run_collect(FakeProm(), 2, clock=clock, margin_s=3.0)
        self.assertAlmostEqual(clock.slept[0], 13.0)   # até START + 3 s
        self.assertAlmostEqual(clock.slept[1], 60.0)   # +1 minuto


class IdempotenceTest(CollectorBase):
    def test_second_run_adds_nothing_and_does_not_query(self):
        self.run_collect(FakeProm(), 3)
        before = self.read()
        prom = FakeProm()
        stats, _ = self.run_collect(prom, 3, clock=Clock(START + 500))
        self.assertEqual(self.read(), before)
        self.assertEqual(prom.calls, [])
        self.assertEqual((stats.skipped, stats.collected), (3, 0))

    def test_meta_is_written_once_at_creation(self):
        self.run_collect(FakeProm(), 1, meta={"sigma": 0.1})
        self.run_collect(FakeProm(), 3, clock=Clock(START + 500), meta={"sigma": 0.1})
        metas = [r for r in self.rows() if "meta" in r]
        self.assertEqual(len(metas), 1)
        self.assertEqual(metas[0]["meta"]["sigma"], 0.1)
        self.assertEqual(self.rows()[0].get("meta", {}).get("sigma"), 0.1)  # primeira linha


class GapFillTest(CollectorBase):
    def test_fills_only_the_missing_minutes_without_sleeping(self):
        self.run_collect(FakeProm(), 3)
        rows = self.rows()
        with open(self.out, "w") as f:  # arquivo com o minuto do meio faltando
            for r in (rows[0], rows[2]):
                f.write(json.dumps(r) + "\n")
        prom = FakeProm()
        clock = Clock(START + 10_000)
        stats, _ = self.run_collect(prom, 3, clock=clock)
        self.assertEqual(prom.calls[:1], [START + 60])
        self.assertEqual(set(prom.calls), {START + 60})
        self.assertEqual(clock.slept, [])
        self.assertEqual((stats.collected, stats.skipped), (1, 2))
        self.assertEqual(self.rows()[-1]["src"], "fill")
        # o carregador devolve as três janelas em ordem, apesar do preenchimento no fim
        ld = load_samples(self.out)
        self.assertEqual(len(ld.samples), 3)

    def test_minutes_older_than_retention_are_expired_not_queried(self):
        prom = FakeProm()
        clock = Clock(START + 100 * 3600)
        stats, _ = self.run_collect(prom, 2, clock=clock, retention_s=72 * 3600)
        self.assertEqual(prom.calls, [])
        self.assertEqual(len(stats.expired), 2)
        self.assertEqual(stats.missing, [START, START + 60])
        self.assertFalse(os.path.exists(self.out) and self.rows())


class ErrorTest(CollectorBase):
    def test_error_is_recorded_then_retried_and_filled(self):
        prom = FakeProm(fail_once=[START + 60])
        stats, _ = self.run_collect(prom, 3)
        errs = [r for r in self.rows() if "error" in r]
        self.assertEqual(len(errs), 1)
        self.assertIn("Connection refused", errs[0]["error"])
        self.assertEqual(stats.missing, [])
        ld = load_samples(self.out)
        self.assertEqual((len(ld.samples), ld.errors), (3, 1))

    def test_persistent_error_leaves_the_minute_missing_and_visible(self):
        stats, _ = self.run_collect(FakeProm(fail_at=[START + 60]), 3)
        self.assertEqual(stats.missing, [START + 60])
        errs = [r for r in self.rows() if "error" in r]
        self.assertEqual(len(errs), 2)  # tentativa ao vivo + 1 repetição
        self.assertEqual(len(load_samples(self.out).samples), 2)

    def test_empty_response_is_an_error_not_a_valid_sample(self):
        stats, _ = self.run_collect(FakeProm(empty_at=[START + 60]), 3)
        self.assertEqual(stats.missing, [START + 60])
        self.assertTrue(any("sem dados" in r.get("error", "") for r in self.rows()))

    def test_sample_missing_a_version_or_feature_is_an_error(self):
        for key in (("v1", "dashboard"), ("v2", "dashboard"), ("v1", "heavy-reports"), ("v2", "heavy-reports")):
            self.tearDown()
            self.setUp()
            stats, _ = self.run_collect(FakeProm(drop={START + 60: [key]}), 3)
            self.assertEqual(stats.missing, [START + 60], key)
            errs = [r["error"] for r in self.rows() if "error" in r]
            self.assertTrue(errs and all(f"{key[0]}/{key[1]}" in e for e in errs), (key, errs))
            self.assertEqual(len(load_samples(self.out).samples), 2)

    def test_rerun_after_a_failure_only_retries_the_missing_minute(self):
        self.run_collect(FakeProm(fail_at=[START + 60]), 3)
        prom = FakeProm()
        stats, _ = self.run_collect(prom, 3, clock=Clock(START + 1000))
        self.assertEqual(set(prom.calls), {START + 60})
        self.assertEqual(stats.missing, [])


class IntegrationTest(CollectorBase):
    def test_output_feeds_replay_and_rule_d(self):
        self.run_collect(FakeProm(), 8)
        ld = load_samples(self.out)
        self.assertEqual((len(ld.samples), ld.duplicates, ld.meta), (8, 0, None))
        r = replay(ld.samples, "a", "D", limits={"heavy-reports": 3000}, features=("heavy-reports",))
        self.assertEqual(r.gaps, [])
        self.assertEqual(r.no_bucket_windows, 0)


class SummaryTest(CollectorBase):
    def test_cli_summary_carries_missing_as_epoch_for_the_runner(self):
        from collector import stats_summary
        stats, _ = self.run_collect(FakeProm(fail_at=[START + 60]), 3)
        out = stats_summary(stats)
        self.assertEqual(out["missing_epoch"], [float(START + 60)])
        self.assertEqual(len(out["missing"]), 1)
        self.assertTrue(out["missing"][0].endswith(":00Z"))
        self.assertEqual(json.loads(json.dumps(out))["collected"], 2)

    def test_runner_handle_parses_the_last_json_line(self):
        import runner

        class P:
            def communicate(s):
                return ('aviso solto\n{"collected": 2, "missing_epoch": [1761000060.0]}\n', None)

            def poll(s):
                return 0
        self.assertEqual(runner.RealHandle(P()).wait(), {"collected": 2, "missing": [1761000060.0]})

    def test_runner_handle_without_a_summary_fails_loudly_instead_of_validating_empty_data(self):
        import runner

        class P:
            returncode = -9

            def communicate(s):
                return ("", None)

            def poll(s):
                return -9
        with self.assertRaisesRegex(RuntimeError, "sem resumo"):
            runner.RealHandle(P()).wait()


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_hashes_the_analysis_code(self):
        fp = code_fingerprint()
        for name in ("detector.py", "replay.py", "prom.py", "collector.py", "agent.py"):
            self.assertRegex(fp["files"][name], r"^[0-9a-f]{64}$")
        self.assertIn("git_sha", fp)

    def test_fingerprint_includes_the_runner_and_the_app(self):
        import hashlib
        here = os.path.dirname(os.path.abspath(__file__))
        fp = code_fingerprint()
        for name in ("runner.py", "../app/app_server.py"):
            with open(os.path.join(here, name), "rb") as f:
                self.assertEqual(fp["files"][name], hashlib.sha256(f.read()).hexdigest(), name)


if __name__ == "__main__":
    unittest.main()
