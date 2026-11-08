"""Runner único das rodadas de cluster (PRE-REGISTRO v4). Um processo por cluster.

Lê um plano JSON (cenários, repetições, σ) e executa, em ordem: pré-voo (só leitura),
snapshot, mudanças, coleta e restauração. O runner NÃO conhece o detector: nenhuma
execução é descartada por detectar ou não detectar.

Guardrails (cada um tem teste em test_runner.py):
- pré-voo lista TODAS as falhas e aborta sem alterar nada (nó, env da v1 e da v2,
  HEAVY_RATIO, probes, triage-agent, admin ocioso, retenção, Prometheus, disco, lock);
- snapshot do estado limpo gravado UMA vez e nunca sobrescrito: se o runner morrer e o
  cluster ficar sujo, o pré-voo seguinte recusa em vez de fotografar o estado sujo;
- a falha vai SÓ para a v2, por /admin/fault, com prazo (falha + 60 s); quem desliga é o
  runner, o prazo é a rede de segurança;
- leitura de volta após ligar, antes de desligar e depois de desligar;
- horários de verdade vêm do histórico do próprio app (set/clear/expired);
- restauração por `restore_from_snapshot`, o mesmo código no fim normal, no erro e no
  subcomando `restore` (runner morto à força);
- `run` só executa com --confirm igual ao início do hash do plano;
- manifesto sha256 dos dados ao fim de cada bloco, verificado no início do seguinte;
  saída em OUT/<cluster>/ (um diretório por cluster).

Descarte (PRE-REGISTRO): leitura de volta divergente; nó NotReady; mais de 2 janelas
inválidas na faixa de falha (rótulos em (t_on, t_off]; ver `in_fault`). No CONTROLE não se descarta por janelas faltando (15 h
perdidas por um solavanco de 3 min): o número de janelas válidas é a exposição, e o
coletor idempotente preenche lacunas ao retomar.

O caminho real (RealKube, coletor em subprocesso, port-forward) só é exercitável no
cluster: o piloto B1 é descartável por desenho.

Uso:
  python3 runner.py dry-run PLANO.json
  python3 runner.py preflight PLANO.json --cluster a
  python3 runner.py run PLANO.json --cluster a --confirm <12 primeiros hex do hash>
  python3 runner.py restore PLANO.json --cluster a
  python3 runner.py verify DIRETORIO_DE_SAIDA
"""
import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
SETTLE_S = 75           # após cada rollout, a 1ª janela vem contaminada
LEAD_S = 60             # folga para alinhar o início ao próximo minuto
TTL_MARGIN_S = 60       # prazo da falha = duração + 1 min
MAX_MISSING_IN_FAULT = 2
MAX_DISCARDS = 3        # por cenário; acima disso o bloco para
MIN_RETENTION_S = 72 * 3600
MIN_DISK_BYTES = 2 * 1024 ** 3
TOLERANCE_S = 10        # divergência aceita entre o horário planejado e o do app
FAULT_HEAVY_RATIO = "0.3"  # HEAVY_RATIO das execuções com falha (o controle usa o original)
MANAGED = ("app-service-v1", "app-service-v2", "probe-generator", "triage-agent")
# Só estas variáveis são mexidas pelo runner. A restauração se limita a elas; qualquer outra
# deriva é avisada e NUNCA alterada (pode ser mudança deliberada do operador).
RUNNER_KEYS = {"probe-generator": ("HEAVY_RATIO",),
               "app-service-v1": ("SLOW_JITTER_SIGMA",), "app-service-v2": ("SLOW_JITTER_SIGMA",)}
PARTIAL_VARS = ("SLOW_EXTRA_FRACTION", "SLOW_EXTRA_S", "FAST_DELAY_FRACTION", "FAST_DELAY_S")
FEATURE_PARAMS = {"heavy-reports": ("slow_extra_fraction", "slow_extra_s"),
                  "dashboard": ("fast_delay_fraction", "fast_delay_s")}
ADMIN_SCRIPT = (
    "import sys, urllib.request, urllib.error\n"
    "m, b = sys.argv[1], sys.argv[2]\n"
    "req = urllib.request.Request('http://127.0.0.1:8081/admin/fault', data=(b.encode() if b else None), method=m)\n"
    "try:\n"
    "    with urllib.request.urlopen(req, timeout=10) as r:\n"
    "        print(r.read().decode())\n"
    "except urllib.error.HTTPError as e:\n"
    "    print(e.read().decode())\n"
    "    sys.exit(1)\n"
)


class KubeError(RuntimeError):
    pass


class PlanError(ValueError):
    pass


class PreflightError(RuntimeError):
    pass


class TooManyDiscards(RuntimeError):
    pass


# --------------------------------------------------------------------------- plano

@dataclass(frozen=True)
class ClusterCfg:
    context: str
    prom_port: int
    heavy_ratio_original: str


@dataclass(frozen=True)
class Scenario:
    id: str
    kind: str
    feature: Optional[str] = None
    params: Optional[dict] = None
    reps: int = 1
    baseline_min: int = 0
    fault_min: int = 0
    after_min: int = 0
    minutes: int = 0
    heavy_ratio: Optional[str] = None


@dataclass(frozen=True)
class Plan:
    name: str
    namespace: str
    out_dir: str
    prereg: str
    clusters: Dict[str, ClusterCfg]
    sigma: Optional[float]
    scenarios: List[Scenario]
    sha256: str
    raw: dict = field(repr=False, default_factory=dict)


def _int(v, name, lo=1):
    if isinstance(v, bool) or not isinstance(v, int) or v < lo:
        raise PlanError(f"{name}: inteiro >= {lo} esperado")
    return v


def runner_constants() -> dict:
    """Regras de descarte e condição das falhas; lidas na chamada (vão para o hash e a meta)."""
    return {"TOLERANCE_S": TOLERANCE_S, "SETTLE_S": SETTLE_S, "MAX_MISSING_IN_FAULT": MAX_MISSING_IN_FAULT,
            "MAX_DISCARDS": MAX_DISCARDS, "FAULT_HEAVY_RATIO": FAULT_HEAVY_RATIO}


def validate_plan(raw: dict) -> Plan:
    if not isinstance(raw, dict):
        raise PlanError("o plano precisa ser um objeto JSON")
    extra = sorted(set(raw) - {"name", "namespace", "out_dir", "prereg", "clusters", "sigma", "scenarios"})
    if extra:
        raise PlanError(f"chaves desconhecidas no plano: {extra}")
    for k in ("name", "out_dir", "clusters", "scenarios"):
        if k not in raw:
            raise PlanError(f"falta a chave {k}")
    if not raw["clusters"] or not isinstance(raw["clusters"], dict):
        raise PlanError("clusters: pelo menos um")
    clusters = {}
    for c, v in raw["clusters"].items():
        if set(v) != {"context", "prom_port", "heavy_ratio_original"}:
            raise PlanError(f"cluster {c}: chaves context, prom_port e heavy_ratio_original")
        clusters[c] = ClusterCfg(str(v["context"]), _int(v["prom_port"], "prom_port"), str(v["heavy_ratio_original"]))
    sigma = raw.get("sigma")
    if sigma is not None and (isinstance(sigma, bool) or not isinstance(sigma, (int, float)) or sigma <= 0):
        raise PlanError("sigma: número > 0 ou null")
    scs, seen = [], set()
    if not raw["scenarios"]:
        raise PlanError("scenarios: pelo menos um")
    for s in raw["scenarios"]:
        sid = s.get("id")
        if not sid or sid in seen:
            raise PlanError(f"id de cenário ausente ou repetido: {sid!r}")
        seen.add(sid)
        kind = s.get("kind")
        if kind == "control":
            if set(s) - {"id", "kind", "minutes", "heavy_ratio"}:
                raise PlanError(f"{sid}: chaves inválidas para control")
            scs.append(Scenario(sid, kind, minutes=_int(s.get("minutes"), f"{sid}.minutes"),
                                heavy_ratio=s.get("heavy_ratio")))
        elif kind == "fault":
            if set(s) - {"id", "kind", "feature", "params", "reps", "baseline_min", "fault_min", "after_min", "heavy_ratio"}:
                raise PlanError(f"{sid}: chaves inválidas para fault")
            feat = s.get("feature")
            if feat not in FEATURE_PARAMS:
                raise PlanError(f"{sid}: feature {feat!r} desconhecida")
            params = s.get("params") or {}
            if set(params) - set(FEATURE_PARAMS[feat]):
                raise PlanError(f"{sid}: parâmetros fora de {FEATURE_PARAMS[feat]} para {feat}")
            if not any(params.get(k, 0) for k in FEATURE_PARAMS[feat]):
                raise PlanError(f"{sid}: falha vazia (todos os parâmetros em zero)")
            scs.append(Scenario(sid, kind, feat, dict(params), _int(s.get("reps"), f"{sid}.reps"),
                                _int(s.get("baseline_min"), f"{sid}.baseline_min"),
                                _int(s.get("fault_min"), f"{sid}.fault_min"),
                                _int(s.get("after_min"), f"{sid}.after_min", 0), heavy_ratio=s.get("heavy_ratio")))
        else:
            raise PlanError(f"{sid}: kind precisa ser fault ou control")
    # as constantes de descarte entram no hash: mudar uma delas muda o --confirm
    canon = json.dumps({"plan": {k: v for k, v in raw.items() if k != "out_dir"}, "runner": runner_constants()},
                       sort_keys=True, separators=(",", ":"))
    return Plan(raw["name"], raw.get("namespace", "lab-apps"), raw["out_dir"], raw.get("prereg", ""),
                clusters, sigma, scs, hashlib.sha256(canon.encode()).hexdigest(), raw)


def load_plan(path: str) -> Plan:
    with open(path, encoding="utf-8") as f:
        plan = validate_plan(json.load(f))
    if not os.path.isabs(plan.out_dir):  # relativo à raiz do repositório, não ao diretório atual
        plan = replace(plan, out_dir=os.path.join(os.path.dirname(HERE), plan.out_dir))
    return plan


def summarize(plan: Plan, cluster: str) -> dict:
    """Duração estimada, sem tocar em nada."""
    per, total = [], 0.0
    if plan.sigma is not None:
        total += 2 * SETTLE_S / 60
    for s in plan.scenarios:
        if s.kind == "fault":
            m = s.reps * (s.baseline_min + s.fault_min + s.after_min + 2) + SETTLE_S / 60
            runs = s.reps
        else:
            m, runs = s.minutes + 2 + SETTLE_S / 60, 1
        per.append({"id": s.id, "runs": runs, "minutes": round(m, 1)})
        total += m
    return {"cluster": cluster, "runs": sum(p["runs"] for p in per), "total_min": round(total, 1), "scenarios": per}


# ------------------------------------------------------------------ dependências

@dataclass
class Deps:
    kube: Callable            # contexto -> objeto com .run(*args) -> str
    now: Callable[[], float]
    sleep: Callable[[float], None]
    start_collector: Callable  # (cluster, out_path, minutes, start, meta) -> handle(.wait(), .stop())
    prom_check: Callable       # cluster -> {"up": bool, "retention_s": float}
    disk_free: Callable        # caminho -> bytes livres
    log: Callable = print
    portforward: Callable = lambda cfg: contextlib.nullcontext()


class RealKube:
    def __init__(self, context: str, namespace: str):
        self.context, self.namespace = context, namespace

    def argv(self, args) -> List[str]:
        return ["kubectl", "--context", self.context, "-n", self.namespace, *args]

    def run(self, *args, timeout: int = 240) -> str:
        p = subprocess.run(self.argv(args), capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise KubeError(f"kubectl {' '.join(map(str, args))[:80]}: {(p.stdout + p.stderr).strip()[:300]}")
        return p.stdout


def admin_call(kube, version: str, method: str, body: Optional[dict] = None) -> dict:
    out = kube.run("exec", f"deploy/app-service-{version}", "-c", "app", "--", "python3", "-c",
                   ADMIN_SCRIPT, method, "" if body is None else json.dumps(body))
    try:
        return json.loads(out)
    except ValueError:
        raise KubeError(f"resposta inválida do admin: {out[:100]!r}")


# ----------------------------------------------------------------- estado do cluster

def get_deploy(kube, name: str) -> dict:
    d = json.loads(kube.run("get", "deploy", name, "-o", "json"))
    env = {e["name"]: e.get("value", "") for e in d["spec"]["template"]["spec"]["containers"][0].get("env", [])}
    return {"env": env, "replicas": d["spec"].get("replicas", 0), "ready": d.get("status", {}).get("readyReplicas", 0)}


def nodes_ready(kube) -> bool:
    items = json.loads(kube.run("get", "nodes", "-o", "json"))["items"]
    return bool(items) and all(
        any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"]) for n in items)


def take_snapshot(kube) -> dict:
    ds = {n: get_deploy(kube, n) for n in MANAGED}
    return {"deployments": {n: d["env"] for n, d in ds.items()}, "replicas": {n: d["replicas"] for n, d in ds.items()}}


def diff_snapshot(a: dict, b: dict, managed_only: bool = False) -> List[str]:
    out = []
    for n in sorted(set(a["deployments"]) | set(b["deployments"])):
        ea, eb = a["deployments"].get(n, {}), b["deployments"].get(n, {})
        for k in sorted(set(ea) | set(eb)):
            if managed_only and k not in RUNNER_KEYS.get(n, ()):
                continue
            if ea.get(k) != eb.get(k):
                out.append(f"{n}: {k} {ea.get(k)!r} -> {eb.get(k)!r}")
        if not managed_only and a["replicas"].get(n) != b["replicas"].get(n):
            out.append(f"{n}: replicas {a['replicas'].get(n)} -> {b['replicas'].get(n)}")
    return out


def _set_env(kube, name: str, *pairs: str) -> None:
    kube.run("set", "env", f"deploy/{name}", *pairs)
    kube.run("rollout", "status", f"deploy/{name}", "--timeout=180s")


def cluster_dir(plan: Plan, cluster: str) -> str:
    """Um diretório por cluster: os blocos rodam em paralelo e cada um tem runs.jsonl,
    estado, lock e manifesto próprios (um manifesto comum pegaria arquivos do outro
    cluster ainda em escrita)."""
    return os.path.join(plan.out_dir, cluster)


def journal_path(plan: Plan, cluster: str) -> str:
    return os.path.join(cluster_dir(plan, cluster), f".rollouts-{cluster}.jsonl")


def journal_rollout(plan: Plan, cluster: str, at: float, name: str, pairs) -> None:
    """Registra todo set env (rollout) do runner, inclusive o da restauração. A retomada de
    um controle usa este diário para saber se a condição mudou desde o t0."""
    os.makedirs(cluster_dir(plan, cluster), exist_ok=True)
    with open(journal_path(plan, cluster), "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": at, "deploy": name, "pairs": list(pairs)}) + "\n")


def rollouts_since(plan: Plan, cluster: str, t: float) -> List[dict]:
    p = journal_path(plan, cluster)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in map(json.loads, filter(str.strip, f)) if r["at"] >= t]


def snapshot_path(plan: Plan, cluster: str) -> str:
    return os.path.join(cluster_dir(plan, cluster), f"snapshot-pre-{cluster}.json")


def restore_from_snapshot(deps: Deps, plan: Plan, cluster: str) -> List[str]:
    """Devolve ao snapshot SÓ o que o runner gerencia (RUNNER_KEYS e o admin).

    Retorna as diferenças que restarem nessas chaves ([] = ok). Deriva em outras variáveis
    é registrada no log e não é alterada."""
    with open(snapshot_path(plan, cluster), encoding="utf-8") as f:
        snap = json.load(f)
    kube = deps.kube(plan.clusters[cluster].context)
    cur = take_snapshot(kube)
    for name, want in snap["deployments"].items():
        have = cur["deployments"].get(name, {})
        keys = RUNNER_KEYS.get(name, ())
        changes = ([f"{k}-" for k in keys if k in have and k not in want]
                   + [f"{k}={want[k]}" for k in keys if k in want and have.get(k) != want[k]])
        if changes:
            journal_rollout(plan, cluster, deps.now(), name, changes)
            _set_env(kube, name, *changes)
    for ver in ("v1", "v2"):
        if admin_call(kube, ver, "GET").get("active"):
            admin_call(kube, ver, "DELETE")
    final = take_snapshot(kube)
    drift = [d for d in diff_snapshot(snap, final) if d not in diff_snapshot(snap, final, managed_only=True)]
    if drift:
        deps.log(f"[{cluster}] deriva fora do escopo do runner (não alterada): {drift}")
    return diff_snapshot(snap, final, managed_only=True)


# ---------------------------------------------------------------------- pré-voo

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_problem(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except ValueError:
        return f"lock {path} ilegível"
    return f"lock {path} em uso pelo pid {pid}" if _pid_alive(pid) else None


def acquire_lock(path: str) -> None:
    if lock_problem(path):
        raise PreflightError(lock_problem(path))
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)  # lock de pid morto
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise PreflightError(f"lock {path} criado por outro runner agora")
    with os.fdopen(fd, "w") as f:
        f.write(str(os.getpid()))


def preflight_failures(plan: Plan, cluster: str, kube, deps: Deps) -> List[str]:
    cfg, bad = plan.clusters[cluster], []

    def chk(ok, msg):
        if not ok:
            bad.append(msg)

    try:
        chk(nodes_ready(kube), "nó NotReady ou sem nó")
        dep = {n: get_deploy(kube, n) for n in MANAGED}
    except (KubeError, ValueError, KeyError) as exc:
        return [f"cluster ilegível: {exc}"]
    for n in ("app-service-v1", "app-service-v2", "probe-generator"):
        chk(dep[n]["ready"] == dep[n]["replicas"] and dep[n]["replicas"] > 0, f"{n}: pods não prontos")
    for n in ("app-service-v1", "app-service-v2"):  # kubectl exec deploy/ fala com um pod só
        chk(dep[n]["replicas"] == 1, f"{n}: replicas={dep[n]['replicas']} (esperado 1: o admin é por pod)")
    chk(dep["triage-agent"]["replicas"] == 0, "triage-agent com réplicas > 0 (conflita com a medição)")
    for ver, n in (("v1", "app-service-v1"), ("v2", "app-service-v2")):
        env = dep[n]["env"]
        if env.get("SLOW_DELAY_S") != "3":
            bad.append(f"{n}: SLOW_DELAY_S={env.get('SLOW_DELAY_S')!r} (esperado '3')")
        if env.get("FAST_ERROR_RATE", "0") != "0":
            bad.append(f"{n}: FAST_ERROR_RATE={env['FAST_ERROR_RATE']!r} (esperado 0)")
        if "SLOW_JITTER_SIGMA" in env:
            bad.append(f"{n}: SLOW_JITTER_SIGMA presente ({env['SLOW_JITTER_SIGMA']}) antes do início; rode restore")
        for v in PARTIAL_VARS:
            if ver == "v1" and v in env:
                bad.append(f"{n}: {v} presente na v1 (a v1 nunca recebe injeção)")
            elif ver == "v2" and float(env.get(v, "0") or 0) != 0:
                bad.append(f"{n}: {v}={env[v]} deixado ligado na v2")
    pg = dep["probe-generator"]["env"]
    chk(pg.get("HEAVY_RATIO") == cfg.heavy_ratio_original,
        f"HEAVY_RATIO={pg.get('HEAVY_RATIO')!r} difere do original do plano {cfg.heavy_ratio_original!r}")
    chk(pg.get("PROBE_INTERVAL") == "1", f"PROBE_INTERVAL={pg.get('PROBE_INTERVAL')!r} (esperado '1')")
    chk(pg.get("WORKERS") == "8", f"WORKERS={pg.get('WORKERS')!r} (esperado '8')")
    for ver in ("v1", "v2"):
        try:
            a = admin_call(kube, ver, "GET")
            chk(not a.get("active"), f"admin da {ver} com falha ativa")
            chk(isinstance(a.get("changes"), int), f"admin da {ver} sem contador de mudanças (app antigo; aplique C0)")
            # o histórico da v2 persiste no pod entre execuções; o da v1 tem de estar sempre vazio
            chk(ver == "v2" or not a.get("history"), "admin da v1 tem histórico: a v1 nunca recebe falha")
        except KubeError as exc:
            bad.append(f"admin da {ver} inacessível: {exc}")
    pc = deps.prom_check(cluster)
    chk(pc.get("up"), "Prometheus inacessível")
    chk(pc.get("retention_s", 0) >= MIN_RETENTION_S,
        f"retenção do Prometheus {pc.get('retention_s', 0) / 3600:.0f} h < {MIN_RETENTION_S // 3600} h")
    cdir = cluster_dir(plan, cluster)
    os.makedirs(cdir, exist_ok=True)
    chk(deps.disk_free(cdir) >= MIN_DISK_BYTES, "pouco espaço em disco")
    lp = lock_problem(os.path.join(cdir, f".lock-{cluster}"))
    chk(lp is None, lp or "")
    if os.path.exists(os.path.join(cdir, "MANIFEST.sha256")):
        changed = verify_manifest(cdir, allow_append=True)
        chk(not changed, f"manifesto divergente em {cdir}: {changed}")
    return bad


# ------------------------------------------------------------------- execução

class Ctx:
    def __init__(self, plan, cluster, deps):
        self.plan, self.cluster, self.deps = plan, cluster, deps
        self.cfg = plan.clusters[cluster]
        self.kube = deps.kube(self.cfg.context)
        self.changed = False
        self.dir = cluster_dir(plan, cluster)
        self.runs_path = os.path.join(self.dir, "runs.jsonl")

    def set_env(self, name, *pairs):
        self.changed = True
        journal_rollout(self.plan, self.cluster, self.deps.now(), name, pairs)
        _set_env(self.kube, name, *pairs)

    def sleep_until(self, t):
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


def conditions(kube) -> dict:
    """Condição real lida do cluster no início da execução (não a pedida pelo plano)."""
    env = {n: get_deploy(kube, n)["env"] for n in ("probe-generator", "app-service-v1", "app-service-v2")}
    return {"heavy_ratio": env["probe-generator"].get("HEAVY_RATIO"),
            "sigma_v1": env["app-service-v1"].get("SLOW_JITTER_SIGMA"),
            "sigma_v2": env["app-service-v2"].get("SLOW_JITTER_SIGMA")}


def _meta(ctx, sc, rep, attempt, t0, resumed=False) -> dict:
    return {"scenario": sc.id, "kind": sc.kind, "cluster": ctx.cluster, "rep": rep, "attempt": attempt,
            "sigma": ctx.plan.sigma, "params": sc.params, "plan_sha256": ctx.plan.sha256,
            "prereg": ctx.plan.prereg, "plan_name": ctx.plan.name, "t0": t0, "resumed": resumed,
            "conditions": conditions(ctx.kube), "runner_constants": runner_constants()}


def _aligned_start(ctx) -> float:
    return math.ceil((ctx.deps.now() + LEAD_S) / 60.0) * 60


def _discard(ctx, sc, rep, attempt, reason, **extra) -> dict:
    ctx.deps.log(f"[{ctx.cluster}] {sc.id} rep {rep} tentativa {attempt} DESCARTADA: {reason}")
    return {"cluster": ctx.cluster, "scenario": sc.id, "kind": sc.kind, "rep": rep, "attempt": attempt,
            "status": "discarded", "reason": reason, "plan_sha256": ctx.plan.sha256, **extra}


def in_fault(label: float, t_on: float, t_off: float) -> bool:
    """Convenção de rótulo (vale também na Fase 2): a janela de rótulo m é o increase[1m]
    avaliado em m e cobre [m-60, m). Com a falha em [t_on, t_off), as janelas com falha são
    os rótulos em (t_on, t_off]; o rótulo t_on ainda é baseline."""
    return t_on < label <= t_off


def run_fault(ctx: Ctx, sc: Scenario, rep: int, attempt: int) -> dict:
    kube, now = ctx.kube, ctx.deps.now
    t0 = _aligned_start(ctx)
    t_on = t0 + sc.baseline_min * 60
    t_off = t_on + sc.fault_min * 60
    total = sc.baseline_min + sc.fault_min + sc.after_min
    name = f"{sc.id}-r{rep:02d}-a{attempt}-{ctx.cluster}.jsonl"
    out = ctx.path(name)
    base = {"t0": t0, "file": name, "params": sc.params, "expired": False}
    if not nodes_ready(kube):
        return _discard(ctx, sc, rep, attempt, "nó NotReady no início", **base)
    handle = ctx.deps.start_collector(ctx.cluster, out, total, t0, _meta(ctx, sc, rep, attempt, t0))
    reason, put_done, real_on, real_off, expired = None, False, None, None, False
    try:
        ctx.sleep_until(t_on)
        ctx.changed = True  # a falha é uma mudança: o bloco precisa restaurar mesmo sem set env
        resp = admin_call(kube, "v2", "PUT", {**sc.params, "ttl_s": sc.fault_min * 60 + TTL_MARGIN_S})
        put_done = True
        if not resp.get("active") or any(resp["params"].get(k) != v for k, v in sc.params.items()):
            reason = "leitura de volta divergente logo após ligar a falha"
        else:
            ctx.sleep_until(t_off - 5)
            mid = admin_call(kube, "v2", "GET")
            if not mid.get("active") or any(mid["params"].get(k) != v for k, v in sc.params.items()):
                reason = "leitura de volta divergente antes de desligar (a falha não estava ativa)"
            else:
                ctx.sleep_until(t_off)
        end = admin_call(kube, "v2", "DELETE") if put_done else None
        put_done = False
        if end is not None:
            if end.get("active"):
                reason = reason or "leitura de volta divergente: falha ainda ativa depois de desligar"
            hist = end.get("history", [])
            sets = [h for h in hist if h["event"] == "set"]
            if sets:
                real_on = sets[-1]["at"]
                tail = [h for h in hist if h["at"] >= real_on and h["event"] in ("clear", "expired")]
                if tail:
                    real_off = tail[0]["at"]
                    expired = tail[0]["event"] == "expired"
            if reason is None:
                if real_on is None or real_off is None:
                    reason = "leitura de volta divergente: histórico sem set/clear"
                elif expired:
                    reason = "o prazo expirou antes de o runner desligar a falha"
                elif abs(real_on - t_on) > TOLERANCE_S or abs(real_off - t_off) > TOLERANCE_S:
                    reason = "horário da falha diverge do planejado"
        v1 = admin_call(kube, "v1", "GET")
        if reason is None and (v1.get("active") or v1.get("history")):
            reason = "a v1 recebeu falha (nunca pode)"
    finally:
        if put_done:  # erro no meio: não deixar a falha ligada
            with contextlib.suppress(Exception):
                admin_call(kube, "v2", "DELETE")
    if reason is not None:
        with contextlib.suppress(Exception):
            handle.stop()
        return _discard(ctx, sc, rep, attempt, reason, **{**base, "expired": expired})
    ctx.sleep_until(t0 + total * 60 + 5)
    res = handle.wait()
    if not nodes_ready(kube):
        return _discard(ctx, sc, rep, attempt, "nó NotReady após a execução", **base)
    miss = [m for m in res["missing"] if in_fault(m, t_on, t_off)]
    if len(miss) > MAX_MISSING_IN_FAULT:
        return _discard(ctx, sc, rep, attempt,
                        f"{len(miss)} janelas inválidas na faixa de falha (máximo {MAX_MISSING_IN_FAULT})", **base)
    return {"cluster": ctx.cluster, "scenario": sc.id, "kind": "fault", "rep": rep, "attempt": attempt,
            "status": "ok", "t0": t0, "t_on": real_on, "t_off": real_off, "expired": False,
            "params": sc.params, "file": name, "missing": len(res["missing"]), "missing_in_fault": len(miss),
            "plan_sha256": ctx.plan.sha256}


def _resume_problem(ctx: Ctx, st: dict) -> Optional[str]:
    if not isinstance(st.get("hist0"), dict) or "created" not in st:
        return "estado sem hist0 (formato antigo)"
    since = rollouts_since(ctx.plan, ctx.cluster, st["created"])
    if since:
        return f"{len(since)} rollout(s) desde o t0 ({', '.join(sorted({r['deploy'] for r in since}))})"
    for ver in ("v1", "v2"):
        if admin_call(ctx.kube, ver, "GET").get("changes") != st["hist0"][ver]:
            return f"admin da {ver} mudou desde o t0"
    return None


def run_control(ctx: Ctx, sc: Scenario, attempt: int) -> dict:
    kube = ctx.kube
    name = f"{sc.id}-a{attempt}-{ctx.cluster}.jsonl"
    state = ctx.path(f".state-{sc.id}-a{attempt}-{ctx.cluster}.json")
    resumed = os.path.exists(state)
    if resumed:  # retomada: mesma grade de minutos; o coletor preenche a lacuna
        with open(state, encoding="utf-8") as f:
            st = json.load(f)
        t0, hist0 = st["t0"], st.get("hist0")
        why = _resume_problem(ctx, st)
        if why:  # a condição mudou desde o t0: a exposição não é homogênea
            os.unlink(state)
            return _discard(ctx, sc, 1, attempt, f"retomada inválida: {why}", t0=t0, file=name)
    else:
        t0 = _aligned_start(ctx)
        # contador monotônico: o histórico é cortado em 50 e len(history) para de crescer
        hist0 = {ver: admin_call(kube, ver, "GET")["changes"] for ver in ("v1", "v2")}
        with open(state, "w") as f:
            json.dump({"t0": t0, "hist0": hist0, "created": ctx.deps.now()}, f)
    if not nodes_ready(kube):
        return _discard(ctx, sc, 1, attempt, "nó NotReady no início", t0=t0, file=name)
    handle = ctx.deps.start_collector(ctx.cluster, ctx.path(name), sc.minutes, t0,
                                      _meta(ctx, sc, 1, attempt, t0, resumed))
    ctx.sleep_until(t0 + sc.minutes * 60 + 5)
    reason = None
    for ver in ("v1", "v2"):
        a = admin_call(kube, ver, "GET")
        if a.get("active") or a.get("changes") != hist0[ver]:
            reason = f"a falha foi ligada na {ver} durante o controle"
    if not nodes_ready(kube):
        reason = reason or "nó NotReady após a execução"
    res = handle.wait()
    if reason:
        return _discard(ctx, sc, 1, attempt, reason, t0=t0, file=name)
    os.unlink(state)
    return {"cluster": ctx.cluster, "scenario": sc.id, "kind": "control", "rep": 1, "attempt": attempt,
            "status": "ok", "t0": t0, "minutes": sc.minutes, "file": name, "missing": len(res["missing"]),
            "plan_sha256": ctx.plan.sha256}


def run_scenario(ctx: Ctx, sc: Scenario) -> None:
    want = sc.heavy_ratio or (ctx.cfg.heavy_ratio_original if sc.kind == "control" else FAULT_HEAVY_RATIO)
    if get_deploy(ctx.kube, "probe-generator")["env"].get("HEAVY_RATIO") != want:
        ctx.set_env("probe-generator", f"HEAVY_RATIO={want}")
        ctx.deps.sleep(SETTLE_S)
    reps = sc.reps if sc.kind == "fault" else 1
    while True:
        mine = [r for r in ctx.runs() if r["scenario"] == sc.id]
        ok = sum(r["status"] == "ok" for r in mine)
        discards = sum(r["status"] == "discarded" for r in mine)
        if ok >= reps:
            return
        if discards > MAX_DISCARDS:
            raise TooManyDiscards(f"{sc.id}: {discards} execuções descartadas; veja runs.jsonl")
        rep = ok + 1
        attempt = max([r["attempt"] for r in mine if r["rep"] == rep] or [0]) + 1
        if sc.kind == "fault":
            while os.path.exists(ctx.path(f"{sc.id}-r{rep:02d}-a{attempt}-{ctx.cluster}.jsonl")):
                attempt += 1  # dados de uma tentativa interrompida não são reaproveitados
            rec = run_fault(ctx, sc, rep, attempt)
        else:
            rec = run_control(ctx, sc, attempt)
        ctx.record(rec)
        ctx.deps.log(f"[{ctx.cluster}] {sc.id} rep {rep} tentativa {attempt}: {rec['status']}")


def run_block(plan: Plan, cluster: str, deps: Deps) -> None:
    ctx = Ctx(plan, cluster, deps)
    os.makedirs(ctx.dir, exist_ok=True)
    lock = os.path.join(ctx.dir, f".lock-{cluster}")
    exc = None
    with deps.portforward(ctx.cfg):
        bad = preflight_failures(plan, cluster, ctx.kube, deps)
        if bad:
            raise PreflightError("pré-voo reprovado: " + "; ".join(bad))
        acquire_lock(lock)
        try:
            sp = snapshot_path(plan, cluster)
            if not os.path.exists(sp):  # nunca sobrescrever: o estado limpo é o de antes de tudo
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump({"cluster": cluster, **take_snapshot(ctx.kube)}, f, indent=1, sort_keys=True)
            if plan.sigma is not None:
                for n in ("app-service-v1", "app-service-v2"):
                    ctx.set_env(n, f"SLOW_JITTER_SIGMA={plan.sigma}")
                deps.sleep(SETTLE_S)
                got = {n: get_deploy(ctx.kube, n)["env"].get("SLOW_JITTER_SIGMA")
                       for n in ("app-service-v1", "app-service-v2")}
                if set(got.values()) != {str(plan.sigma)}:
                    raise PreflightError(f"SLOW_JITTER_SIGMA divergente entre as versões: {got}")
            for sc in plan.scenarios:
                run_scenario(ctx, sc)
        except BaseException as e:
            exc = e
            raise
        finally:
            try:
                if ctx.changed:
                    diffs = restore_from_snapshot(deps, plan, cluster)
                    if diffs:
                        deps.log(f"[{cluster}] RESTAURAÇÃO INCOMPLETA: {diffs}")
                        if exc is None:
                            raise RuntimeError(f"restauração incompleta: {diffs}")
            except Exception as e2:
                deps.log(f"[{cluster}] ERRO NA RESTAURAÇÃO: {e2}")
                if exc is None:
                    raise
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(lock)
                try:
                    write_manifest(ctx.dir)
                except Exception as e3:  # sem manifesto o bloco não pode passar por íntegro
                    deps.log(f"[{cluster}] ERRO AO GRAVAR O MANIFESTO: {e3}")
                    if exc is None:
                        raise


# ----------------------------------------------------------- manifesto e host

SIZES = ".manifest-sizes.json"  # tamanho de cada arquivo no manifesto (checagem de prefixo)


def _sha(path: str, size: Optional[int] = None) -> str:
    """sha256 do arquivo inteiro, ou só dos primeiros `size` bytes."""
    h, left = hashlib.sha256(), size
    with open(path, "rb") as f:
        while left is None or left > 0:
            chunk = f.read(1 << 20 if left is None else min(1 << 20, left))
            if not chunk:
                break
            h.update(chunk)
            if left is not None:
                left -= len(chunk)
    return h.hexdigest()


def _data_files(d: str) -> List[str]:
    return sorted(n for n in os.listdir(d)
                  if not n.startswith(".") and n != "MANIFEST.sha256" and os.path.isfile(os.path.join(d, n)))


def write_manifest(out_dir: str) -> str:
    path = os.path.join(out_dir, "MANIFEST.sha256")
    names = _data_files(out_dir)
    with open(path, "w", encoding="utf-8") as f:
        for n in names:
            f.write(f"{_sha(os.path.join(out_dir, n))}  {n}\n")
    with open(os.path.join(out_dir, SIZES), "w", encoding="utf-8") as f:
        json.dump({n: os.path.getsize(os.path.join(out_dir, n)) for n in names}, f, sort_keys=True)
    return path


def verify_manifest(out_dir: str, allow_append: bool = False) -> List[str]:
    """Arquivos que divergem do manifesto. Com allow_append (início de bloco), um arquivo
    que só cresceu no fim passa: kill -9 não grava o manifesto, e runs.jsonl e a coleta são
    só de acréscimo. Truncar ou alterar bytes já registrados continua divergindo."""
    bad, sizes = [], {}
    if allow_append:
        with open(os.path.join(out_dir, SIZES), encoding="utf-8") as f:
            sizes = json.load(f)
    with open(os.path.join(out_dir, "MANIFEST.sha256"), encoding="utf-8") as f:
        for line in f:
            digest, name = line.rstrip("\n").split("  ", 1)
            p = os.path.join(out_dir, name)
            if not os.path.exists(p):
                bad.append(name)
            elif allow_append:
                size = sizes.get(name)
                if size is None or os.path.getsize(p) < size or _sha(p, size) != digest:
                    bad.append(name)
            elif _sha(p) != digest:
                bad.append(name)
    return bad


def inhibit_argv(argv: List[str], environ=None, have=shutil.which) -> Optional[List[str]]:
    """Reexecuta sob systemd-inhibit (o host suspendeu durante o controle de 30 h)."""
    env = os.environ if environ is None else environ
    if env.get("RUNNER_INHIBITED") or not have("systemd-inhibit"):
        return None
    return ["systemd-inhibit", "--what=sleep:idle", "--why=triage runner: coleta em andamento",
            "--mode=block", *argv]


def parse_duration_s(text: str) -> float:
    """'72h', '1d12h', '30m' -> segundos (formato dos flags do Prometheus)."""
    units = {"y": 365 * 86400, "w": 7 * 86400, "d": 86400, "h": 3600, "m": 60, "s": 1}
    parts = re.findall(r"(\d+)([ywdhms])", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"duração inválida: {text!r}")
    return float(sum(int(n) * units[u] for n, u in parts))


# ----------------------------------------------------------- implementação real

class PortForward:
    """Port-forward do Prometheus com reinício automático (cai em reconexões longas)."""

    def __init__(self, kube: RealKube, port: int):
        self.kube, self.port, self._stop, self._proc, self._t = kube, port, threading.Event(), None, None

    def __enter__(self):
        import socket
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", self.port)) == 0:
                raise PreflightError(f"porta {self.port} já está em uso (port-forward antigo?)")
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            argv = ["kubectl", "--context", self.kube.context, "-n", "observability", "port-forward",
                    "svc/prometheus", f"{self.port}:9090"]
            self._proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._proc.wait()
            self._stop.wait(2)

    def __exit__(self, *exc):
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


class RealHandle:
    def __init__(self, proc):
        self.proc = proc

    def wait(self) -> dict:
        out, _ = self.proc.communicate()
        last = [x for x in (out or "").splitlines() if x.strip().startswith("{")]
        if not last:  # sem resumo = o coletor morreu; contar como "nada faltando" validaria dados que não existem
            raise RuntimeError(f"coletor terminou sem resumo (rc={self.proc.returncode})")
        info = json.loads(last[-1])
        return {"collected": info.get("collected", 0), "missing": info.get("missing_epoch", [])}

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()


def real_deps(plan: Plan) -> Deps:
    import urllib.request

    def start_collector(cluster, out_path, minutes, start, meta):
        argv = [sys.executable, os.path.join(HERE, "collector.py"), "--prom",
                f"http://localhost:{plan.clusters[cluster].prom_port}", "--out", out_path,
                "--minutes", str(minutes), "--start", str(start), "--meta", json.dumps(meta)]
        return RealHandle(subprocess.Popen(argv, stdout=subprocess.PIPE, text=True))

    def prom_check(cluster):
        base = f"http://localhost:{plan.clusters[cluster].prom_port}"
        try:
            with urllib.request.urlopen(f"{base}/-/ready", timeout=5):
                pass
            with urllib.request.urlopen(f"{base}/api/v1/status/flags", timeout=5) as r:
                ret = json.loads(r.read())["data"]["storage.tsdb.retention.time"]
            return {"up": True, "retention_s": parse_duration_s(ret)}
        except Exception:
            return {"up": False, "retention_s": 0}

    return Deps(kube=lambda ctx: RealKube(ctx, plan.namespace), now=time.time, sleep=time.sleep,
                start_collector=start_collector, prom_check=prom_check,
                disk_free=lambda p: shutil.disk_usage(p).free,
                portforward=lambda cfg: PortForward(RealKube(cfg.context, plan.namespace), cfg.prom_port))


def main(argv=None, deps_factory=real_deps) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("dry-run", "preflight", "run", "restore", "verify"))
    ap.add_argument("target", help="plano JSON (ou diretório do cluster, OUT/<cluster>, em verify)")
    ap.add_argument("--cluster")
    ap.add_argument("--confirm", help="primeiros 12 hex do hash do plano; obrigatório em run e restore")
    ap.add_argument("--no-inhibit", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "verify":
        bad = verify_manifest(a.target)
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
    if a.cmd in ("run", "restore") and a.confirm != plan.sha256[:12]:
        print(f"Recusado: confirme com --confirm {plan.sha256[:12]} (hash do plano {plan.name}).")
        return 2
    if a.cmd == "run" and not a.no_inhibit:
        wrapped = inhibit_argv([sys.executable, *sys.argv])
        if wrapped:
            os.environ["RUNNER_INHIBITED"] = "1"
            os.execvp(wrapped[0], wrapped)
    deps = deps_factory(plan)
    if a.cmd == "preflight":
        with deps.portforward(plan.clusters[a.cluster]):
            bad = preflight_failures(plan, a.cluster, deps.kube(plan.clusters[a.cluster].context), deps)
        print("pré-voo OK" if not bad else "REPROVADO:\n  " + "\n  ".join(bad))
        return 1 if bad else 0
    if a.cmd == "restore":
        diffs = restore_from_snapshot(deps, plan, a.cluster)
        print("restaurado" if not diffs else f"DIFERENÇAS RESTANTES: {diffs}")
        return 1 if diffs else 0
    run_block(plan, a.cluster, deps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
