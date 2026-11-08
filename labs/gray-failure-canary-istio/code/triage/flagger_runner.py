"""Orquestrador do teste com o Flagger real (v6). Uma execução = uma revisão do Canary.

Para cada execução o runner: espera o Canary ficar ocioso, dispara uma revisão nova (anota
o Deployment `app-fl`), espera a fase Progressing, alinha o início ao minuto, liga o coletor
(nosso detector lê o MESMO tráfego pelo job probe-flagger), injeta a falha pelo admin do pod
do canary (3 min de base, 8 de falha, 3 depois, como na avaliação v5) e registra o que o
Flagger fez: Failed (reverteu) ou Succeeded (promoveu), com o horário.

Acerto do Flagger: reverteu com horário em (t_on, t_off + 60] (mesmo critério de
`market_emul.detect`). Reverter até t_on é alarme falso antes da falha. No controle
(sem falha), qualquer reversão é falso alarme. Não há restauração a fazer: a execução só
mexe no namespace flagger-lab e a falha do admin expira sozinha (prazo obrigatório).

Uso:
  python3 flagger_runner.py dry-run|preflight|run|verify PLANO.json [--cluster a] [--confirm HASH12]
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import runner
from runner import (ADMIN_SCRIPT, FEATURE_PARAMS, Deps, KubeError, PlanError, PreflightError,
                    TooManyDiscards, nodes_ready)

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = "app-fl"
PRIMARY = "app-fl-primary"
LOADGEN = "probe-flagger"
LEAD_S = 60              # folga entre ver Progressing e o minuto de início da coleta
TTL_MARGIN_S = 60        # prazo da falha = duração + 1 min
TOLERANCE_S = 10         # divergência aceita entre o horário planejado e o do app
MAX_DISCARDS = 3
POLL_S = 10
PROGRESS_WAIT_S = 600    # espera pela fase Progressing depois do trigger
IDLE_WAIT_S = 1800       # espera por um canary ocupado antes de começar
ITERATIONS = 16          # iguais a flagger/canary.yaml (checado no teste)
THRESHOLD = 5
PATH_MAX_MS = 1000       # pré-voo: nenhuma de 10 requisições ao dashboard pode passar disso
IDLE_PHASES = ("Initialized", "Succeeded", "Failed")
TERMINAL = ("Succeeded", "Failed")


PATH_SCRIPT = (
    "import json, time, urllib.request\n"
    "ms, err = [], 0\n"
    "for _ in range(10):\n"
    "    t = time.time()\n"
    "    try:\n"
    "        urllib.request.urlopen(urllib.request.Request("
    "'http://app-fl.flagger-lab.svc.cluster.local:8080/api/v1/fast-data', "
    "headers={'X-Feature-Context': 'dashboard'}), timeout=15)\n"
    "    except Exception:\n"
    "        err += 1\n"
    "    ms.append(round((time.time() - t) * 1000))\n"
    "print(json.dumps({'max_ms': max(ms), 'errors': err}))\n"
)

# --------------------------------------------------------------------------- plano

@dataclass(frozen=True)
class FCluster:
    context: str
    prom_port: int


@dataclass(frozen=True)
class FScenario:
    id: str
    kind: str
    feature: Optional[str]
    params: Optional[dict]
    reps: int
    baseline_min: int
    fault_min: int
    after_min: int

    @property
    def total(self) -> int:
        return self.baseline_min + self.fault_min + self.after_min


@dataclass(frozen=True)
class FPlan:
    name: str
    namespace: str
    out_dir: str
    prereg: str
    clusters: Dict[str, FCluster]
    scenarios: List[FScenario]
    sha256: str
    raw: dict = field(repr=False, default_factory=dict)


def runner_constants() -> dict:
    with open(os.path.join(HERE, "flagger", "canary.yaml"), "rb") as f:
        canary_sha = hashlib.sha256(f.read()).hexdigest()
    return {"PATH_MAX_MS": PATH_MAX_MS, "LEAD_S": LEAD_S, "TTL_MARGIN_S": TTL_MARGIN_S, "TOLERANCE_S": TOLERANCE_S,
            "MAX_DISCARDS": MAX_DISCARDS, "ITERATIONS": ITERATIONS, "THRESHOLD": THRESHOLD,
            "canary_yaml_sha256": canary_sha}


def collector_env() -> dict:
    return {"TRIAGE_PROM_JOB": "probe-flagger", "TRIAGE_PROM_NAMESPACE": "flagger-lab",
            "TRIAGE_PROM_SERVICE": "app-fl.*"}


def _int(v, name, lo=1):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise PlanError(f"{name}: inteiro >= {lo} esperado")
    return v


def validate_plan(raw: dict) -> FPlan:
    if not isinstance(raw, dict):
        raise PlanError("o plano precisa ser um objeto JSON")
    extra = sorted(set(raw) - {"name", "namespace", "out_dir", "prereg", "clusters", "scenarios"})
    if extra:
        raise PlanError(f"chaves desconhecidas no plano: {extra}")
    for k in ("name", "out_dir", "clusters", "scenarios"):
        if k not in raw:
            raise PlanError(f"falta a chave {k}")
    if not raw["clusters"] or not isinstance(raw["clusters"], dict):
        raise PlanError("clusters: pelo menos um")
    clusters, ports = {}, set()
    for c, v in raw["clusters"].items():
        if set(v) != {"context", "prom_port"}:
            raise PlanError(f"cluster {c}: chaves context e prom_port")
        port = _int(v["prom_port"], "prom_port")
        if port in ports:
            raise PlanError(f"prom_port {port} repetido")
        ports.add(port)
        clusters[c] = FCluster(str(v["context"]), port)
    if not raw["scenarios"]:
        raise PlanError("scenarios: pelo menos um")
    scs, seen = [], set()
    for s in raw["scenarios"]:
        sid = s.get("id")
        if not sid or sid in seen:
            raise PlanError(f"id de cenário ausente ou repetido: {sid!r}")
        seen.add(sid)
        kind = s.get("kind")
        common = {"id", "kind", "reps", "baseline_min", "fault_min", "after_min"}
        if kind == "control":
            if set(s) - common:
                raise PlanError(f"{sid}: chaves inválidas para control")
            feat, params = None, None
        elif kind == "fault":
            if set(s) - common - {"feature", "params"}:
                raise PlanError(f"{sid}: chaves inválidas para fault")
            feat = s.get("feature")
            if feat not in FEATURE_PARAMS:
                raise PlanError(f"{sid}: feature {feat!r} desconhecida")
            params = s.get("params") or {}
            if set(params) - set(FEATURE_PARAMS[feat]):
                raise PlanError(f"{sid}: parâmetros fora de {FEATURE_PARAMS[feat]}")
            if not any(params.get(k, 0) for k in FEATURE_PARAMS[feat]):
                raise PlanError(f"{sid}: falha vazia")
            params = dict(params)
        else:
            raise PlanError(f"{sid}: kind precisa ser fault ou control")
        sc = FScenario(sid, kind, feat, params, _int(s.get("reps"), f"{sid}.reps"),
                       _int(s.get("baseline_min"), f"{sid}.baseline_min"),
                       _int(s.get("fault_min"), f"{sid}.fault_min"),
                       _int(s.get("after_min"), f"{sid}.after_min", 0))
        if sc.total > ITERATIONS:
            raise PlanError(f"{sid}: {sc.total} min de análise não cabem nas {ITERATIONS} iterações do Canary")
        scs.append(sc)
    canon = json.dumps({"plan": {k: v for k, v in raw.items() if k != "out_dir"}, "runner": runner_constants()},
                       sort_keys=True, separators=(",", ":"))
    return FPlan(raw["name"], raw.get("namespace", "flagger-lab"), raw["out_dir"], raw.get("prereg", ""),
                 clusters, scs, hashlib.sha256(canon.encode()).hexdigest(), raw)


def load_plan(path: str) -> FPlan:
    with open(path, encoding="utf-8") as f:
        plan = validate_plan(json.load(f))
    if not os.path.isabs(plan.out_dir):
        from dataclasses import replace
        plan = replace(plan, out_dir=os.path.join(os.path.dirname(HERE), plan.out_dir))
    return plan


def summarize(plan: FPlan, cluster: str) -> dict:
    per = []
    for s in plan.scenarios:
        per.append({"id": s.id, "runs": s.reps, "minutes": round(s.reps * (s.total + 6), 1)})
    return {"cluster": cluster, "runs": sum(p["runs"] for p in per),
            "total_min": round(sum(p["minutes"] for p in per), 1), "scenarios": per}


# ------------------------------------------------------------------------ cluster

def admin_call(kube, method: str, body: Optional[dict] = None) -> dict:
    out = kube.run("exec", f"deploy/{TARGET}", "-c", "app", "--", "python3", "-c", ADMIN_SCRIPT, method,
                   "" if body is None else json.dumps(body))
    try:
        return json.loads(out)
    except ValueError:
        raise KubeError(f"resposta inválida do admin: {out[:100]!r}")


def _epoch(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def canary_status(kube) -> dict:
    st = json.loads(kube.run("get", "canary", TARGET, "-o", "json")).get("status", {})
    ts = st.get("lastTransitionTime") or (st.get("conditions") or [{}])[0].get("lastTransitionTime")
    return {"phase": st.get("phase", ""), "failed_checks": st.get("failedChecks", 0),
            "iterations": st.get("iterations", 0), "transition": _epoch(ts) if ts else None}


def _deploy(kube, name: str, ns: Optional[str] = None) -> dict:
    args = ["get", "deploy", name, "-o", "json"] + (["-n", ns] if ns else [])
    d = json.loads(kube.run(*args))
    return {"replicas": d["spec"].get("replicas", 0), "ready": d.get("status", {}).get("readyReplicas", 0)}


def preflight_failures(plan: FPlan, cluster: str, kube, deps: Deps) -> List[str]:
    bad = []

    def chk(ok, msg):
        if not ok:
            bad.append(msg)
    try:
        chk(nodes_ready(kube), "nó NotReady ou sem nó")
        p, t, g = _deploy(kube, PRIMARY), _deploy(kube, TARGET), _deploy(kube, LOADGEN)
        st = canary_status(kube)
        pods = json.loads(kube.run("get", "pods", "-n", "flagger-system", "-l", "app.kubernetes.io/name=flagger",
                                   "-o", "json"))["items"]
    except (KubeError, ValueError, KeyError) as exc:
        return [f"cluster ilegível: {exc}"]
    chk(p["replicas"] == 1 and p["ready"] == 1, f"{PRIMARY}: réplicas {p['replicas']}, prontas {p['ready']} (esperado 1/1)")
    chk(t["replicas"] == 0, f"{TARGET}: réplicas {t['replicas']} (esperado 0: canary ocioso)")
    chk(g["replicas"] == 2 and g["ready"] == 2, f"{LOADGEN}: réplicas {g['replicas']}, prontas {g['ready']} (esperado 2/2)")
    chk(pods and all(x["status"].get("phase") == "Running" for x in pods), "Flagger: controlador não está Running")
    chk(st["phase"] in IDLE_PHASES, f"canary ocupado (fase {st['phase']!r})")
    # saúde do caminho: o dashboard custa ~2 ms; endpoints mortos de outro cluster (CIDRs
    # sobrepostos) faziam metade das requisições esperar o timeout de 10 s e invalidavam tudo
    try:
        pr = json.loads(kube.run("exec", f"deploy/{LOADGEN}", "-c", "probe", "--", "python3", "-c", PATH_SCRIPT))
        chk(pr["max_ms"] <= PATH_MAX_MS and pr["errors"] == 0,
            f"caminho lento ou com erro pelo Service: máximo {pr['max_ms']} ms, {pr['errors']} erros em 10 requisições")
    except (KubeError, ValueError, KeyError) as exc:
        bad.append(f"caminho não pôde ser medido: {exc}")
    pc = deps.prom_check(cluster)
    chk(pc.get("up"), "Prometheus inacessível")
    chk(pc.get("retention_s", 0) >= runner.MIN_RETENTION_S,
        f"retenção do Prometheus {pc.get('retention_s', 0) / 3600:.0f} h < {runner.MIN_RETENTION_S // 3600} h")
    cdir = cluster_dir(plan, cluster)
    os.makedirs(cdir, exist_ok=True)
    chk(deps.disk_free(cdir) >= runner.MIN_DISK_BYTES, "pouco espaço em disco")
    lp = runner.lock_problem(os.path.join(cdir, f".lock-{cluster}"))
    chk(lp is None, lp or "")
    if os.path.exists(os.path.join(cdir, "MANIFEST.sha256")):
        changed = runner.verify_manifest(cdir, allow_append=True)
        chk(not changed, f"manifesto divergente em {cdir}: {changed}")
    return bad


def cluster_dir(plan: FPlan, cluster: str) -> str:
    return os.path.join(plan.out_dir, cluster)


class Ctx:
    def __init__(self, plan: FPlan, cluster: str, deps: Deps):
        self.plan, self.cluster, self.deps = plan, cluster, deps
        self.cfg = plan.clusters[cluster]
        self.kube = deps.kube(self.cfg.context)
        self.dir = cluster_dir(plan, cluster)
        self.runs_path = os.path.join(self.dir, "runs.jsonl")

    def sleep_until(self, t: float) -> None:
        d = t - self.deps.now()
        if d > 0:
            self.deps.sleep(d)

    def runs(self) -> List[dict]:
        if not os.path.exists(self.runs_path):
            return []
        with open(self.runs_path, encoding="utf-8") as f:
            return [r for r in map(json.loads, filter(str.strip, f)) if r.get("cluster") == self.cluster]

    def record(self, rec: dict) -> None:
        with open(self.runs_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)


def wait_idle(ctx: Ctx, limit_s: float = IDLE_WAIT_S) -> None:
    end = ctx.deps.now() + limit_s
    while True:
        st = canary_status(ctx.kube)
        if st["phase"] in IDLE_PHASES:
            return
        if ctx.deps.now() >= end:
            raise PreflightError(f"canary ocupado (fase {st['phase']!r}) há mais de {limit_s:.0f} s")
        ctx.deps.sleep(POLL_S)


class Obs:
    """O que o Flagger fez, visto pelas leituras periódicas do status."""

    def __init__(self):
        self.terminal: Optional[dict] = None
        self.seen_at: Optional[float] = None
        self.max_failed = 0   # o status final zera failedChecks; o máximo visto fica aqui

    def update(self, st: dict, now: float) -> None:
        if st["phase"] == "Progressing":
            self.max_failed = max(self.max_failed, st["failed_checks"])
        if self.terminal is None and st["phase"] in TERMINAL:
            self.terminal, self.seen_at = st, now


def sleep_watch(ctx: Ctx, t: float, obs: Obs) -> None:
    while ctx.deps.now() < t:
        obs.update(canary_status(ctx.kube), ctx.deps.now())
        ctx.sleep_until(min(t, ctx.deps.now() + POLL_S))
    obs.update(canary_status(ctx.kube), ctx.deps.now())


def _meta(ctx: Ctx, sc: FScenario, rep: int, attempt: int, t0: float, rev: str) -> dict:
    return {"scenario": sc.id, "kind": sc.kind, "cluster": ctx.cluster, "rep": rep, "attempt": attempt,
            "params": sc.params, "plan_sha256": ctx.plan.sha256, "prereg": ctx.plan.prereg,
            "plan_name": ctx.plan.name, "t0": t0, "rev": rev, "flagger": runner_constants(),
            "prom_env": collector_env()}


def _discard(ctx, sc, rep, attempt, reason, **extra) -> dict:
    ctx.deps.log(f"[{ctx.cluster}] {sc.id} rep {rep} tentativa {attempt} DESCARTADA: {reason}")
    return {"cluster": ctx.cluster, "scenario": sc.id, "kind": sc.kind, "rep": rep, "attempt": attempt,
            "status": "discarded", "reason": reason, "plan_sha256": ctx.plan.sha256, **extra}


def run_one(ctx: Ctx, sc: FScenario, rep: int, attempt: int) -> dict:
    kube, now = ctx.kube, ctx.deps.now
    name = f"{sc.id}-r{rep:02d}-a{attempt}-{ctx.cluster}.jsonl"
    rev = f"{sc.id}-r{rep:02d}-a{attempt}-{ctx.cluster}-{int(now())}"
    base = {"file": name, "params": sc.params, "rev": rev}
    if not nodes_ready(kube):
        return _discard(ctx, sc, rep, attempt, "nó NotReady no início", **base)
    wait_idle(ctx)
    kube.run("patch", "deploy", TARGET, "--type=merge", "-p",
             json.dumps({"spec": {"template": {"metadata": {"annotations": {"bench/rev": rev}}}}}))
    deadline, t_p = now() + PROGRESS_WAIT_S, None
    while now() < deadline:
        st = canary_status(kube)
        if st["phase"] == "Progressing":
            t_p = now()
            break
        # até o Flagger notar a revisão (próximo ciclo) o status ainda é o do run anterior
        # (Failed ou Succeeded): só Progressing encerra a espera
        ctx.deps.sleep(5)
    if t_p is None:
        return _discard(ctx, sc, rep, attempt, "o canary não entrou em Progressing", **base)
    t0 = math.ceil((t_p + LEAD_S) / 60.0) * 60
    t_on = t0 + sc.baseline_min * 60
    t_off = t_on + sc.fault_min * 60
    base.update(t0=t0)
    handle = ctx.deps.start_collector(ctx.cluster, ctx.path(name), sc.total, t0, _meta(ctx, sc, rep, attempt, t0, rev))
    obs, reason, put_done, real_on, real_off, applied = Obs(), None, False, None, None, False
    try:
        sleep_watch(ctx, t_on if sc.kind == "fault" else t0 + sc.total * 60 + 5, obs)
        if sc.kind == "fault" and obs.terminal is None:
            resp = admin_call(kube, "PUT", {**sc.params, "ttl_s": sc.fault_min * 60 + TTL_MARGIN_S})
            put_done = applied = True
            if not resp.get("active") or any(resp["params"].get(k) != v for k, v in sc.params.items()):
                reason = "leitura de volta divergente logo após ligar a falha"
            elif abs((resp.get("set_at") or 0) - t_on) > TOLERANCE_S:
                # lido do pod no PUT: depois de um rollback o pod some e o histórico não dá mais
                reason = "horário da falha diverge do planejado"
            else:
                sleep_watch(ctx, t_off - 5, obs)
                if obs.terminal is None:  # depois de um rollback o pod do canary some
                    mid = admin_call(kube, "GET")
                    if not mid.get("active") or any(mid["params"].get(k) != v for k, v in sc.params.items()):
                        reason = "leitura de volta divergente antes de desligar (a falha não estava ativa)"
                sleep_watch(ctx, t_off, obs)
            end = None
            with contextlib.suppress(KubeError):
                end = admin_call(kube, "DELETE") if put_done else None
            put_done = False
            if end is not None and reason is None:
                hist = end.get("history", [])
                sets = [h for h in hist if h["event"] == "set"]
                tail = [h for h in hist if sets and h["at"] >= sets[-1]["at"] and h["event"] in ("clear", "expired")]
                if end.get("active"):
                    reason = "leitura de volta divergente: falha ainda ativa depois de desligar"
                elif not sets or not tail:
                    reason = "leitura de volta divergente: histórico sem set/clear"
                else:
                    real_on, real_off = sets[-1]["at"], tail[0]["at"]
                    if tail[0]["event"] == "expired":
                        reason = "o prazo expirou antes de o runner desligar a falha"
                    elif abs(real_on - t_on) > TOLERANCE_S or abs(real_off - t_off) > TOLERANCE_S:
                        reason = "horário da falha diverge do planejado"
        if reason is None:
            sleep_watch(ctx, t0 + sc.total * 60 + 5, obs)
    finally:
        if put_done:
            with contextlib.suppress(Exception):
                admin_call(kube, "DELETE")
    if reason is not None:
        with contextlib.suppress(Exception):
            handle.stop()
        return _discard(ctx, sc, rep, attempt, reason, **base)
    end_by = t_p + ITERATIONS * 60 + 600
    while obs.terminal is None and now() < end_by:
        ctx.deps.sleep(POLL_S)
        obs.update(canary_status(kube), now())
    res = handle.wait()
    if not nodes_ready(kube):
        return _discard(ctx, sc, rep, attempt, "nó NotReady após a execução", **base)
    st = obs.terminal or canary_status(kube)
    failed_at = None
    if st["phase"] == "Failed":
        failed_at = st["transition"] if st["transition"] else obs.seen_at
    return {"cluster": ctx.cluster, "scenario": sc.id, "kind": sc.kind, "rep": rep, "attempt": attempt,
            "status": "ok", "t0": t0, "t_on": t_on, "t_off": t_off, "file": name, "params": sc.params,
            "rev": rev, "flagger_phase": st["phase"], "flagger_failed_at": failed_at,
            "flagger_seen_at": obs.seen_at, "failed_checks": st["failed_checks"], "failed_checks_max": obs.max_failed,
            "iterations": st["iterations"],
            "flagger_before_fault": failed_at is not None and failed_at <= t_on,
            "fault_applied": applied, "real_on": real_on, "real_off": real_off,
            "missing": len(res["missing"]), "plan_sha256": ctx.plan.sha256}


def run_scenario(ctx: Ctx, sc: FScenario) -> None:
    while True:
        mine = [r for r in ctx.runs() if r["scenario"] == sc.id]
        ok = sum(r["status"] == "ok" for r in mine)
        discards = sum(r["status"] == "discarded" for r in mine)
        if ok >= sc.reps:
            return
        if discards > MAX_DISCARDS:
            raise TooManyDiscards(f"{sc.id}: {discards} execuções descartadas; veja runs.jsonl")
        rep = ok + 1
        attempt = max([r["attempt"] for r in mine if r["rep"] == rep] or [0]) + 1
        while os.path.exists(ctx.path(f"{sc.id}-r{rep:02d}-a{attempt}-{ctx.cluster}.jsonl")):
            attempt += 1
        rec = run_one(ctx, sc, rep, attempt)
        ctx.record(rec)
        ctx.deps.log(f"[{ctx.cluster}] {sc.id} rep {rep} tentativa {attempt}: {rec['status']} "
                     f"{rec.get('flagger_phase', '')}")


def run_block(plan: FPlan, cluster: str, deps: Deps) -> None:
    ctx = Ctx(plan, cluster, deps)
    os.makedirs(ctx.dir, exist_ok=True)
    lock = os.path.join(ctx.dir, f".lock-{cluster}")
    exc = None
    with deps.portforward(ctx.cfg):
        wait_idle(ctx)
        bad = preflight_failures(plan, cluster, ctx.kube, deps)
        if bad:
            raise PreflightError("pré-voo reprovado: " + "; ".join(bad))
        runner.acquire_lock(lock)
        try:
            for sc in plan.scenarios:
                run_scenario(ctx, sc)
        except BaseException as e:
            exc = e
            raise
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(lock)
            try:
                runner.write_manifest(ctx.dir)
            except Exception as e3:
                deps.log(f"[{cluster}] ERRO AO GRAVAR O MANIFESTO: {e3}")
                if exc is None:
                    raise


# ------------------------------------------------------------- implementação real

def real_deps(plan: FPlan) -> Deps:
    import subprocess
    deps = runner.real_deps(plan)

    def start_collector(cluster, out_path, minutes, start, meta):
        argv = [sys.executable, os.path.join(HERE, "collector.py"), "--prom",
                f"http://localhost:{plan.clusters[cluster].prom_port}", "--out", out_path,
                "--minutes", str(minutes), "--start", str(start), "--meta", json.dumps(meta)]
        return runner.RealHandle(subprocess.Popen(argv, stdout=subprocess.PIPE, text=True,
                                                  env={**os.environ, **collector_env()}))
    deps.start_collector = start_collector
    return deps


def main(argv=None, deps_factory=real_deps) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("dry-run", "preflight", "run", "verify"))
    ap.add_argument("target")
    ap.add_argument("--cluster")
    ap.add_argument("--confirm")
    ap.add_argument("--no-inhibit", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        bad = runner.verify_manifest(a.target)
        print("íntegro" if not bad else f"ALTERADOS: {bad}")
        return 1 if bad else 0
    plan = load_plan(a.target)
    if a.cmd == "dry-run":
        for c in plan.clusters:
            print(json.dumps(summarize(plan, c), ensure_ascii=False))
        print(f"hash do plano: {plan.sha256}  (--confirm {plan.sha256[:12]})")
        return 0
    if not a.cluster or a.cluster not in plan.clusters:
        ap.error(f"--cluster obrigatório, um de {sorted(plan.clusters)}")
    if a.cmd == "run" and a.confirm != plan.sha256[:12]:
        print(f"Recusado: confirme com --confirm {plan.sha256[:12]} (hash do plano {plan.name}).")
        return 2
    if a.cmd == "run" and not a.no_inhibit:
        wrapped = runner.inhibit_argv([sys.executable, *sys.argv])
        if wrapped:
            os.environ["RUNNER_INHIBITED"] = "1"
            os.execvp(wrapped[0], wrapped)
    deps = deps_factory(plan)
    if a.cmd == "preflight":
        with deps.portforward(plan.clusters[a.cluster]):
            bad = preflight_failures(plan, a.cluster, deps.kube(plan.clusters[a.cluster].context), deps)
        print("pré-voo OK" if not bad else "REPROVADO:\n  " + "\n  ".join(bad))
        return 1 if bad else 0
    run_block(plan, a.cluster, deps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
