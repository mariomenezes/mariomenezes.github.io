"""Contrato do orquestrador do Flagger real (v6). O Flagger e o cluster são emulados:
o `kubectl exec` do admin é respondido pelo FaultState real do app, com relógio falso."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
from app_server import FaultState, parse_fault  # noqa: E402

import flagger_runner as fr  # noqa: E402
from runner import Deps, KubeError, PreflightError  # noqa: E402

T0 = 1_761_000_000.0
ZERO = {"slow_extra_fraction": 0.0, "slow_extra_s": 0.0, "fast_delay_fraction": 0.0, "fast_delay_s": 0.0}
ITER = 16


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    def __init__(self, t=T0 + 5):
        self.t = float(t)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(0.0, s)


class FakeFlagger:
    """Cluster com um Canary. Cada trigger inicia uma análise: Progressing após `start_delay`;
    a checagem k roda em T_p + 60k e falha se `sees_fault` e a falha estava ativa naquele
    instante (ou k está em `spurious`); com 5 falhas acumuladas o canary vira Failed; sem
    isso, Succeeded na iteração 16."""

    def __init__(self, clock, sees_fault=True, start_delay=30.0, spurious=()):
        self.clock, self.sees_fault, self.start_delay, self.spurious = clock, sees_fault, start_delay, set(spurious)
        self.nodes_ready = True
        self.log = []
        self.revs = []
        self.trigger_t = None
        self.rev = None
        self.admin = self.new_admin()
        self.intervals = []
        self.exec_fail_after_put = False
        self.primary = {"replicas": 1, "ready": 1}
        self.target_replicas = 0
        self.loadgen = {"replicas": 2, "ready": 2}
        self.flagger_ready = True
        self.skew = 0.0
        self.path_max_ms = 5
        self.path_errors = 0
        self.path_broken = False

    def new_admin(self):
        return FaultState(ZERO, clock=lambda: self.clock.now() + self.skew)

    # --- estado do canary (calculado do relógio)
    def _active_at(self, t):
        return any(a <= t <= (b if b is not None else 1e18) for a, b in self.intervals)

    def status(self):
        if self.trigger_t is None:
            return {"phase": "Initialized", "failedChecks": 0, "iterations": 0}
        tp = self.trigger_t + self.start_delay
        now = self.clock.now()
        if now < tp:
            # o Flagger só nota a revisão no próximo ciclo: até lá o status ainda é o do run anterior
            # (Failed com lastTransitionTime fresco, pois o status é ressincronizado a cada ciclo)
            return {"phase": "Failed", "failedChecks": 5, "iterations": 0,
                    "conditions": [{"lastTransitionTime": iso(now - 1)}]}
        failed, k = 0, 0
        for k in range(1, ITER + 1):
            tk = tp + 60 * k
            if tk > now:
                k -= 1
                break
            bad = k in self.spurious or (self.sees_fault and self._active_at(tk))
            failed += bad
            if failed >= 5:
                return {"phase": "Failed", "failedChecks": failed, "iterations": k,
                        "conditions": [{"lastTransitionTime": iso(tk)}]}
        if k >= ITER:
            return {"phase": "Succeeded", "failedChecks": failed, "iterations": ITER,
                    "conditions": [{"lastTransitionTime": iso(tp + 60 * ITER)}]}
        return {"phase": "Progressing", "failedChecks": failed, "iterations": k}

    def canary_pod_exists(self):
        return self.status()["phase"] in ("Progressing",)

    def run(self, *a):
        a = list(a)
        t = self.clock.now()
        if a[:2] == ["get", "nodes"]:
            st = "True" if self.nodes_ready else "False"
            return json.dumps({"items": [{"status": {"conditions": [{"type": "Ready", "status": st}]}}]})
        if a[:3] == ["get", "canary", "app-fl"]:
            return json.dumps({"status": self.status()})
        if a[:2] == ["get", "deploy"]:
            name = a[2]
            d = {"app-fl": {"replicas": self.target_replicas, "ready": self.target_replicas},
                 "app-fl-primary": self.primary, "probe-flagger": self.loadgen}[name]
            return json.dumps({"spec": {"replicas": d["replicas"], "template": {"spec": {"containers": [{"env": []}]}}},
                               "status": {"readyReplicas": d["ready"]}})
        if a[:2] == ["get", "pods"]:
            return json.dumps({"items": [{"status": {"phase": "Running" if self.flagger_ready else "Pending"}}]})
        if a[:2] == ["patch", "deploy"]:
            rev = json.loads(a[a.index("-p") + 1])["spec"]["template"]["metadata"]["annotations"]["bench/rev"]
            self.revs.append(rev)
            self.rev, self.trigger_t, self.intervals = rev, t, []
            self.admin = self.new_admin()
            self.log.append((t, "trigger", rev))
            return ""
        if a[0] == "exec" and a[1] == "deploy/probe-flagger":
            if self.path_broken:
                raise KubeError("exec falhou")
            return json.dumps({"max_ms": self.path_max_ms, "errors": self.path_errors})
        if a[0] == "exec":
            return self._exec(a, t)
        raise AssertionError(f"comando inesperado: {a}")

    def _exec(self, a, t):
        if not self.canary_pod_exists():
            raise KubeError("pod do canary não existe")
        i = a.index("--")
        method, raw = a[i + 4], a[i + 5]
        st = self.admin
        if method == "GET":
            return json.dumps(st.snapshot())
        if method == "DELETE":
            st.clear()
            self._close(t)
            self.log.append((t, "admin_delete"))
            return json.dumps(st.snapshot())
        params, ttl = parse_fault(json.loads(raw))
        st.set(params, ttl)
        self.intervals.append([t, None])
        self.log.append((t, "admin_put", ttl))
        if self.exec_fail_after_put:
            st.clear()
        return json.dumps(st.snapshot())

    def _close(self, t):
        for iv in self.intervals:
            if iv[1] is None:
                iv[1] = t


class FakeKube:
    def __init__(self, c):
        self.c = c

    def run(self, *a, **kw):
        return self.c.run(*a)


class FakeHandle:
    def __init__(self, parent, start):
        self.parent, self.start = parent, start

    def wait(self):
        return {"collected": 14, "missing": []}

    def stop(self):
        self.parent.stopped.append(self.start)


class FakeCollector:
    def __init__(self):
        self.started, self.stopped = [], []

    def start(self, cluster, out_path, minutes, start, meta):
        self.started.append({"cluster": cluster, "out": out_path, "minutes": minutes, "start": start, "meta": meta})
        with open(out_path, "w") as f:
            f.write(json.dumps({"meta": meta}) + "\n")
        return FakeHandle(self, start)


def make_plan(**over):
    p = {"name": "t", "namespace": "flagger-lab", "out_dir": "OUT", "prereg": "v6-test",
         "clusters": {"a": {"context": "home/cluster-a", "prom_port": 9151}},
         "scenarios": [{"id": "dash10", "kind": "fault", "feature": "dashboard",
                        "params": {"fast_delay_fraction": 0.1, "fast_delay_s": 0.5},
                        "reps": 1, "baseline_min": 3, "fault_min": 8, "after_min": 3}]}
    p.update(over)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "out")
        self.cdir = os.path.join(self.out, "a")
        self.clock = Clock()
        self.cl = FakeFlagger(self.clock)
        self.coll = FakeCollector()
        self.prom = {"retention_s": 72 * 3600, "up": True}

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, **over):
        raw = make_plan(**over)
        raw["out_dir"] = self.out
        return fr.validate_plan(raw)

    def deps(self):
        return Deps(kube=lambda ctx: FakeKube(self.cl), now=self.clock.now, sleep=self.clock.sleep,
                    start_collector=self.coll.start, prom_check=lambda c: dict(self.prom),
                    disk_free=lambda p: 50 * 1024 ** 3, log=lambda *a: None)

    def block(self, plan=None):
        return fr.run_block(plan or self.plan(), "a", self.deps())

    def runs(self):
        p = os.path.join(self.cdir, "runs.jsonl")
        if not os.path.exists(p):
            return []
        with open(p) as f:
            return [json.loads(x) for x in f if x.strip()]


class RunFaultTest(Base):
    def test_max_failed_checks_is_kept_even_if_the_final_status_resets_it(self):
        orig = self.cl.status

        def status():  # como o Flagger real: depois do rollback o contador volta a 0
            st = orig()
            return {**st, "failedChecks": 0} if st["phase"] in ("Failed", "Succeeded") else st
        self.cl.status = status
        self.block()
        r = self.runs()[0]
        self.assertEqual(r["failed_checks"], 0)
        self.assertEqual(r["failed_checks_max"], 4)  # visto até a leitura antes do 5º (que já vem zerado)

    def test_flagger_rolls_back_inside_the_fault_window(self):
        self.block()
        r = self.runs()[0]
        self.assertEqual((r["status"], r["flagger_phase"]), ("ok", "Failed"))
        self.assertTrue(r["t_on"] < r["flagger_failed_at"] <= r["t_off"] + 60, r)
        self.assertEqual((r["t_on"] - r["t0"], r["t_off"] - r["t_on"]), (180, 480))
        self.assertFalse(r["flagger_before_fault"])
        self.assertEqual(r["failed_checks"], 5)

    def test_timeline_is_exact_in_the_emulated_cluster(self):
        # trigger em T0+5; Progressing visto em T0+35; início = próximo minuto depois de +60 s
        self.block()
        r = self.runs()[0]
        self.assertEqual(r["t0"], T0 + 120)
        self.assertEqual((r["t_on"], r["t_off"]), (T0 + 300, T0 + 780))
        # falhas das checagens k=5..9 (T0+35+60k): o 5º horário vem do status do Flagger, não da leitura
        self.assertEqual(r["flagger_failed_at"], T0 + 35 + 60 * 9)
        self.assertNotEqual(r["flagger_failed_at"], r["flagger_seen_at"])

    def test_blind_flagger_promotes_and_the_fault_runs_its_full_course(self):
        self.cl.sees_fault = False
        self.block()
        r = self.runs()[0]
        self.assertEqual((r["status"], r["flagger_phase"], r["flagger_failed_at"]), ("ok", "Succeeded", None))
        puts = [e for e in self.cl.log if e[1] == "admin_put"]
        dels = [e for e in self.cl.log if e[1] == "admin_delete"]
        self.assertAlmostEqual(puts[0][0], r["t_on"], delta=2)
        self.assertAlmostEqual(dels[0][0], r["t_off"], delta=2)
        self.assertEqual(puts[0][2], 8 * 60 + fr.TTL_MARGIN_S)

    def test_collector_gets_aligned_start_total_minutes_and_flagger_env(self):
        self.block()
        c = self.coll.started[0]
        self.assertEqual(c["minutes"], 14)
        self.assertEqual(c["start"] % 60, 0)
        self.assertEqual(c["meta"]["scenario"], "dash10")
        self.assertEqual(c["meta"]["plan_sha256"], self.plan().sha256)
        self.assertEqual(c["start"], self.runs()[0]["t0"])
        self.assertIn("flagger", c["meta"])

    def test_each_run_triggers_a_new_revision(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=2)])
        self.block(plan)
        self.assertEqual(len(set(self.cl.revs)), 2)
        self.assertEqual([r["rep"] for r in self.runs()], [1, 2])

    def test_rollback_before_the_fault_is_a_false_alarm_and_the_run_is_kept(self):
        self.cl.spurious = {1, 2, 3, 4, 5}  # 5 falhas exigem 5 min: a falha só liga bem depois
        sc = dict(make_plan()["scenarios"][0], baseline_min=8, fault_min=3, after_min=3)
        self.block(self.plan(scenarios=[sc]))
        r = self.runs()[0]
        self.assertEqual((r["status"], r["flagger_phase"], r["flagger_before_fault"]), ("ok", "Failed", True))
        self.assertTrue(r["flagger_failed_at"] <= r["t_on"])
        self.assertEqual([e for e in self.cl.log if e[1] == "admin_put"], [])  # canary já tinha saído

    def test_admin_failure_after_rollback_is_not_an_error(self):
        # o rollback derruba o pod do canary no meio da falha: DELETE/GET não podem estourar
        self.block()
        self.assertEqual(self.runs()[0]["status"], "ok")

    def test_readback_divergence_discards(self):
        self.cl.exec_fail_after_put = True
        with self.assertRaises(fr.TooManyDiscards):
            self.block(self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=1)]))
        self.assertIn("leitura de volta", self.runs()[0]["reason"])
        self.assertTrue(self.coll.stopped)
        self.assertEqual(len(self.runs()), fr.MAX_DISCARDS + 1)

    def test_canary_that_never_progresses_discards(self):
        self.cl.start_delay = 1e9
        with self.assertRaises(fr.TooManyDiscards):  # Flagger que nunca nota a revisão: o limite para o bloco
            self.block()
        self.assertEqual(len(self.runs()), fr.MAX_DISCARDS + 1)
        self.assertTrue(all("Progressing" in r["reason"] for r in self.runs()))
        self.assertEqual(self.coll.started, [])

    def test_node_not_ready_discards_before_triggering(self):
        self.cl.nodes_ready = False
        os.makedirs(self.cdir, exist_ok=True)
        plan = self.plan()
        r = fr.run_one(fr.Ctx(plan, "a", self.deps()), plan.scenarios[0], 1, 1)
        self.assertEqual(r["status"], "discarded")
        self.assertIn("NotReady", r["reason"])
        self.assertEqual(self.cl.revs, [])

    def test_clock_skew_discards(self):
        self.cl.skew = 100.0
        with self.assertRaises(fr.TooManyDiscards):
            self.block()
        self.assertIn("horário da falha diverge", self.runs()[0]["reason"])


class ControlTest(Base):
    def ctrl_plan(self, reps=1):
        return self.plan(scenarios=[{"id": "ctrl", "kind": "control", "reps": reps,
                                     "baseline_min": 3, "fault_min": 8, "after_min": 3}])

    def test_control_never_touches_the_admin_and_promotes(self):
        self.block(self.ctrl_plan())
        r = self.runs()[0]
        self.assertEqual((r["kind"], r["flagger_phase"], r["status"]), ("control", "Succeeded", "ok"))
        self.assertEqual([e for e in self.cl.log if e[1] in ("admin_put", "admin_delete")], [])

    def test_control_rollback_is_a_false_alarm(self):
        self.cl.spurious = {2, 4, 6, 8, 10}  # 5 falhas não consecutivas: reverte (acumuladas)
        self.block(self.ctrl_plan())
        r = self.runs()[0]
        self.assertEqual((r["flagger_phase"], r["status"]), ("Failed", "ok"))
        self.assertIsNotNone(r["flagger_failed_at"])

    def test_four_spurious_failures_do_not_roll_back(self):
        self.cl.spurious = {2, 4, 6, 8}
        self.block(self.ctrl_plan())
        self.assertEqual(self.runs()[0]["flagger_phase"], "Succeeded")


class BlockTest(Base):
    def test_resume_skips_runs_already_ok(self):
        plan = self.plan(scenarios=[dict(make_plan()["scenarios"][0], reps=2)])
        self.block(plan)
        n = len(self.cl.revs)
        self.block(plan)
        self.assertEqual(len(self.cl.revs), n)

    def test_output_dir_is_per_cluster_with_manifest_and_no_lock_left(self):
        self.block()
        names = os.listdir(self.cdir)
        self.assertIn("MANIFEST.sha256", names)
        self.assertNotIn(".lock-a", names)
        self.assertTrue(any(n.startswith("dash10-r01") for n in names))

    def test_a_busy_canary_is_waited_for_and_never_hijacked(self):
        self.cl.trigger_t = self.clock.now() - 100  # análise em curso de um run anterior
        self.cl.start_delay = 30.0
        self.block()
        self.assertEqual(self.runs()[0]["status"], "ok")
        self.assertEqual(len(self.cl.revs), 1)

    def test_busy_canary_that_never_finishes_blocks_the_start(self):
        self.cl.trigger_t = self.clock.now() - 100
        self.cl.sees_fault = False
        orig = self.cl.status
        self.cl.status = lambda: {"phase": "Progressing", "failedChecks": 0, "iterations": 3}
        with self.assertRaises(PreflightError):
            self.block()
        self.cl.status = orig

    def test_manifest_error_is_not_swallowed(self):
        import runner
        orig = runner.write_manifest
        runner.write_manifest = lambda d: (_ for _ in ()).throw(OSError("disco cheio"))
        try:
            with self.assertRaisesRegex(OSError, "disco cheio"):
                self.block()
        finally:
            runner.write_manifest = orig


class PreflightTest(Base):
    def bad(self):
        os.makedirs(self.cdir, exist_ok=True)
        return fr.preflight_failures(self.plan(), "a", FakeKube(self.cl), self.deps())

    def test_happy_path(self):
        self.assertEqual(self.bad(), [])

    def test_failures_are_listed(self):
        self.cl.primary = {"replicas": 1, "ready": 0}
        self.assertTrue(any("app-fl-primary" in b for b in self.bad()))
        self.cl.primary = {"replicas": 2, "ready": 2}
        self.assertTrue(any("app-fl-primary" in b and "réplicas" in b for b in self.bad()))
        self.cl.primary = {"replicas": 1, "ready": 1}
        self.cl.target_replicas = 1
        self.assertTrue(any("app-fl:" in b for b in self.bad()))
        self.cl.target_replicas = 0
        self.cl.loadgen = {"replicas": 2, "ready": 1}
        self.assertTrue(any("probe-flagger" in b for b in self.bad()))
        self.cl.loadgen = {"replicas": 2, "ready": 2}
        self.cl.flagger_ready = False
        self.assertTrue(any("flagger" in b.lower() for b in self.bad()))
        self.cl.flagger_ready = True
        self.prom = {"up": False, "retention_s": 0}
        self.assertTrue(any("Prometheus" in b for b in self.bad()))

    def test_slow_path_through_the_service_fails_the_preflight(self):
        # o caso real: endpoint morto de outro cluster fazia metade das requisições esperar 10 s
        self.cl.path_max_ms = 10025
        self.assertTrue(any("caminho" in b and "10025" in b for b in self.bad()))
        self.cl.path_max_ms = fr.PATH_MAX_MS
        self.assertEqual(self.bad(), [])
        self.cl.path_max_ms = fr.PATH_MAX_MS + 1
        self.assertTrue(any("caminho" in b for b in self.bad()))

    def test_unmeasurable_path_fails_the_preflight(self):
        self.cl.path_broken = True
        self.assertTrue(any("caminho não pôde ser medido" in b for b in self.bad()))

    def test_path_limit_is_frozen_at_one_second(self):
        self.assertEqual(fr.PATH_MAX_MS, 1000)

    def test_errors_on_the_path_fail_the_preflight(self):
        self.cl.path_errors = 1
        self.assertTrue(any("caminho" in b for b in self.bad()))

    def test_path_probe_runs_in_the_load_generator_pod_against_the_canary_host(self):
        calls = []
        kube = FakeKube(self.cl)
        orig = kube.run
        kube.run = lambda *a, **k: (calls.append(a), orig(*a))[1]
        os.makedirs(self.cdir, exist_ok=True)
        fr.preflight_failures(self.plan(), "a", kube, self.deps())
        probe = [c for c in calls if c[0] == "exec" and c[1] == "deploy/probe-flagger"]
        self.assertEqual(len(probe), 1)
        self.assertIn("app-fl.flagger-lab.svc.cluster.local:8080/api/v1/fast-data", probe[0][-1])

    def test_failed_canary_is_idle_but_progressing_is_not(self):
        self.cl.trigger_t = self.clock.now() - 100000  # análise antiga já concluída (Succeeded)
        self.assertEqual(self.bad(), [])


class PlanTest(unittest.TestCase):
    def test_hash_covers_the_constants_and_the_canary_settings(self):
        base = fr.validate_plan(make_plan()).sha256
        for name, v in (("TOLERANCE_S", 11), ("TTL_MARGIN_S", 61), ("LEAD_S", 61), ("MAX_DISCARDS", 4)):
            old = getattr(fr, name)
            setattr(fr, name, v)
            try:
                self.assertNotEqual(fr.validate_plan(make_plan()).sha256, base, name)
            finally:
                setattr(fr, name, old)
        self.assertEqual(fr.validate_plan(make_plan()).sha256, base)

    def test_rejects_invalid_plans(self):
        bad = [make_plan(clusters={}), make_plan(scenarios=[]),
               make_plan(scenarios=[{"id": "x", "kind": "weird"}]),
               make_plan(scenarios=[{"id": "x", "kind": "fault", "feature": "nope", "params": {"slow_extra_fraction": 0.1},
                                     "reps": 1, "baseline_min": 3, "fault_min": 8, "after_min": 3}]),
               make_plan(scenarios=[{"id": "x", "kind": "control", "reps": 1, "baseline_min": 3, "fault_min": 8,
                                     "after_min": 3}, {"id": "x", "kind": "control", "reps": 1, "baseline_min": 3,
                                                       "fault_min": 8, "after_min": 3}]),
               make_plan(clusters={"a": {"context": "x", "prom_port": 9151}, "b": {"context": "y", "prom_port": 9151}}),
               make_plan(bogus=1)]
        for raw in bad:
            with self.assertRaises(fr.PlanError, msg=json.dumps(raw)[:100]):
                fr.validate_plan(raw)

    def test_analysis_must_fit_the_flagger_iterations(self):
        # 14 min de análise cabem nas 16 iterações do Canary; 20 não
        with self.assertRaises(fr.PlanError):
            fr.validate_plan(make_plan(scenarios=[dict(make_plan()["scenarios"][0], after_min=9)]))


class CollectorEnvTest(unittest.TestCase):
    def test_collector_env_points_at_the_flagger_lab(self):
        env = fr.collector_env()
        self.assertEqual(env["TRIAGE_PROM_JOB"], "probe-flagger")
        self.assertEqual(env["TRIAGE_PROM_NAMESPACE"], "flagger-lab")
        self.assertEqual(env["TRIAGE_PROM_SERVICE"], "app-fl.*")


if __name__ == "__main__":
    unittest.main()
