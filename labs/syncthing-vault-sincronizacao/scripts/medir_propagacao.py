"""Tempo ate um arquivo novo aparecer no hub e na replica do Syncthing.
Cria um arquivo numa pasta de rascunhos (excluida do indice) e le o horario de chegada em cada destino.
Variaveis: HOST_SSH (acesso ao servidor), CT_HUB, CT_REPLICA (ids dos containers),
CAMINHO_HUB e CAMINHO_REPLICA (pastas da pasta sincronizada), PASTA_LOCAL (pasta de rascunhos no PC).
"""
import os, subprocess, time, json, statistics

HOST = os.environ["HOST_SSH"]
CT_HUB, CT_REP = os.environ["CT_HUB"], os.environ["CT_REPLICA"]
HUB = os.environ["CAMINHO_HUB"] + "/teste-sync"
REP = os.environ["CAMINHO_REPLICA"] + "/teste-sync"
LOCAL = os.environ["PASTA_LOCAL"]
os.makedirs(LOCAL, exist_ok=True)
rows = []
for i in range(int(os.environ.get("REPETICOES", "10"))):
    name = f"run-{i:02d}.txt"
    poll = lambda base, ct: subprocess.Popen(
        ["ssh", "-o", "ConnectTimeout=5", HOST, f"pct exec {ct} -- sh -c 'while [ ! -f {base}/{name} ]; do sleep 0.1; done; date +%s.%N'"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    ph, pr = poll(HUB, CT_HUB), poll(REP, CT_REP)
    time.sleep(1.0)
    t0 = time.time()
    with open(os.path.join(LOCAL, name), "w") as f:
        f.write(f"teste {i} {t0}\n")
    hub_t = float(ph.communicate(timeout=120)[0].strip())
    rep_t = float(pr.communicate(timeout=120)[0].strip())
    rows.append({"run": i, "hub_s": round(hub_t - t0, 2), "replica_s": round(rep_t - t0, 2)})
    print(rows[-1], flush=True)
for k in ("hub_s", "replica_s"):
    v = [r[k] for r in rows]
    print(k, "mediana", round(statistics.median(v), 2), "min", min(v), "max", max(v))
json.dump(rows, open(os.environ.get("SAIDA", "sync_medida.json"), "w"), indent=1)
