"""Contrato do analisador da comparação com o Flagger real (v6), escrito antes dos dados."""
import json
import os
import tempfile
import unittest

import eval_flagger as ef
from test_market_emul import (DASH_BAD, HEAVY_OK, T0, run as make_run, sample)


class DecisionTest(unittest.TestCase):
    def test_h6a_blind_on_the_dashboard_allows_at_most_two_rollbacks_in_thirty(self):
        self.assertTrue(ef.h6a_pass(0, 30))
        self.assertTrue(ef.h6a_pass(2, 30))   # UB95 0,195
        self.assertFalse(ef.h6a_pass(3, 30))  # UB95 0,239
        self.assertFalse(ef.h6a_pass(0, 0))

    def test_h6b_heavy_needs_the_lower_bound_at_080(self):
        self.assertTrue(ef.h6b_pass(28, 30))
        self.assertFalse(ef.h6b_pass(27, 30))

    def test_h6c_control_false_alarm_upper_bound_below_ten_percent(self):
        self.assertTrue(ef.h6c_pass(0, 30))
        self.assertTrue(ef.h6c_pass(0, 29))
        self.assertFalse(ef.h6c_pass(0, 28))
        self.assertFalse(ef.h6c_pass(1, 30))

    def test_h8_agreement_needs_28_of_30(self):
        self.assertTrue(ef.h8_pass(28, 30))
        self.assertFalse(ef.h8_pass(27, 30))

    def test_flagger_hit_window_is_t_on_to_t_off_plus_60(self):
        t_on, t_off = 1000.0, 1480.0
        self.assertFalse(ef.flagger_hit("Failed", t_on, t_on, t_off))
        self.assertTrue(ef.flagger_hit("Failed", t_on + 1, t_on, t_off))
        self.assertTrue(ef.flagger_hit("Failed", t_off + 60, t_on, t_off))
        self.assertFalse(ef.flagger_hit("Failed", t_off + 61, t_on, t_off))
        self.assertFalse(ef.flagger_hit("Succeeded", None, t_on, t_off))
        self.assertFalse(ef.flagger_hit("Failed", None, t_on, t_off))


def with_p95(samples):
    """p95 por janela como o coletor grava: heavy-reports 3000 ms, 4500 ms na v2 com cauda ruim."""
    for s in samples:
        for w in s["windows"]:
            if w["feature"] == "heavy-reports":
                w["p95_ms"] = 4500.0 if w["version"] == "v2" and w["buckets"]["3750"] == 0 else 3000.0
    return samples


def write(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


class AnalyzeTest(unittest.TestCase):
    """Dois clusters sintéticos. Dashboard 10%: o Flagger não vê em a, 'reverte' em b."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = self.tmp.name
        self.plan = os.path.join(self.out, "plan.json")
        raw = {"name": "t", "namespace": "flagger-lab", "out_dir": self.out, "prereg": "x",
               "clusters": {"a": {"context": "x", "prom_port": 1}, "b": {"context": "y", "prom_port": 2}},
               "scenarios": [
                   {"id": "dash10", "kind": "fault", "feature": "dashboard",
                    "params": {"fast_delay_fraction": 0.1, "fast_delay_s": 0.5}, "reps": 1,
                    "baseline_min": 3, "fault_min": 8, "after_min": 3},
                   {"id": "heavy10", "kind": "fault", "feature": "heavy-reports",
                    "params": {"slow_extra_fraction": 0.1, "slow_extra_s": 1.5}, "reps": 1,
                    "baseline_min": 3, "fault_min": 8, "after_min": 3},
                   {"id": "ctrl", "kind": "control", "reps": 1, "baseline_min": 3, "fault_min": 8, "after_min": 3}]}
        with open(self.plan, "w") as f:
            json.dump(raw, f)
        for c, phase in (("a", "Succeeded"), ("b", "Failed")):
            d = os.path.join(self.out, c)
            os.makedirs(d)
            runs = []
            s, on, off = make_run(fault_d=DASH_BAD)
            write(os.path.join(d, "dash10-r01-a1.jsonl"), s)
            runs.append({"cluster": c, "scenario": "dash10", "kind": "fault", "rep": 1, "attempt": 1, "status": "ok",
                         "t0": T0, "t_on": on, "t_off": off, "file": "dash10-r01-a1.jsonl",
                         "flagger_phase": phase, "flagger_failed_at": (on + 300) if phase == "Failed" else None})
            s, on, off = make_run(fault_h={"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70})
            write(os.path.join(d, "heavy10-r01-a1.jsonl"), with_p95(s))
            runs.append({"cluster": c, "scenario": "heavy10", "kind": "fault", "rep": 1, "attempt": 1, "status": "ok",
                         "t0": T0, "t_on": on, "t_off": off, "file": "heavy10-r01-a1.jsonl",
                         "flagger_phase": "Failed", "flagger_failed_at": on + 240})
            write(os.path.join(d, "ctrl-r01-a1.jsonl"), [sample(T0 + 60 * i) for i in range(14)])
            runs.append({"cluster": c, "scenario": "ctrl", "kind": "control", "rep": 1, "attempt": 1, "status": "ok",
                         "t0": T0, "t_on": T0 + 180, "t_off": T0 + 660, "file": "ctrl-r01-a1.jsonl",
                         "flagger_phase": "Succeeded", "flagger_failed_at": None})
            runs.append({"cluster": c, "scenario": "ctrl", "kind": "control", "rep": 9, "attempt": 1,
                         "status": "discarded", "reason": "x"})
            write(os.path.join(d, "runs.jsonl"), runs)
        self.r = ef.analyze(self.out, self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_and_discards_are_ignored(self):
        s = self.r["scenarios"]
        self.assertEqual((s["dash10"]["flagger"]["hits"], s["dash10"]["flagger"]["n"]), (1, 2))
        self.assertEqual((s["heavy10"]["flagger"]["hits"], s["heavy10"]["flagger"]["n"]), (2, 2))
        self.assertEqual(self.r["control"]["flagger"], {"false_alarms": 0, "runs": 2})

    def test_our_detector_and_the_emulations_run_on_the_same_samples(self):
        d = self.r["scenarios"]["dash10"]
        self.assertEqual(d["ours"]["hits"], 2)           # regra D no dashboard
        self.assertEqual(d["emul_flagger_rel"]["hits"], 0)
        self.assertEqual(d["emul_agg_b"]["hits"], 0)
        h = self.r["scenarios"]["heavy10"]
        self.assertEqual((h["ours"]["hits"], h["emul_flagger_rel"]["hits"]), (2, 2))

    def test_agreement_between_the_real_flagger_and_the_emulation(self):
        # dash10: real = [não, sim], emulado = [não, não] -> concordam em 1 de 2
        self.assertEqual(self.r["scenarios"]["dash10"]["agreement"], {"agree": 1, "n": 2})
        self.assertEqual(self.r["scenarios"]["heavy10"]["agreement"], {"agree": 2, "n": 2})

    def test_mcnemar_pairs_by_cluster_and_rep(self):
        h7 = self.r["h7"]
        # dash10: nosso detector acertou os 2; o Flagger só 1 -> b=1 (só nós), c=0
        self.assertEqual((h7["dash10"]["b"], h7["dash10"]["c"]), (1, 0))
        self.assertAlmostEqual(h7["dash10"]["p"], 0.5)
        self.assertEqual((h7["heavy10"]["b"], h7["heavy10"]["c"]), (0, 0))
        self.assertIn("p_holm", h7["dash10"])

    def test_false_alarm_of_our_detector_and_emulations_in_the_control(self):
        c = self.r["control"]
        self.assertEqual(c["ours"], {"false_alarms": 0, "runs": 2})
        self.assertEqual(c["emul_flagger_rel"], {"false_alarms": 0, "runs": 2})

    def test_render_mentions_every_hypothesis(self):
        md = ef.render(self.r)
        for k in ("H6a", "H6b", "H6c", "H7", "H8"):
            self.assertIn(k, md)


BAD = {"1": 0, "250": 0, "3000": 0, "3750": 0, "5000": 0, "+Inf": 70}


class FalseAlarmTest(unittest.TestCase):
    """Um cluster. Padrão ruim em 5 minutos NÃO consecutivos: só o Flagger (falhas acumuladas) reverte;
    3 janelas seguidas ruins: nosso detector e agg_b disparam."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "a")
        os.makedirs(d)
        raw = {"name": "t", "namespace": "flagger-lab", "out_dir": self.tmp.name, "prereg": "x",
               "clusters": {"a": {"context": "x", "prom_port": 1}},
               "scenarios": [{"id": "heavy10", "kind": "fault", "feature": "heavy-reports",
                              "params": {"slow_extra_fraction": 0.1, "slow_extra_s": 1.5}, "reps": 1,
                              "baseline_min": 3, "fault_min": 8, "after_min": 3},
                             {"id": "ctrl", "kind": "control", "reps": 2, "baseline_min": 3, "fault_min": 8,
                              "after_min": 3}]}
        self.plan = os.path.join(self.tmp.name, "plan.json")
        with open(self.plan, "w") as f:
            json.dump(raw, f)
        nonconsec = with_p95([sample(T0 + 60 * i, h2=BAD if i in (4, 6, 8, 10, 11) else HEAVY_OK) for i in range(14)])
        run3 = with_p95([sample(T0 + 60 * i, h2=BAD if i in (5, 6, 7) else HEAVY_OK) for i in range(14)])
        write(os.path.join(d, "h.jsonl"), nonconsec)
        write(os.path.join(d, "c1.jsonl"), nonconsec)
        write(os.path.join(d, "c2.jsonl"), run3)
        on, off = T0 + 180, T0 + 660
        base = {"cluster": "a", "attempt": 1, "status": "ok", "t0": T0, "t_on": on, "t_off": off}
        write(os.path.join(d, "runs.jsonl"), [
            {**base, "scenario": "heavy10", "kind": "fault", "rep": 1, "file": "h.jsonl",
             "flagger_phase": "Failed", "flagger_failed_at": on + 300},
            {**base, "scenario": "ctrl", "kind": "control", "rep": 1, "file": "c1.jsonl",
             "flagger_phase": "Failed", "flagger_failed_at": on + 300},
            {**base, "scenario": "ctrl", "kind": "control", "rep": 2, "file": "c2.jsonl",
             "flagger_phase": "Succeeded", "flagger_failed_at": None}])
        self.r = ef.analyze(self.tmp.name, self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def test_control_counts_each_method_separately(self):
        c = self.r["control"]
        self.assertEqual(c["flagger"], {"false_alarms": 1, "runs": 2})
        self.assertEqual(c["emul_flagger_rel"], {"false_alarms": 1, "runs": 2})  # só as 5 acumuladas
        self.assertEqual(c["emul_agg_b"], {"false_alarms": 1, "runs": 2})        # só as 3 seguidas
        self.assertEqual(c["ours"], {"false_alarms": 1, "runs": 2})              # só as 3 seguidas

    def test_agreement_compares_the_real_flagger_with_flagger_rel_not_agg_b(self):
        h = self.r["scenarios"]["heavy10"]
        self.assertEqual(h["emul_flagger_rel"]["hits"], 1)
        self.assertEqual(h["emul_agg_b"]["hits"], 0)
        self.assertEqual(h["agreement"], {"agree": 1, "n": 1})


if __name__ == "__main__":
    unittest.main()
