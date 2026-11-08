"""Contrato do runner. O cluster é emulado: o 'kubectl exec' do admin é respondido pelo
FaultState real do app_server.py com relógio falso, então prazo e histórico se comportam
como no pod. Nenhum teste fala com cluster, Prometheus ou relógio de verdade."""
import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from app_server import FaultState, parse_fault  # noqa: E402

import runner  # noqa: E402
from runner import (Deps, KubeError, PlanError, PreflightError, load_plan, validate_plan)

T0 = 1_761_000_000.0  # múltiplo de 60
ZERO = {"slow_extra_fraction": 0.0, "slow_extra_s": 0.0, "fast_delay_fraction": 0.0, "fast_delay_s": 0.0}


class Clock:
    def __init__(self, t=T0 + 5):
        self.t = float(t)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class FakeCluster:
    """Cluster emulado. `kube(ctx)` devolve o objeto que o runner usa."""

    def __init__(self, clock, heavy="0.3"):
        self.clock = clock
        self.nodes_ready = True
        self.log = []  # (t, verbo, detalhe) para checar ordem
        self.deploys = {
            "app-service-v1": {"env": {"SLOW_DELAY_S": "3"}, "replicas": 1, "ready": 1},
            "app-service-v2": {"env": {"SLOW_DELAY_S": "3", "FAST_ERROR_RATE": "0", **{k.upper(): "0" for k in ZERO}},
                               "replicas": 1, "ready": 1},
            "probe-generator": {"env": {"HEAVY_RATIO": heavy, "PROBE_INTERVAL": "1", "WORKERS": "8"},
                                "replicas": 2, "ready": 2},
            "triage-agent": {"env": {}, "replicas": 0, "ready": 0},
        }
        self.admin = {"v1": FaultState(ZERO, clock=clock.now), "v2": FaultState(ZERO, clock=clock.now)}
        self.exec_fail_after_put = False

    def env(self, name):
        return dict(self.deploys[name]["env"])

    def run(self, *a):
        a = list(a)
        t = self.clock.now()
        if a[:2] == ["get", "nodes"]:
            st = "True" if self.nodes_ready else "False"
            return json.dumps({"items": [{"status": {"conditions": [{"type": "Ready", "status": st}]}}]})
        if a[:2] == ["get", "deploy"]:
            d = self.deploys[a[2]]
            return json.dumps({"spec": {"replicas": d["replicas"], "template": {"spec": {"containers": [
                {"name": "app", "env": [{"name": k, "value": v} for k, v in d["env"].items()]}]}}},
                "status": {"readyReplicas": d["ready"]}})
        if a[:2] == ["set", "env"]:
            name = a[2].split("/", 1)[1]
            for kv in a[3:]:
                if kv.endswith("-"):
                    self.deploys[name]["env"].pop(kv[:-1], None)
                else:
                    k, v = kv.split("=", 1)
                    self.deploys[name]["env"][k] = v
            self.log.append((t, "set_env", name, tuple(a[3:])))
            return ""
        if a[:2] == ["rollout", "status"]:
            self.log.append((t, "rollout", a[2]))
            return "ok"
        if a[0] == "exec":
            return self._exec(a, t)
        raise AssertionError(f"comando inesperado: {a}")

    def _exec(self, a, t):
        ver = a[1].split("-")[-1]
        i = a.index("--")
        method, raw = a[i + 4], a[i + 5]
        st = self.admin[ver]
        if method == "GET":
            return json.dumps(st.snapshot())
        if method == "DELETE":
            st.clear()
            self.log.append((t, "admin_delete", ver))
            return json.dumps(st.snapshot())
        params, ttl = parse_fault(json.loads(raw))
        if any(params.values()):
            st.set(params, ttl)
            self.log.append((t, "admin_put", ver, ttl))
            if self.exec_fail_after_put:
                st.clear()  # emula divergência: o estado lido de volta não é o pedido
        else:
            st.clear()
        return json.dumps(st.snapshot())


class FakeKube:
    def __init__(self, cluster):
        self.c = cluster

    def run(self, *a, **kw):
        return self.c.run(*a)


class FakeHandle:
    def __init__(self, parent, minutes, start):
        self.parent, self.minutes, self.start = parent, minutes, start

    def wait(self):
        self.parent.waited.append(self.start)
        miss = [self.start + o for o in self.parent.missing_offsets]
        return {"collected": self.minutes - len(miss), "missing": miss}

    def stop(self):
        self.parent.stopped.append(self.start)


class FakeCollector:
    def __init__(self):
        self.started, self.waited, self.stopped = [], [], []
        self.missing_offsets = []  # segundos depois do início da coleta (relativo: vale em toda tentativa)

    def start(self, cluster, out_path, minutes, start, meta):
        self.started.append({"cluster": cluster, "out": out_path, "minutes": minutes, "start": start, "meta": meta})
        with open(out_path, "w") as f:
            f.write(json.dumps({"meta": meta}) + "\n")
        return FakeHandle(self, minutes, start)


def make_plan(**over):
    p = {
        "name": "t", "namespace": "lab-apps", "out_dir": "OUT", "prereg": "v4-test",
        "clusters": {"a": {"context": "home/cluster-a", "prom_port": 9151, "heavy_ratio_original": "0.3"}},
        "sigma": None,
        "scenarios": [{"id": "heavy20", "kind": "fault", "feature": "heavy-reports", "reps": 2,
                       "params": {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5},
                       "baseline_min": 3, "fault_min": 8, "after_min": 3}],
    }
    p.update(over)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "out")
        self.cdir = os.path.join(self.out, "a")  # um diretório por cluster
        self.clock = Clock()
        self.cl = FakeCluster(self.clock)
        self.coll = FakeCollector()
        self.prom = {"retention_s": 72 * 3600, "up": True}
        self.disk_free = 50 * 1024 ** 3

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def read(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def plan(self, **over):
        raw = make_plan(**over)
        raw["out_dir"] = self.out
        return validate_plan(raw)

    def deps(self):
        return Deps(kube=lambda ctx: FakeKube(self.cl), now=self.clock.now, sleep=self.clock.sleep,
                    start_collector=self.coll.start, prom_check=lambda cluster: dict(self.prom),
                    disk_free=lambda path: self.disk_free, log=lambda *a: None)

    def block(self, plan=None, cluster="a"):
        return runner.run_block(plan or self.plan(), cluster, self.deps())

    def runs(self):
        p = os.path.join(self.cdir, "runs.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]


class PlanTest(unittest.TestCase):
    def test_valid_plan_loads(self):
        p = validate_plan(make_plan())
        self.assertEqual(p.scenarios[0].id, "heavy20")
        self.assertEqual(len(p.sha256), 64)

    def test_hash_is_stable_and_changes_with_content(self):
        a, b = validate_plan(make_plan()), validate_plan(make_plan())
        self.assertEqual(a.sha256, b.sha256)
        self.assertNotEqual(a.sha256, validate_plan(make_plan(name="outro")).sha256)

    def test_rejects_invalid_plans(self):
        bad = [
            make_plan(clusters={}),
            make_plan(sigma=-0.1),
            make_plan(scenarios=[]),
            make_plan(scenarios=[{"id": "x", "kind": "weird"}]),
            make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "heavy-reports", "reps": 0,
                                  "params": {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5},
                                  "baseline_min": 3, "fault_min": 8, "after_min": 3}]),
            make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "heavy-reports", "reps": 1,
                                  "params": {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5, "nope": 1},
                                  "baseline_min": 3, "fault_min": 8, "after_min": 3}]),
            make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "dashboard", "reps": 1,
                                  "params": {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5},
                                  "baseline_min": 3, "fault_min": 8, "after_min": 3}]),  # parâmetro de outra feature
            make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "heavy-reports", "reps": 1,
                                  "params": {"slow_extra_fraction": 0.0, "slow_extra_s": 0.0},
                                  "baseline_min": 3, "fault_min": 8, "after_min": 3}]),  # falha vazia
            make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "heavy-reports", "reps": 1,
                                  "params": {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5},
                                  "baseline_min": 0, "fault_min": 8, "after_min": 3}]),
            make_plan(scenarios=[{"id": "x", "kind": "control", "minutes": 0}]),
            make_plan(scenarios=[{"id": "d", "kind": "control", "minutes": 5},
                                 {"id": "d", "kind": "control", "minutes": 5}]),  # id repetido
        ]
        for raw in bad:
            with self.assertRaises(PlanError, msg=json.dumps(raw)[:120]):
                validate_plan(raw)

    def test_discard_constants_enter_the_plan_hash(self):
        base = validate_plan(make_plan()).sha256
        for name, value in (("TOLERANCE_S", 11), ("SETTLE_S", 76), ("MAX_MISSING_IN_FAULT", 3),
                            ("MAX_DISCARDS", 4), ("FAULT_HEAVY_RATIO", "0.4")):
            old = getattr(runner, name)
            setattr(runner, name, value)
            try:
                self.assertNotEqual(validate_plan(make_plan()).sha256, base, name)
            finally:
                setattr(runner, name, old)
        self.assertEqual(validate_plan(make_plan()).sha256, base)

    def test_relative_out_dir_is_resolved_from_the_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            raw = make_plan(out_dir="triage/results/x")
            path = os.path.join(d, "p.json")
            with open(path, "w") as f:
                json.dump(raw, f)
            cwd = os.getcwd()
            os.chdir(d)
            try:
                plan = load_plan(path)
            finally:
                os.chdir(cwd)
        repo = os.path.dirname(os.path.dirname(os.path.abspath(runner.__file__)))
        self.assertEqual(plan.out_dir, os.path.join(repo, "triage", "results", "x"))
        self.assertEqual(plan.sha256, validate_plan(make_plan(out_dir="/abs")).sha256)  # out_dir fora do hash

    def test_unknown_top_level_key_is_rejected(self):
        with self.assertRaises(PlanError):
            validate_plan(make_plan(surprise=1))

    def test_load_plan_reads_a_json_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(make_plan(), f)
        try:
            self.assertEqual(load_plan(f.name).name, "t")
        finally:
            os.unlink(f.name)

    def test_summary_gives_durations_without_touching_anything(self):
        s = runner.summarize(validate_plan(make_plan()), "a")
        # 2 execuções de (3+8+3) min + a espera de alinhamento; pelo menos 28 min
        self.assertGreaterEqual(s["total_min"], 28)
        self.assertEqual(s["runs"], 2)


class PreflightTest(Base):
    def check(self, mutate, fragment, **plan_over):
        mutate()
        with self.assertRaises(PreflightError) as cm:
            self.block(self.plan(**plan_over))
        self.assertIn(fragment, str(cm.exception))
        self.assertEqual(self.cl.log, [], "nada pode ser alterado quando o pré-voo falha")

    def test_happy_path_passes(self):
        self.block()

    def test_node_not_ready(self):
        self.check(lambda: setattr(self.cl, "nodes_ready", False), "nó")

    def test_v1_with_partial_injection_variable(self):
        self.check(lambda: self.cl.deploys["app-service-v1"]["env"].update(SLOW_EXTRA_FRACTION="0.1"), "v1")

    def test_v2_with_leftover_fault_in_env(self):
        self.check(lambda: self.cl.deploys["app-service-v2"]["env"].update(SLOW_EXTRA_FRACTION="0.2"), "v2")

    def test_wrong_slow_delay(self):
        self.check(lambda: self.cl.deploys["app-service-v2"]["env"].update(SLOW_DELAY_S="8"), "SLOW_DELAY_S")

    def test_error_injection_left_on(self):
        self.check(lambda: self.cl.deploys["app-service-v2"]["env"].update(FAST_ERROR_RATE="0.2"), "FAST_ERROR_RATE")

    def test_heavy_ratio_differs_from_the_plan(self):
        self.check(lambda: self.cl.deploys["probe-generator"]["env"].update(HEAVY_RATIO="0.5"), "HEAVY_RATIO")

    def test_probe_settings_changed(self):
        self.check(lambda: self.cl.deploys["probe-generator"]["env"].update(WORKERS="4"), "WORKERS")

    def test_triage_agent_running(self):
        def f():
            self.cl.deploys["triage-agent"]["replicas"] = 1
        self.check(f, "triage-agent")

    def test_deployment_not_ready(self):
        def f():
            self.cl.deploys["app-service-v2"]["ready"] = 0
        self.check(f, "app-service-v2")

    def test_admin_already_active(self):
        self.check(lambda: self.cl.admin["v2"].set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 600), "admin")

    def test_sigma_must_match_on_both_versions(self):
        self.cl.deploys["app-service-v1"]["env"]["SLOW_JITTER_SIGMA"] = "0.1"
        with self.assertRaises(PreflightError) as cm:
            self.block(self.plan(sigma=0.1))
        self.assertIn("SLOW_JITTER_SIGMA", str(cm.exception))

    def test_sigma_present_when_plan_has_none(self):
        self.check(lambda: self.cl.deploys["app-service-v1"]["env"].update(SLOW_JITTER_SIGMA="0.1"),
                   "SLOW_JITTER_SIGMA")

    def test_retention_too_short(self):
        self.check(lambda: self.prom.update(retention_s=12 * 3600), "retenção")

    def test_prometheus_down(self):
        self.check(lambda: self.prom.update(up=False), "Prometheus")

    def test_low_disk(self):
        self.check(lambda: setattr(self, "disk_free", 100 * 1024 ** 2), "disco")

    def test_lock_held_by_another_runner(self):
        os.makedirs(self.cdir)
        with open(os.path.join(self.cdir, ".lock-a"), "w") as f:
            f.write(str(os.getpid()))  # pid vivo: este processo
        with self.assertRaises(PreflightError) as cm:
            self.block()
        self.assertIn("lock", str(cm.exception))

    def test_stale_lock_from_a_dead_pid_is_taken_over(self):
        os.makedirs(self.cdir)
        with open(os.path.join(self.cdir, ".lock-a"), "w") as f:
            f.write("999999999")
        self.block()

    def test_report_lists_every_failed_check_not_just_the_first(self):
        self.cl.nodes_ready = False
        self.prom["up"] = False
        with self.assertRaises(PreflightError) as cm:
            self.block()
        self.assertIn("nó", str(cm.exception))
        self.assertIn("Prometheus", str(cm.exception))


class FaultRunTest(Base):
    def test_timeline_and_ground_truth(self):
        self.block()
        runs = self.runs()
        self.assertEqual([(r["status"], r["rep"]) for r in runs], [("ok", 1), ("ok", 2)])
        r = runs[0]
        # fora o alinhamento, a falha dura exatamente fault_min minutos
        self.assertEqual(r["t_off"] - r["t_on"], 8 * 60)
        self.assertEqual(r["t_on"] - r["t0"], 3 * 60)
        self.assertEqual(r["t0"] % 60, 0)
        self.assertEqual(r["expired"], False)
        self.assertEqual(r["params"], {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5})

    def test_collector_covers_baseline_fault_and_after(self):
        self.block()
        c = self.coll.started[0]
        self.assertEqual(c["minutes"], 3 + 8 + 3)
        self.assertEqual(c["start"] % 60, 0)
        self.assertEqual(c["meta"]["scenario"], "heavy20")
        self.assertEqual(c["meta"]["cluster"], "a")
        self.assertEqual(c["meta"]["rep"], 1)
        self.assertEqual(c["meta"]["plan_sha256"], self.plan().sha256)
        self.assertEqual(c["meta"]["prereg"], "v4-test")
        self.assertEqual(c["meta"]["runner_constants"],
                         {"TOLERANCE_S": runner.TOLERANCE_S, "SETTLE_S": runner.SETTLE_S,
                          "MAX_MISSING_IN_FAULT": runner.MAX_MISSING_IN_FAULT,
                          "MAX_DISCARDS": runner.MAX_DISCARDS, "FAULT_HEAVY_RATIO": "0.3"})
        self.assertTrue(c["out"].startswith(self.out))

    def test_fault_goes_only_to_v2_and_never_to_v1(self):
        self.block()
        puts = [e for e in self.cl.log if e[1] == "admin_put"]
        self.assertTrue(puts and all(e[2] == "v2" for e in puts))
        self.assertEqual(self.cl.admin["v1"].snapshot()["history"], [])

    def test_ttl_is_longer_than_the_fault_and_clear_comes_from_the_runner(self):
        self.block()
        put = next(e for e in self.cl.log if e[1] == "admin_put")
        self.assertEqual(put[3], 8 * 60 + 60)  # prazo = falha + 1 min de folga
        hist = [h["event"] for h in self.cl.admin["v2"].snapshot()["history"]]
        self.assertEqual(hist[:2], ["set", "clear"])
        self.assertNotIn("expired", hist)

    def test_put_happens_at_baseline_end_and_delete_at_fault_end(self):
        self.block()
        put = next(e for e in self.cl.log if e[1] == "admin_put")
        dele = next(e for e in self.cl.log if e[1] == "admin_delete" and e[0] > put[0])
        r = self.runs()[0]
        self.assertAlmostEqual(put[0], r["t_on"], delta=2)
        self.assertAlmostEqual(dele[0], r["t_off"], delta=2)

    def test_state_is_clean_after_the_block(self):
        self.block()
        self.assertFalse(self.cl.admin["v2"].snapshot()["active"])
        self.assertEqual(self.cl.env("probe-generator")["HEAVY_RATIO"], "0.3")

    def test_resume_skips_runs_already_ok(self):
        self.block()
        n = len(self.coll.started)
        self.block()
        self.assertEqual(len(self.coll.started), n)
        self.assertEqual(len(self.runs()), 2)

    def test_resume_completes_only_what_is_missing(self):
        self.block(self.plan())
        lines = self.read(os.path.join(self.cdir, "runs.jsonl")).splitlines()
        with open(os.path.join(self.cdir, "runs.jsonl"), "w") as f:
            f.write(lines[0] + "\n")
        runner.write_manifest(self.cdir)  # como se o bloco anterior tivesse terminado após a 1ª
        self.block(self.plan())
        self.assertEqual([r["rep"] for r in self.runs()], [1, 2])


class DiscardTest(Base):
    def test_readback_divergence_discards_and_replaces_the_run(self):
        self.cl.exec_fail_after_put = True
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        rs = self.runs()
        self.assertTrue(rs and all(r["status"] == "discarded" for r in rs))
        self.assertIn("leitura de volta", rs[0]["reason"])
        self.assertFalse(self.cl.admin["v2"].snapshot()["active"])

    def test_discarded_run_is_replaced_until_reps_valid(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=2)])
        calls = {"n": 0}
        orig = self.cl.run

        def flaky(*a):
            if a[0] == "exec" and "GET" in a and calls["n"] == 0 and self.cl.admin["v2"].snapshot()["active"]:
                calls["n"] += 1
                self.cl.admin["v2"].clear()  # a falha some no meio: divergência na leitura de volta
            return orig(*a)

        self.cl.run = flaky
        self.block(plan)
        status = [r["status"] for r in self.runs()]
        self.assertEqual(status.count("ok"), 2)
        self.assertEqual(status.count("discarded"), 1)

    def test_node_not_ready_after_the_run_discards(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        orig = self.cl.run
        state = {"deletes": 0}

        def f(*a):
            out = orig(*a)
            if a[0] == "exec" and "DELETE" in a:
                self.cl.nodes_ready = False
            return out

        self.cl.run = f
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertIn("nó", self.runs()[0]["reason"])

    def test_too_many_missing_windows_in_the_fault_range_discards(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [240, 300, 360]  # 3 rótulos com falha: (180, 660]
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertIn("janelas", self.runs()[0]["reason"])

    # Convenção: o rótulo m cobre [m-60, m). Falha em [t_on, t_off) = [180, 660) relativo ao
    # início; as janelas com falha são os rótulos em (t_on, t_off] = 240, 300, ..., 660.
    def test_label_at_t_on_is_baseline_not_fault(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [180, 240, 300]  # 180 cobre [120, 180): baseline
        self.block(plan)
        r = self.runs()[0]
        self.assertEqual((r["status"], r["missing_in_fault"]), ("ok", 2))

    def test_label_at_t_off_is_fault(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [540, 600, 660]  # 660 cobre [600, 660): ainda com falha
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertIn("3 janelas", self.runs()[0]["reason"])

    def test_label_after_t_off_is_not_fault(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [600, 660, 720]  # 720 cobre [660, 720): depois
        self.block(plan)
        self.assertEqual(self.runs()[0]["missing_in_fault"], 2)

    def test_missing_windows_outside_the_fault_range_do_not_discard(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [0, 60, 120, 180, 720, 780, 840]  # só baseline e depois da falha
        self.block(plan)
        self.assertEqual(self.runs()[0]["status"], "ok")

    def test_an_early_discard_stops_the_collector(self):
        self.cl.exec_fail_after_put = True
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertTrue(self.coll.stopped)

    def test_two_missing_windows_are_tolerated(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])
        self.coll.missing_offsets = [240, 300]  # 2 janelas dentro da faixa de falha: tolerado
        self.block(plan)
        self.assertEqual(self.runs()[0]["status"], "ok")

    def test_discard_reason_never_depends_on_detection(self):
        # o runner não conhece o detector: nenhuma execução é descartada por detectar ou não
        import inspect
        src = inspect.getsource(runner)
        for banned in ("replay", "ShadowAgent", "detected", "first_detected"):
            self.assertNotIn(banned, src)


class ControlTest(Base):
    def test_control_runs_without_any_fault_and_checks_nothing_turned_on(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])
        self.block(plan)
        self.assertEqual(self.coll.started[0]["minutes"], 45)
        self.assertEqual([e for e in self.cl.log if e[1] == "admin_put"], [])
        self.assertEqual(self.runs()[0]["status"], "ok")
        self.assertEqual(self.runs()[0]["kind"], "control")

    def test_control_uses_the_original_heavy_ratio(self):
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.3"
        raw = make_plan(clusters={"a": {"context": "home/cluster-a", "prom_port": 9151, "heavy_ratio_original": "0.3"}},
                        scenarios=[{"id": "ctrl", "kind": "control", "minutes": 5}])
        raw["out_dir"] = self.out
        self.block(validate_plan(raw))
        sets = [e for e in self.cl.log if e[1] == "set_env" and e[2] == "probe-generator"]
        self.assertEqual(sets, [])  # já estava no valor original: sem rollout

    def test_fault_heavy_ratio_comes_from_the_constant(self):
        old = runner.FAULT_HEAVY_RATIO
        runner.FAULT_HEAVY_RATIO = "0.4"
        try:
            self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)]))
        finally:
            runner.FAULT_HEAVY_RATIO = old
        self.assertEqual(self.coll.started[0]["meta"]["conditions"]["heavy_ratio"], "0.4")

    def test_fault_scenario_sets_heavy_ratio_then_restores_original(self):
        raw = make_plan(clusters={"a": {"context": "home/cluster-a", "prom_port": 9151, "heavy_ratio_original": "0.5"}})
        raw["out_dir"] = self.out
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.5"
        self.block(validate_plan(raw))
        sets = [e[3] for e in self.cl.log if e[1] == "set_env" and e[2] == "probe-generator"]
        self.assertEqual(sets, [("HEAVY_RATIO=0.3",), ("HEAVY_RATIO=0.5",)])
        self.assertEqual(self.cl.env("probe-generator")["HEAVY_RATIO"], "0.5")


class SigmaAndRestoreTest(Base):
    def test_sigma_is_set_on_both_versions_and_removed_at_the_end(self):
        self.block(self.plan(sigma=0.1))
        sets = [(e[2], e[3]) for e in self.cl.log if e[1] == "set_env" and "SLOW_JITTER_SIGMA" in "".join(e[3])]
        self.assertEqual(sets[0], ("app-service-v1", ("SLOW_JITTER_SIGMA=0.1",)))
        self.assertEqual(sets[1], ("app-service-v2", ("SLOW_JITTER_SIGMA=0.1",)))
        self.assertNotIn("SLOW_JITTER_SIGMA", self.cl.env("app-service-v1"))
        self.assertNotIn("SLOW_JITTER_SIGMA", self.cl.env("app-service-v2"))

    def test_final_state_equals_the_snapshot_taken_before(self):
        before = copy.deepcopy(self.cl.deploys)
        self.block(self.plan(sigma=0.1))
        self.assertEqual(self.cl.deploys, before)

    def test_restore_runs_even_when_the_block_crashes(self):
        class Boom(FakeCollector):
            def start(s, *a):
                raise RuntimeError("coletor morreu")
        self.coll = Boom()
        before = copy.deepcopy(self.cl.deploys)
        with self.assertRaises(RuntimeError):
            self.block(self.plan(sigma=0.1))
        self.assertEqual(self.cl.deploys, before)
        self.assertFalse(self.cl.admin["v2"].snapshot()["active"])

    def test_restore_command_recovers_a_hard_killed_runner(self):
        self.block(self.plan(sigma=0.1))  # só para gerar o snapshot em disco
        snap_path = os.path.join(self.cdir, "snapshot-pre-a.json")
        self.assertTrue(os.path.exists(snap_path))
        # simula um runner morto no meio de uma falha: tudo fora do lugar
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.9"
        self.cl.deploys["app-service-v1"]["env"]["SLOW_JITTER_SIGMA"] = "0.3"
        self.cl.deploys["app-service-v2"]["env"]["SLOW_JITTER_SIGMA"] = "0.3"
        self.cl.admin["v2"].set({**ZERO, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, 600)
        before = json.loads(self.read(snap_path))
        diffs = runner.restore_from_snapshot(self.deps(), self.plan(sigma=0.1), "a")
        self.assertEqual(diffs, [])
        self.assertEqual(self.cl.env("probe-generator")["HEAVY_RATIO"], before["deployments"]["probe-generator"]["HEAVY_RATIO"])
        self.assertNotIn("SLOW_JITTER_SIGMA", self.cl.env("app-service-v1"))
        self.assertFalse(self.cl.admin["v2"].snapshot()["active"])

    def test_restore_touches_only_runner_managed_keys_and_reports_other_drift(self):
        self.block(self.plan(sigma=0.1))
        logs = []
        deps = self.deps()
        deps.log = lambda *a: logs.append(" ".join(map(str, a)))
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.9"   # gerenciada: volta
        self.cl.deploys["probe-generator"]["env"]["WORKERS"] = "4"         # alheia: só avisa
        self.cl.deploys["app-service-v2"]["env"]["SLOW_DELAY_S"] = "8"     # alheia: só avisa
        diffs = runner.restore_from_snapshot(deps, self.plan(sigma=0.1), "a")
        self.assertEqual(diffs, [])
        self.assertEqual(self.cl.env("probe-generator")["HEAVY_RATIO"], "0.3")
        self.assertEqual(self.cl.env("probe-generator")["WORKERS"], "4")
        self.assertEqual(self.cl.env("app-service-v2")["SLOW_DELAY_S"], "8")
        self.assertTrue(any("deriva" in x and "WORKERS" in x for x in logs), logs)

    def test_diff_snapshot_reports_differences(self):
        a = runner.take_snapshot(FakeKube(self.cl))
        self.cl.deploys["app-service-v1"]["env"]["X"] = "1"
        b = runner.take_snapshot(FakeKube(self.cl))
        d = runner.diff_snapshot(a, b)
        self.assertTrue(any("app-service-v1" in x for x in d), d)
        self.assertEqual(runner.diff_snapshot(a, a), [])


class SnapshotOnceTest(Base):
    def test_snapshot_is_never_overwritten_by_a_later_block(self):
        self.block()
        path = os.path.join(self.cdir, "snapshot-pre-a.json")
        first = self.read(path)
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.9"  # estado sujo
        with self.assertRaises(PreflightError):
            self.block()
        self.assertEqual(self.read(path), first)

    def test_snapshot_is_written_before_the_first_change(self):
        self.block(self.plan(sigma=0.1))
        snap = json.loads(self.read(os.path.join(self.cdir, "snapshot-pre-a.json")))
        self.assertNotIn("SLOW_JITTER_SIGMA", snap["deployments"]["app-service-v1"])
        self.assertEqual(snap["cluster"], "a")


class SnapshotPolicyTest(Base):
    def test_snapshot_is_never_replaced_and_unrelated_drift_is_left_alone(self):
        self.block()
        # deriva de uma variável que o pré-voo não confere
        self.cl.deploys["probe-generator"]["env"]["EXTRA"] = "1"
        self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], id="outro", reps=1)]))
        snap = json.loads(self.read(os.path.join(self.cdir, "snapshot-pre-a.json")))
        self.assertNotIn("EXTRA", snap["deployments"]["probe-generator"])
        # o runner só restaura o que gerencia: a alteração alheia fica como estava
        self.assertEqual(self.cl.env("probe-generator")["EXTRA"], "1")


class FaultSafetyTest(Base):
    def one_run_plan(self):
        return self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)])

    def test_divergence_right_after_turning_on_is_detected_immediately(self):
        self.cl.exec_fail_after_put = True
        with self.assertRaises(runner.TooManyDiscards):
            self.block(self.one_run_plan())
        r = self.runs()[0]
        self.assertIn("logo após ligar", r["reason"])
        # descartou em t_on, sem esperar os 8 min da falha
        self.assertLess(self.clock.now() - r["t0"], 4 * 4 * 60 + 600)
        self.assertTrue(all("logo após ligar" in x["reason"] for x in self.runs()))

    def test_sigma_not_applied_to_one_version_aborts_and_restores(self):
        before = copy.deepcopy(self.cl.deploys)
        orig = self.cl.run

        def f(*a):
            if a[:2] == ("set", "env") and a[2] == "deploy/app-service-v2" and "SLOW_JITTER_SIGMA=0.1" in a:
                return ""  # o rollout 'passou', mas a variável não ficou na v2
            return orig(*a)

        self.cl.run = lambda *a: f(*a)
        with self.assertRaises(PreflightError) as cm:
            self.block(self.plan(sigma=0.1))
        self.assertIn("divergente", str(cm.exception))
        self.assertEqual(self.cl.deploys, before)
        self.assertEqual(self.coll.started, [])

    def test_clock_skew_between_pod_and_runner_discards_the_run(self):
        self.cl.admin["v2"]._clock = lambda: self.clock.now() + 100
        with self.assertRaises(runner.TooManyDiscards):
            self.block(self.one_run_plan())
        self.assertIn("horário da falha diverge", self.runs()[0]["reason"])

    def test_run_fault_clears_the_fault_itself_if_it_crashes_midway(self):
        plan = self.one_run_plan()
        os.makedirs(self.cdir, exist_ok=True)
        ctx = runner.Ctx(plan, "a", self.deps())
        orig = self.cl.run

        def f(*a):
            if a[0] == "exec" and "GET" in a and self.cl.admin["v2"].snapshot()["active"]:
                raise KubeError("kubectl exec caiu")
            return orig(*a)

        self.cl.run = f
        with self.assertRaises(KubeError):
            runner.run_fault(ctx, plan.scenarios[0], 1, 1)
        self.assertFalse(self.cl.admin["v2"].snapshot()["active"])  # sem esperar o prazo nem a restauração
        self.assertTrue(ctx.changed)  # ligar a falha já obriga o bloco a restaurar


class ManifestAndInhibitTest(Base):
    def test_manifest_hashes_every_data_file_and_detects_changes(self):
        self.block()
        m = runner.write_manifest(self.cdir)
        txt = self.read(m)
        self.assertIn("runs.jsonl", txt)
        first = txt
        with open(os.path.join(self.cdir, "runs.jsonl"), "a") as f:
            f.write("{}\n")
        runner.write_manifest(self.cdir)
        self.assertNotEqual(self.read(m), first)
        self.assertEqual(runner.verify_manifest(self.cdir), [])
        with open(os.path.join(self.cdir, "runs.jsonl"), "a") as f:
            f.write("tamper\n")
        self.assertEqual(runner.verify_manifest(self.cdir), ["runs.jsonl"])

    def two_cluster_plan(self):
        clusters = {c: {"context": f"home/cluster-{c}", "prom_port": 9151 + i, "heavy_ratio_original": "0.3"}
                    for i, c in enumerate(("a", "b"))}
        return self.plan(clusters=clusters, scenarios=[dict(make_plan()["scenarios"][0], reps=1)])

    def test_each_cluster_has_its_own_dir_and_manifest(self):
        plan = self.two_cluster_plan()
        self.block(plan, "a")
        self.block(plan, "b")
        self.assertEqual(sorted(os.listdir(self.out)), ["a", "b"])
        for c in ("a", "b"):
            d = os.path.join(self.out, c)
            names = runner._data_files(d)
            self.assertTrue(names)
            self.assertTrue(all(n == "runs.jsonl" or c in n for n in names), names)
            self.assertEqual(runner.verify_manifest(d), [])
            self.assertIn("runs.jsonl", self.read(os.path.join(d, "MANIFEST.sha256")))

    def test_block_start_verifies_the_existing_manifest(self):
        self.block()
        p = os.path.join(self.cdir, "runs.jsonl")
        txt = self.read(p)
        with open(p, "w") as f:  # altera um registro já gravado (acréscimo no fim seria aceito)
            f.write(txt.replace('"ok"', '"OK"', 1))
        with self.assertRaises(PreflightError) as cm:
            self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], id="outro", reps=1)]))
        self.assertIn("manifesto", str(cm.exception))
        self.assertIn("runs.jsonl", str(cm.exception))

    def test_block_start_accepts_data_appended_after_a_hard_kill(self):
        # kill -9 não roda o finally: runs.jsonl e o arquivo da execução crescem depois do manifesto
        self.block()
        with open(os.path.join(self.cdir, "runs.jsonl"), "a") as f:
            f.write(json.dumps({"cluster": "a", "scenario": "x", "status": "discarded", "rep": 1,
                                "attempt": 1}) + "\n")
        self.assertEqual(runner.verify_manifest(self.cdir), ["runs.jsonl"])  # o verify da CLI é estrito
        self.assertEqual(runner.verify_manifest(self.cdir, allow_append=True), [])
        self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], id="outro", reps=1)]))

    def test_append_check_still_catches_truncation_and_edits(self):
        self.block()
        p = os.path.join(self.cdir, "runs.jsonl")
        txt = self.read(p)
        with open(p, "w") as f:
            f.write(txt[:-5])
        self.assertEqual(runner.verify_manifest(self.cdir, allow_append=True), ["runs.jsonl"])
        with open(p, "w") as f:
            f.write("X" + txt[1:] + "mais\n")
        self.assertEqual(runner.verify_manifest(self.cdir, allow_append=True), ["runs.jsonl"])

    def test_manifest_error_is_not_suppressed(self):
        orig = runner.write_manifest
        runner.write_manifest = lambda d: (_ for _ in ()).throw(OSError("disco cheio"))
        try:
            with self.assertRaisesRegex(OSError, "disco cheio"):
                self.block()
        finally:
            runner.write_manifest = orig

    def test_manifest_error_does_not_mask_the_original_error(self):
        orig = runner.write_manifest
        runner.write_manifest = lambda d: (_ for _ in ()).throw(OSError("disco cheio"))
        self.cl.exec_fail_after_put = True
        try:
            with self.assertRaises(runner.TooManyDiscards):
                self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)]))
        finally:
            runner.write_manifest = orig

    def test_inhibit_argv_wraps_the_command_once(self):
        argv = runner.inhibit_argv(["python3", "runner.py", "run"], environ={}, have=lambda b: True)
        self.assertEqual(argv[0], "systemd-inhibit")
        self.assertIn("--what=sleep:idle", argv)
        self.assertEqual(argv[-3:], ["python3", "runner.py", "run"])
        self.assertIsNone(runner.inhibit_argv(["x"], environ={"RUNNER_INHIBITED": "1"}, have=lambda b: True))
        self.assertIsNone(runner.inhibit_argv(["x"], environ={}, have=lambda b: False))


class AdminCallTest(Base):
    def test_admin_call_goes_through_exec_on_the_app_container(self):
        calls = []
        kube = FakeKube(self.cl)
        orig = kube.run
        kube.run = lambda *a, **k: (calls.append(a), orig(*a))[1]
        runner.admin_call(kube, "v2", "GET")
        a = calls[0]
        self.assertEqual(a[:4], ("exec", "deploy/app-service-v2", "-c", "app"))
        self.assertEqual(a[4:7], ("--", "python3", "-c"))
        self.assertIn("127.0.0.1:8081", runner.ADMIN_SCRIPT)
        self.assertEqual(a[-2:], ("GET", ""))

    def test_admin_call_error_raises_kube_error(self):
        class Bad:
            def run(self, *a, **k):
                raise KubeError("exec falhou")
        with self.assertRaises(KubeError):
            runner.admin_call(Bad(), "v2", "GET")


class ControlResumeTest(Base):
    def test_interrupted_control_resumes_on_the_same_minute_grid(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])

        class Die(FakeCollector):
            def start(s, *a):
                super().start(*a)
                raise RuntimeError("host suspendeu")
        first = Die()
        self.coll = first
        with self.assertRaises(RuntimeError):
            self.block(plan)
        t0 = first.started[0]["start"]
        self.assertTrue(any(n.startswith(".state-ctrl") for n in os.listdir(self.cdir)))
        self.clock.t += 3 * 3600  # o relógio andou durante a queda
        self.coll = FakeCollector()
        self.block(plan)
        self.assertEqual(self.coll.started[0]["start"], t0)
        self.assertEqual(self.runs()[0]["status"], "ok")
        self.assertFalse(any(n.startswith(".state-ctrl") for n in os.listdir(self.cdir)))

    def crash_then_resume(self, plan, between=None):
        class Die(FakeCollector):
            def start(s, *a):
                super().start(*a)
                raise RuntimeError("host suspendeu")
        first = Die()
        self.coll = first
        with self.assertRaises(RuntimeError):
            self.block(plan)
        self.clock.t += 3600
        if between:
            between()
        self.coll = FakeCollector()
        self.block(plan)
        return first.started[0]

    def test_state_persists_t0_and_hist0(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])

        class Die(FakeCollector):
            def start(s, *a):
                super().start(*a)
                raise RuntimeError("x")
        self.coll = Die()
        with self.assertRaises(RuntimeError):
            self.block(plan)
        name = next(n for n in os.listdir(self.cdir) if n.startswith(".state-ctrl"))
        st = json.loads(self.read(os.path.join(self.cdir, name)))
        self.assertEqual(st["t0"], self.coll.started[0]["start"])
        self.assertEqual(st["hist0"], {"v1": 0, "v2": 0})

    def test_resume_after_sigma_reapplied_discards_and_restarts_with_new_t0(self):
        plan = self.plan(sigma=0.1, scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])
        first = self.crash_then_resume(plan)
        rs = self.runs()
        self.assertEqual([r["status"] for r in rs], ["discarded", "ok"])
        self.assertIn("retomada", rs[0]["reason"])
        self.assertEqual(rs[0]["t0"], first["start"])
        self.assertNotEqual(rs[1]["t0"], first["start"])
        self.assertEqual(len(self.coll.started), 1)  # a tentativa descartada nem liga o coletor
        self.assertFalse(self.coll.started[0]["meta"]["resumed"])

    def test_resume_after_a_restore_rollout_discards(self):
        # controle com HEAVY_RATIO diferente do original: o bloco muda, a restauração desfaz
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45, "heavy_ratio": "0.4"}])
        self.crash_then_resume(plan)
        rs = self.runs()
        self.assertEqual([r["status"] for r in rs], ["discarded", "ok"])
        self.assertIn("retomada", rs[0]["reason"])

    def test_resume_after_an_admin_change_while_down_discards_at_once(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])

        def poke():
            self.cl.admin["v2"].set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 30)
            self.cl.admin["v2"].clear()
        self.crash_then_resume(plan, poke)
        rs = self.runs()
        self.assertEqual([r["status"] for r in rs], ["discarded", "ok"])
        self.assertIn("retomada", rs[0]["reason"])
        self.assertEqual(len(self.coll.started), 1)

    def test_discarded_resume_leaves_no_stale_state(self):
        plan = self.plan(sigma=0.1, scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])
        self.crash_then_resume(plan)
        self.assertEqual([n for n in os.listdir(self.cdir) if n.startswith(".state-")], [])

    def test_restore_writes_its_rollouts_to_the_journal(self):
        plan = self.plan()
        os.makedirs(self.cdir)
        with open(runner.snapshot_path(plan, "a"), "w") as f:
            json.dump({"cluster": "a", **runner.take_snapshot(FakeKube(self.cl))}, f)
        self.cl.deploys["app-service-v1"]["env"]["SLOW_JITTER_SIGMA"] = "0.1"
        t = self.clock.now()
        runner.restore_from_snapshot(self.deps(), plan, "a")
        self.assertEqual([r["deploy"] for r in runner.rollouts_since(plan, "a", t)], ["app-service-v1"])

    def test_block_set_env_writes_to_the_journal(self):
        t = self.clock.now()
        self.block(self.plan(sigma=0.1, scenarios=[{"id": "ctrl", "kind": "control", "minutes": 5}]))
        rs = runner.rollouts_since(self.plan(), "a", t)
        self.assertEqual([(r["deploy"], r["pairs"]) for r in rs[:2]],
                         [("app-service-v1", ["SLOW_JITTER_SIGMA=0.1"]),
                          ("app-service-v2", ["SLOW_JITTER_SIGMA=0.1"])])

    def test_conditions_reads_each_version_separately(self):
        self.cl.deploys["app-service-v1"]["env"]["SLOW_JITTER_SIGMA"] = "0.1"
        self.cl.deploys["app-service-v2"]["env"]["SLOW_JITTER_SIGMA"] = "0.3"
        c = runner.conditions(FakeKube(self.cl))
        self.assertEqual((c["sigma_v1"], c["sigma_v2"], c["heavy_ratio"]), ("0.1", "0.3", "0.3"))

    def test_valid_resume_is_marked_in_the_meta(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])
        first = self.crash_then_resume(plan)
        self.assertFalse(first["meta"]["resumed"])
        m = self.coll.started[0]["meta"]
        self.assertTrue(m["resumed"])
        self.assertEqual(m["t0"], first["start"])

    def test_meta_carries_the_real_conditions(self):
        self.cl.deploys["probe-generator"]["env"]["HEAVY_RATIO"] = "0.5"
        raw = make_plan(clusters={"a": {"context": "home/cluster-a", "prom_port": 9151, "heavy_ratio_original": "0.5"}},
                        sigma=0.3, scenarios=[{"id": "ctrl", "kind": "control", "minutes": 5},
                                              dict(make_plan()["scenarios"][0], reps=1)])
        raw["out_dir"] = self.out
        self.block(validate_plan(raw))
        ctrl, fault = self.coll.started[0]["meta"], self.coll.started[1]["meta"]
        self.assertEqual(ctrl["conditions"], {"heavy_ratio": "0.5", "sigma_v1": "0.3", "sigma_v2": "0.3"})
        self.assertEqual(fault["conditions"]["heavy_ratio"], "0.3")

    def test_control_is_discarded_if_a_fault_was_turned_on_meanwhile(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 5}])
        orig = self.coll.start

        def start(*a):
            h = orig(*a)
            self.cl.admin["v2"].set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 30)
            return h
        self.coll.start = start
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertIn("falha foi ligada", self.runs()[0]["reason"])

    def test_control_detects_a_change_even_with_the_history_full(self):
        # histórico cortado em 50: set+clear durante o controle não muda len(history)
        v2 = self.cl.admin["v2"]
        for _ in range(30):
            v2.set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 30)
            v2.clear()
        self.assertEqual(len(v2.snapshot()["history"]), 50)
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 5}])
        orig = self.coll.start

        def start(*a):
            h = orig(*a)
            v2.set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 30)
            v2.clear()
            return h
        self.coll.start = start
        with self.assertRaises(runner.TooManyDiscards):
            self.block(plan)
        self.assertIn("falha foi ligada na v2", self.runs()[0]["reason"])

    def test_admin_without_change_counter_fails_preflight(self):
        for st in self.cl.admin.values():
            snap = st.snapshot
            st.snapshot = lambda snap=snap: {k: v for k, v in snap().items() if k != "changes"}
        with self.assertRaises(PreflightError) as cm:
            self.block()
        self.assertIn("contador", str(cm.exception))

    def test_control_is_not_discarded_for_missing_windows(self):
        plan = self.plan(scenarios=[{"id": "ctrl", "kind": "control", "minutes": 45}])
        self.coll.missing_offsets = [60 * i for i in range(10, 20)]
        self.block(plan)
        r = self.runs()[0]
        self.assertEqual((r["status"], r["missing"]), ("ok", 10))

    def test_second_block_after_a_fault_run_is_not_blocked_by_admin_history(self):
        self.block()  # deixa set/clear no histórico da v2
        self.assertTrue(self.cl.admin["v2"].snapshot()["history"])
        self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], id="outro", reps=1)]))
        self.assertEqual([r["scenario"] for r in self.runs()].count("outro"), 1)

    def test_app_versions_need_exactly_one_replica(self):
        # kubectl exec deploy/ fala com um pod só: com 2 réplicas o admin cobre metade do tráfego
        for name in ("app-service-v1", "app-service-v2"):
            cl = FakeCluster(self.clock)
            cl.deploys[name].update(replicas=2, ready=2)
            self.cl = cl
            with self.assertRaises(PreflightError) as cm:
                self.block()
            self.assertIn(f"{name}: replicas=2", str(cm.exception))

    def test_a_v1_with_history_blocks_the_start(self):
        self.cl.admin["v1"].set({**ZERO, "slow_extra_fraction": 0.1, "slow_extra_s": 1}, 30)
        self.cl.admin["v1"].clear()
        with self.assertRaises(PreflightError) as cm:
            self.block()
        self.assertIn("v1", str(cm.exception))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raw = make_plan()
        raw["out_dir"] = os.path.join(self.tmp.name, "out")
        self.path = os.path.join(self.tmp.name, "plan.json")
        with open(self.path, "w") as f:
            json.dump(raw, f)
        self.plan = load_plan(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def boom(self, plan):
        raise AssertionError("não pode criar dependências reais sem confirmação")

    def call(self, *args, **kw):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = runner.main(list(args), **kw)
        return rc, out.getvalue()

    def test_run_without_confirm_is_refused_before_touching_anything(self):
        rc, out = self.call("run", self.path, "--cluster", "a", deps_factory=self.boom)
        self.assertEqual(rc, 2)
        self.assertIn(self.plan.sha256[:12], out)

    def test_run_with_a_wrong_confirm_is_refused(self):
        rc, _ = self.call("run", self.path, "--cluster", "a", "--confirm", "000000000000", deps_factory=self.boom)
        self.assertEqual(rc, 2)

    def test_restore_also_needs_the_confirm(self):
        rc, _ = self.call("restore", self.path, "--cluster", "a", deps_factory=self.boom)
        self.assertEqual(rc, 2)

    def test_dry_run_needs_no_cluster_and_prints_the_hash(self):
        rc, out = self.call("dry-run", self.path, deps_factory=self.boom)
        self.assertEqual(rc, 0)
        self.assertIn(self.plan.sha256[:12], out)
        self.assertIn('"runs": 2', out)

    def test_unknown_cluster_is_a_usage_error(self):
        with self.assertRaises(SystemExit):
            self.call("preflight", self.path, "--cluster", "z", deps_factory=self.boom)

    def test_verify_detects_a_tampered_file(self):
        d = os.path.join(self.tmp.name, "data")
        os.makedirs(d)
        with open(os.path.join(d, "x.jsonl"), "w") as f:
            f.write("a\n")
        runner.write_manifest(d)
        self.assertEqual(self.call("verify", d)[0], 0)
        with open(os.path.join(d, "x.jsonl"), "a") as f:
            f.write("b\n")
        rc, out = self.call("verify", d)
        self.assertEqual(rc, 1)
        self.assertIn("x.jsonl", out)


class TemplateTest(unittest.TestCase):
    def test_the_shipped_template_stays_valid_and_is_marked_provisional(self):
        p = load_plan(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans", "TEMPLATE-PROVISORIO.json"))
        self.assertIn("PROVISORIO", p.name)
        self.assertIn("NAO-CONGELADO", p.prereg)
        s = runner.summarize(p, "a")
        self.assertEqual(s["runs"], 45)
        self.assertGreater(s["total_min"], 45 * 14)


class HelpersTest(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(runner.parse_duration_s("72h"), 72 * 3600)
        self.assertEqual(runner.parse_duration_s("1d12h"), 36 * 3600)
        self.assertEqual(runner.parse_duration_s("30m"), 1800)
        for bad in ("", "72", "h", "72 h", "3x"):
            with self.assertRaises(ValueError, msg=bad):
                runner.parse_duration_s(bad)

    def test_real_kube_builds_a_scoped_command(self):
        k = runner.RealKube("home/cluster-a", "lab-apps")
        self.assertEqual(k.argv(["get", "nodes"]),
                         ["kubectl", "--context", "home/cluster-a", "-n", "lab-apps", "get", "nodes"])

    def test_retention_below_72h_is_the_threshold(self):
        self.assertEqual(runner.MIN_RETENTION_S, 72 * 3600)


if __name__ == "__main__":
    unittest.main()
