"""Coletor v2: janelas alinhadas ao minuto, idempotente, com preenchimento de lacunas.

Diferenças em relação a collect_robust.py (mantido só como referência histórica):
- cada janela é consultada em `time=<minuto exato>`, não em "agora". Por isso uma lacuna
  (suspensão do host, port-forward caído) pode ser preenchida depois, enquanto o
  Prometheus ainda retém os dados (`retention_s`, 72 h depois do ajuste planejado);
- idempotente: a chave é o minuto. Rodar de novo só busca o que falta e nunca duplica;
- guarda o vetor de buckets por (versão, feature), base da regra D, para que uma regra
  nova não exija coletar de novo;
- erro de consulta VIRA linha `{"ts","error"}` e é repetido uma vez no fim; resposta sem
  nenhuma janela também é erro ("sem dados"), e também a que não tem as duas versões das
  duas features (`EXPECTED`), para não entrar como minuto válido;
- primeira linha `{"meta": {...}}` (uma vez, na criação do arquivo): cenário, σ, hash do
  código de análise e SHA do git.

Linhas preenchidas são anexadas no fim do arquivo (fora de ordem); `replay.load_samples`
ordena por tempo. Só lê do Prometheus.

Uso:
  python3 collector.py --prom http://localhost:9151 --out arq.jsonl --minutes 30 \\
      --meta '{"scenario":"ctrl","sigma":0.1}'
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
# relativos a este diretório: análise, runner (regras de descarte) e o app (injeção de falha)
FINGERPRINT_FILES = ("detector.py", "agent.py", "prom.py", "replay.py", "collector.py", "runner.py",
                     "../app/app_server.py")
LIVE_S = 120.0  # consultada até 2 min depois do minuto: "live"; depois, "fill"
# Uma amostra só é minuto válido com as duas versões das duas features: sem a v1 não há
# base e sem a v2 não há candidata; o replay trataria a ausência como "sem tráfego".
EXPECTED = (("v1", "dashboard"), ("v1", "heavy-reports"), ("v2", "dashboard"), ("v2", "heavy-reports"))


@dataclass
class CollectStats:
    collected: int = 0
    skipped: int = 0
    expired: List[int] = field(default_factory=list)
    missing: List[int] = field(default_factory=list)
    errors: int = 0


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def _minute(t: float) -> int:
    return int(round(t / 60.0))


def _scan(path: str):
    """(minutos com amostra válida, arquivo já tem meta?)."""
    have, has_meta = set(), False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                if "meta" in row:
                    has_meta = True
                elif row.get("windows"):
                    have.add(_minute(_epoch(row["ts"])))
    return have, has_meta


def code_fingerprint() -> Dict:
    """SHA do git e hash dos arquivos da análise: amarra os dados ao código que os leu."""
    files = {}
    for name in FINGERPRINT_FILES:
        with open(os.path.join(HERE, name), "rb") as f:
            files[name] = hashlib.sha256(f.read()).hexdigest()
    try:
        sha = subprocess.run(["git", "-C", HERE, "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip() or None
        dirty = bool(subprocess.run(["git", "-C", HERE, "status", "--porcelain", "--", ".", "../app"],
                                    capture_output=True, text=True, timeout=10).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        sha, dirty = None, None
    return {"git_sha": sha, "git_dirty": dirty, "files": files}


def _sample(prom, t: float, src: str) -> dict:
    wins = prom.windows(at=t)
    if not wins:
        raise ValueError("sem dados: nenhuma janela com tráfego nesse minuto")
    missing = [f"{v}/{f}" for v, f in EXPECTED if (v, f) not in wins]
    if missing:
        raise ValueError(f"amostra incompleta: falta {', '.join(missing)}")
    buckets = prom.buckets(at=t)
    out = []
    for (version, feature), w in sorted(wins.items()):
        row = {"version": version, "feature": feature, "n": w.n, "err_pct": w.err_pct,
               "p95_ms": w.p95_ms, "mean_ms": w.mean_ms}
        if (version, feature) in buckets:
            row["buckets"] = buckets[(version, feature)]
        out.append(row)
    return {"ts": _iso(t), "src": src, "windows": out,
            "p95_by_version": prom.p95_by_version(at=t), "mean_by_version": prom.mean_by_version(at=t)}


def collect(prom, out_path: str, minutes: int, start: Optional[float] = None,
            now: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
            meta: Optional[dict] = None, margin_s: float = 3.0,
            retention_s: float = 72 * 3600, retry_errors: bool = True) -> CollectStats:
    t0 = start if start is not None else math.ceil(now() / 60.0) * 60
    targets = [t0 + 60 * k for k in range(minutes)]
    have, has_meta = _scan(out_path)
    stats = CollectStats()
    failed: List[float] = []

    def fetch(f, t: float) -> bool:
        src = "live" if now() - t < LIVE_S else "fill"
        try:
            row = _sample(prom, t, src)
        except Exception as exc:  # consulta falhou ou veio vazia: registra e segue
            f.write(json.dumps({"ts": _iso(t), "error": str(exc)[:200]}) + "\n")
            f.flush()
            stats.errors += 1
            return False
        f.write(json.dumps(row) + "\n")
        f.flush()
        have.add(_minute(t))
        stats.collected += 1
        return True

    with open(out_path, "a", encoding="utf-8") as f:
        if meta is not None and not has_meta:
            f.write(json.dumps({"meta": {**meta, "started": _iso(now()), "fingerprint": code_fingerprint()}}) + "\n")
            f.flush()
        for t in targets:
            if _minute(t) in have:
                stats.skipped += 1
                continue
            if now() - t > retention_s:
                stats.expired.append(t)
                continue
            wait = t + margin_s - now()
            if wait > 0:
                sleep(wait)
            if not fetch(f, t):
                failed.append(t)
        if retry_errors:
            for t in failed:
                if now() - t > retention_s:
                    stats.expired.append(t)
                    continue
                fetch(f, t)
    stats.missing = [t for t in targets if _minute(t) not in have]
    return stats


def stats_summary(st: CollectStats) -> dict:
    """Última linha do CLI. O runner lê `missing_epoch` para decidir descartes."""
    return {"collected": st.collected, "skipped": st.skipped, "errors": st.errors,
            "expired": len(st.expired), "missing": [_iso(t) for t in st.missing],
            "missing_epoch": [float(t) for t in st.missing]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prom", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--start", type=float, default=None, help="epoch alinhado a 60 s (padrão: próximo minuto)")
    ap.add_argument("--meta", default=None, help="JSON com cenário, sigma etc.")
    ap.add_argument("--retention-h", type=float, default=72.0)
    a = ap.parse_args()
    from prom import PromClient
    st = collect(PromClient(a.prom), a.out, a.minutes, a.start,
                 meta=json.loads(a.meta) if a.meta else None, retention_s=a.retention_h * 3600)
    print(json.dumps(stats_summary(st)))
    raise SystemExit(1 if st.missing else 0)


if __name__ == "__main__":
    main()
