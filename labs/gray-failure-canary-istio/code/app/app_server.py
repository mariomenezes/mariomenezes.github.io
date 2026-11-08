#!/usr/bin/env python3
"""App de teste concorrente (substitui o busybox nc, que atende uma conexão por vez).

Latência controlada por ambiente, para que a degradação do experimento seja
explícita. Degradação real de v2 é injetada pelo fault injection do Istio (T1, T2),
não por este app.

Injeção parcial por feature (gray failure; PROXIMO-PASSO), padrão desligado
(frações 0 não mudam o comportamento atual):
- SLOW_EXTRA_FRACTION / SLOW_EXTRA_S: fração das requisições de `slow-data`
  (heavy-reports) que recebe atraso extra, em segundos, somado ao SLOW_DELAY_S;
- FAST_DELAY_FRACTION / FAST_DELAY_S: o mesmo para `fast-data` (dashboard).

Ruído de latência (G4), padrão desligado:
- SLOW_JITTER_SIGMA: com valor > 0, o atraso base de `slow-data` vira
  SLOW_DELAY_S * lognormal(0, sigma). A mediana continua em SLOW_DELAY_S e a
  distribuição ganha cauda à direita. Deve ser igual na v1 e na v2: é condição
  de tráfego normal, não falha.

Controle em tempo de execução, sem rollout (porta admin, ADMIN_PORT, padrão 8081):
- escuta SÓ em 127.0.0.1 e não está no Service: alcance por `kubectl exec` ou
  `kubectl port-forward pod/...`. A porta do Service (8080) responde 404 a /admin;
- GET    /admin/fault   estado atual, quando ligou e expira, e o histórico com horários;
- PUT    /admin/fault   {"slow_extra_fraction","slow_extra_s","fast_delay_fraction",
                         "fast_delay_s","ttl_s"}: liga a falha com prazo OBRIGATÓRIO
                         (1 a 3600 s). Quando o prazo vence, ela se desliga sozinha, mesmo
                         que quem a ligou tenha morrido. Corpo sem parâmetros = limpar;
- DELETE /admin/fault   limpa.
A sobreposição vale por cima das variáveis de ambiente (a base) e, ao expirar, a base
volta. ADMIN_PORT=0 desliga a porta admin. O histórico é a verdade de campo de quando a
falha realmente começou e terminou.
"""
import json
import math
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = os.getenv("VERSION", "unknown")
SLOW_DELAY_S = float(os.getenv("SLOW_DELAY_S", "3"))
FAST_ERROR_RATE = float(os.getenv("FAST_ERROR_RATE", "0"))  # fração de 503 em fast-data (injeção T2/T4)
# Ruído: 0 mantém o atraso fixo (padrão)
SLOW_JITTER_SIGMA = float(os.getenv("SLOW_JITTER_SIGMA", "0"))
PORT = int(os.getenv("PORT", "8080"))
ADMIN_PORT = int(os.getenv("ADMIN_PORT", "8081"))

PARAM_KEYS = ("slow_extra_fraction", "slow_extra_s", "fast_delay_fraction", "fast_delay_s")
_FRACTIONS = ("slow_extra_fraction", "fast_delay_fraction")
MAX_DELAY_S = 30.0
MAX_TTL_S = 3600
HISTORY_MAX = 50


def base_from_env(environ=None) -> dict:
    """Injeção parcial vinda do ambiente (0 desliga). É a base sobre a qual o admin sobrepõe."""
    e = os.environ if environ is None else environ
    return {
        "slow_extra_fraction": float(e.get("SLOW_EXTRA_FRACTION", "0")),
        "slow_extra_s": float(e.get("SLOW_EXTRA_S", "0")),
        "fast_delay_fraction": float(e.get("FAST_DELAY_FRACTION", "0")),
        "fast_delay_s": float(e.get("FAST_DELAY_S", "0")),
    }


def _number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: precisa ser número")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name}: fora de [{lo}, {hi}]")
    return float(value)


def parse_fault(body):
    """(parâmetros, ttl_s) a partir do corpo do PUT. Levanta ValueError se inválido."""
    if not isinstance(body, dict):
        raise ValueError("o corpo precisa ser um objeto JSON")
    unknown = sorted(set(body) - set(PARAM_KEYS) - {"ttl_s"})
    if unknown:
        raise ValueError(f"chaves desconhecidas: {unknown}")
    params = {}
    for k in PARAM_KEYS:
        hi = 1.0 if k in _FRACTIONS else MAX_DELAY_S
        params[k] = _number(body.get(k, 0.0), k, 0.0, hi)
    ttl = None
    if "ttl_s" in body:
        ttl = _number(body["ttl_s"], "ttl_s", 1, MAX_TTL_S)
    if any(params.values()) and ttl is None:
        raise ValueError("ttl_s é obrigatório quando há falha ligada (1 a 3600)")
    return params, ttl


class FaultState:
    """Falha sobreposta com prazo, sobre a base do ambiente. Thread-safe."""

    def __init__(self, base, clock=time.time):
        self._base = dict(base)
        self._clock = clock
        self._lock = threading.Lock()
        self._override = None
        self._history = []
        self._changes = 0  # monotônico: o histórico é cortado em HISTORY_MAX

    def _log(self, event, at, params, ttl_s=None):
        self._changes += 1
        self._history.append({"event": event, "at": at, "params": dict(params), "ttl_s": ttl_s})
        del self._history[:-HISTORY_MAX]

    def _expire(self):
        o = self._override
        if o is not None and self._clock() >= o["expires_at"]:
            self._log("expired", o["expires_at"], o["params"], o["ttl_s"])
            self._override = None

    def current(self):
        with self._lock:
            self._expire()
            return dict(self._override["params"] if self._override else self._base)

    def set(self, params, ttl_s):
        with self._lock:
            self._expire()
            now = self._clock()
            self._override = {"params": dict(params), "set_at": now, "ttl_s": ttl_s,
                              "expires_at": now + ttl_s}
            self._log("set", now, params, ttl_s)

    def clear(self):
        with self._lock:
            self._expire()
            if self._override is not None:
                self._log("clear", self._clock(), self._override["params"], self._override["ttl_s"])
                self._override = None

    def snapshot(self):
        with self._lock:
            self._expire()
            o = self._override
            return {
                "version": VERSION,
                "active": o is not None,
                "params": dict(o["params"] if o else self._base),
                "base": dict(self._base),
                "set_at": o["set_at"] if o else None,
                "expires_at": o["expires_at"] if o else None,
                "ttl_s": o["ttl_s"] if o else None,
                "now": self._clock(),
                "history": list(self._history),
                "changes": self._changes,
            }


def _reply(handler, status, body):
    payload = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("X-App-Version", VERSION)
    handler.end_headers()
    handler.wfile.write(payload)


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/healthz":
                return self._reply(200, {"status": "ok"})
            if self.path == "/api/v1/fast-data":
                f = state.current()
                if FAST_ERROR_RATE > 0 and random.random() < FAST_ERROR_RATE:
                    return self._reply(503, {"error": "injected"})
                if f["fast_delay_fraction"] > 0 and random.random() < f["fast_delay_fraction"]:
                    time.sleep(f["fast_delay_s"])
                return self._reply(200, {"version": VERSION, "kind": "fast"})
            if self.path == "/api/v1/slow-data":
                f = state.current()
                if SLOW_JITTER_SIGMA > 0:
                    time.sleep(SLOW_DELAY_S * random.lognormvariate(0.0, SLOW_JITTER_SIGMA))
                else:
                    time.sleep(SLOW_DELAY_S)
                if f["slow_extra_fraction"] > 0 and random.random() < f["slow_extra_fraction"]:
                    time.sleep(f["slow_extra_s"])
                return self._reply(200, {"version": VERSION, "kind": "slow"})
            return self._reply(404, {"error": "not found"})

        def _reply(self, status, body):
            _reply(self, status, body)

        def log_message(self, fmt, *args):
            return

    return Handler


def make_admin_handler(state):
    class AdminHandler(BaseHTTPRequestHandler):
        def _fault(self):
            return self.path.split("?", 1)[0] == "/admin/fault"

        def do_GET(self):
            if not self._fault():
                return _reply(self, 404, {"error": "not found"})
            _reply(self, 200, state.snapshot())

        def do_PUT(self):
            if not self._fault():
                return _reply(self, 404, {"error": "not found"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 4096:
                    raise ValueError("corpo ausente ou grande demais")
                params, ttl = parse_fault(json.loads(self.rfile.read(size) or b"null"))
            except (ValueError, json.JSONDecodeError) as exc:
                return _reply(self, 400, {"error": str(exc)})
            if any(params.values()):
                state.set(params, ttl)
            else:
                state.clear()
            _reply(self, 200, state.snapshot())

        def do_DELETE(self):
            if not self._fault():
                return _reply(self, 404, {"error": "not found"})
            state.clear()
            _reply(self, 200, state.snapshot())

        def log_message(self, fmt, *args):
            return

    return AdminHandler


def build_servers(state, port, admin_port=None, host="0.0.0.0", admin_host="127.0.0.1"):
    """(servidor principal, servidor admin ou None). admin_port=None não cria o admin."""
    main = ThreadingHTTPServer((host, port), make_handler(state))
    admin = None if admin_port is None else ThreadingHTTPServer((admin_host, admin_port), make_admin_handler(state))
    return main, admin


if __name__ == "__main__":
    st = FaultState(base_from_env())
    srv, adm = build_servers(st, PORT, ADMIN_PORT if ADMIN_PORT > 0 else None)
    if adm is not None:
        threading.Thread(target=adm.serve_forever, daemon=True).start()
    srv.serve_forever()
