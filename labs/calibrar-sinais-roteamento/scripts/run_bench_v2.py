#!/usr/bin/env python3
"""Benchmark v2: braco A (roteador) e braco C (modelo direto), com streaming real.

Correcoes em relacao ao run_bench.py (v1):
- TTFT agora e o tempo ate o primeiro token (streaming). A v1 media o tempo total.
- A rota vem dos cabecalhos X-Vsr-* da resposta do roteador. A v1 apontava, por padrao,
  para o proxy da XTX e nao para o roteador, por isso gravava "unknown".
- Cada chamada comeca com um identificador unico. Sem isso, C (logo depois de A, mesmo prompt)
  reaproveitava o prompt em cache do llama.cpp e o TTFT de C saia artificialmente baixo.
  O roteador recusa o campo cache_prompt, por isso o identificador. Conferido por usage.cached_tokens.
- O braco C usa o mesmo modo de raciocinio (thinking) que o roteador escolheu no braco A
  para o mesmo cenario e rodada; assim A contra C mede o custo do roteador, nao do thinking.

Variaveis de ambiente (obrigatorias, sem valor padrao):
  ROUTER_URL  URL base do roteador (API OpenAI), ex.: http://<HOST_ROTEADOR>:8899
  DIRECT_URL  URL base do llama-server do modelo principal, ex.: http://<HOST_XTX>:8080
Opcionais: TEMPERATURE (0.1), MAX_TOKENS (8192), OUT (runs-v2)

Uso:
  python3 run_bench_v2.py --rodadas 2            # todos os cenarios, A e C intercalados
  python3 run_bench_v2.py --cenario 03-terraform-bucket --rodadas 1
Saida: <OUT>/<cenario>/<braco>-<rodada>.json (metricas) e .md (resposta)
"""
import argparse, json, os, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
OUT = Path(os.environ.get("OUT", "runs-v2"))


def build_prompt(slug):
    d = Path("cenarios") / slug
    lines = [(d / "tarefa.md").read_text()]
    art = d / "artefato"
    if art.exists():
        for f in sorted(p for p in art.iterdir() if p.is_file()):
            lines.append(f"\n### Artefato: {f.name}\n{f.read_text()}")
    lines.append("\n## Resposta:")
    return "\n".join(lines)


def stream_call(base, payload):
    """Chama /v1/chat/completions com stream e mede o tempo de cada fase no cliente."""
    url = base.rstrip("/") + "/v1/chat/completions"
    r = {"t_headers": None, "ttft": None, "ttft_content": None, "t_last_token": None,
         "total": None, "chunks": 0, "token_chunks": 0, "usage": {}, "finish_reason": None,
         "vsr": {}, "status": None, "error": None, "served_model": None}
    content, reasoning = [], []
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(900, connect=10)) as c:
            with c.stream("POST", url, json=payload) as resp:
                r["t_headers"] = time.perf_counter() - t0
                r["status"] = resp.status_code
                r["vsr"] = {k.lower(): v for k, v in resp.headers.items() if k.lower().startswith("x-vsr-")}
                if resp.status_code != 200:
                    r["error"] = f"HTTP {resp.status_code}: {resp.read()[:300]!r}"
                    r["total"] = time.perf_counter() - t0
                    return r, "", ""
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    ev = json.loads(data)
                    r["chunks"] += 1
                    r["served_model"] = ev.get("model", r["served_model"])
                    if ev.get("usage"):
                        r["usage"] = ev["usage"]
                    for ch in ev.get("choices", []):
                        delta = ch.get("delta", {})
                        now = time.perf_counter() - t0
                        rc, cc = delta.get("reasoning_content"), delta.get("content")
                        if rc or cc:
                            r["token_chunks"] += 1
                            r["t_last_token"] = now
                            if r["ttft"] is None:
                                r["ttft"] = now
                        if rc:
                            reasoning.append(rc)
                        if cc:
                            content.append(cc)
                            if r["ttft_content"] is None:
                                r["ttft_content"] = now
                        if ch.get("finish_reason"):
                            r["finish_reason"] = ch["finish_reason"]
    except Exception as e:  # erro entra no resultado, nao some
        r["error"] = f"{type(e).__name__}: {e}"
    r["total"] = time.perf_counter() - t0
    gen = r["usage"].get("completion_tokens")
    if gen and r["ttft"] is not None and r["t_last_token"] and r["t_last_token"] > r["ttft"]:
        r["decode_tok_s_cliente"] = (gen - 1) / (r["t_last_token"] - r["ttft"])
    return r, "".join(content), "".join(reasoning)


def run_one(slug, braco, rodada, thinking=None):
    prompt = f"[execucao {uuid.uuid4().hex}]\n" + build_prompt(slug)
    payload = {"messages": [{"role": "user", "content": prompt}], "temperature": TEMPERATURE,
               "max_tokens": MAX_TOKENS, "stream": True, "stream_options": {"include_usage": True}}
    if braco == "A":
        base = os.environ["ROUTER_URL"]; payload["model"] = "vllm-sr/auto"
    else:
        base = os.environ["DIRECT_URL"]; payload["model"] = "principal"
        payload["chat_template_kwargs"] = {"enable_thinking": bool(thinking)}
    started = datetime.now(timezone.utc).isoformat()
    r, content, reasoning = stream_call(base, payload)
    r.update({"cenario": slug, "braco": braco, "rodada": rodada, "inicio_utc": started,
              "prompt_chars": len(prompt), "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS,
              "thinking_pedido": thinking if braco == "C" else None,
              "content_chars": len(content), "reasoning_chars": len(reasoning)})
    d = OUT / slug; d.mkdir(parents=True, exist_ok=True)
    (d / f"{braco}-{rodada}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False))
    md = [f"# {braco} - {slug} - rodada {rodada}", "", "```json", json.dumps(r, indent=2, ensure_ascii=False), "```", ""]
    if reasoning:
        md += ["## Raciocinio", "", reasoning, ""]
    md += ["## Resposta", "", content or f"ERRO: {r['error']}"]
    (d / f"{braco}-{rodada}.md").write_text("\n".join(md))
    f = lambda x: "-" if x is None else f"{x:.2f}"
    print(f"{slug} {braco}{rodada} status={r['status']} rota={r['vsr'].get('x-vsr-selected-decision','-')}/"
          f"{r['vsr'].get('x-vsr-selected-model','-')} ttft={f(r['ttft'])}s total={f(r['total'])}s "
          f"tok={r['usage'].get('completion_tokens')} fim={r['finish_reason']} erro={r['error']}", flush=True)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cenario")
    ap.add_argument("--rodadas", type=int, default=2)
    a = ap.parse_args()
    for v in ("ROUTER_URL", "DIRECT_URL"):
        if not os.environ.get(v):
            sys.exit(f"defina {v}")
    cens = [a.cenario] if a.cenario else sorted(p.name for p in Path("cenarios").iterdir() if p.is_dir())
    for rodada in range(1, a.rodadas + 1):
        for slug in cens:
            ra = run_one(slug, "A", rodada)
            thinking = ra["vsr"].get("x-vsr-selected-decision") == "deep-reasoning"
            run_one(slug, "C", rodada, thinking)


if __name__ == "__main__":
    main()
