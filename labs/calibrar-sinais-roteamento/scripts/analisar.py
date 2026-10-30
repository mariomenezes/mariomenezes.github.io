#!/usr/bin/env python3
"""Analise da calibracao. Entrada: medida.json (do medir_calibracao.py), medida_cenarios_bench.json,
embeddings_bench.json (opcional). Saida: analise.json e resumo no terminal.

1. Sinal do roteador (P(deep), P(attack)) com os limiares em uso (0,85 e 0,7): matriz de confusao.
2. Limiar escolhido por dominio deixado de fora (leave-one-domain-out): escolhe o limiar que maximiza
   o acerto em 7 dominios e mede no oitavo.
3. Alternativa por embeddings: centroide mais proximo (cosseno), tambem deixando um dominio de fora.
Uso: python3 analisar.py <pasta>
"""
import json, math, sys

D = sys.argv[1] if len(sys.argv) > 1 else "."
M = json.load(open(f"{D}/medida.json"))["itens"]
LIM_DEEP, LIM_ATK = 0.85, 0.7


def media(xs):
    return sum(xs) / len(xs)


def p(it, k):
    return media([c[k] or 0.0 for c in it["corridas"]])


def norm(v):
    n = math.sqrt(sum(x * x for x in v)); return [x / n for x in v]


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def centroide(vs):
    return norm([sum(c) / len(vs) for c in zip(*vs)])


dif = [it for it in M if it["tarefa"] == "dificuldade"]
atk = [it for it in M if it["tarefa"] == "ataque"]
for it in M:
    it["emb"] = norm(it["embedding"])
out = {}

# 1. limiares em uso
cm = {"deep_ok": 0, "deep_perdido": 0, "quick_ok": 0, "quick_falso_deep": 0}
for it in dif:
    pd = p(it, "p_deep")
    if it["rotulo"] == "deep":
        cm["deep_ok" if pd >= LIM_DEEP else "deep_perdido"] += 1
    else:
        cm["quick_falso_deep" if pd >= LIM_DEEP else "quick_ok"] += 1
out["dificuldade_limiar_atual"] = cm
por_tipo = {}
for it in atk:
    t = it["grupo"]; pa = p(it, "p_attack"); bloq = pa >= LIM_ATK
    por_tipo.setdefault(t, {"n": 0, "bloqueados": 0}); por_tipo[t]["n"] += 1; por_tipo[t]["bloqueados"] += bloq
out["ataque_limiar_atual"] = por_tipo
out["max_p_attack_benigno"] = max(p(it, "p_attack") for it in atk if it["grupo"] == "benigno")
out["max_p_attack_pedidos_legitimos_de_dificuldade"] = max((p(it, "p_attack"), it["id"]) for it in dif)
out["determinismo"] = all(len({round(c["p_deep"] or 0, 9) for c in it["corridas"]}) == 1 for it in M)

# 2. limiar por dominio deixado de fora
doms = sorted({it["grupo"] for it in dif})
grade = [i / 100 for i in range(1, 100)]


def acerto(itens, lim):
    return sum((p(it, "p_deep") >= lim) == (it["rotulo"] == "deep") for it in itens)


lodo = []
for dm in doms:
    treino = [it for it in dif if it["grupo"] != dm]; teste = [it for it in dif if it["grupo"] == dm]
    melhor = max(grade, key=lambda l: (acerto(treino, l), -abs(l - 0.5)))
    lodo.append({"dominio": dm, "limiar": melhor, "acerto_teste": acerto(teste, melhor), "n": len(teste)})
out["roteador_limiar_lodo"] = lodo

# 3. embeddings, centroide mais proximo, dominio deixado de fora
emb_lodo = []
for dm in doms:
    treino = [it for it in dif if it["grupo"] != dm]; teste = [it for it in dif if it["grupo"] == dm]
    cd = centroide([it["emb"] for it in treino if it["rotulo"] == "deep"])
    cq = centroide([it["emb"] for it in treino if it["rotulo"] == "quick"])
    ok = 0; marg = []
    for it in teste:
        m = cos(it["emb"], cd) - cos(it["emb"], cq); marg.append(m)
        ok += (m > 0) == (it["rotulo"] == "deep")
    emb_lodo.append({"dominio": dm, "acerto_teste": ok, "n": len(teste), "margens": marg})
out["embedding_centroide_lodo"] = emb_lodo
# margem por item (para a figura): treino em todos os outros dominios
for it in dif:
    treino = [x for x in dif if x["grupo"] != it["grupo"]]
    cd = centroide([x["emb"] for x in treino if x["rotulo"] == "deep"]); cq = centroide([x["emb"] for x in treino if x["rotulo"] == "quick"])
    it["margem_emb_lodo"] = cos(it["emb"], cd) - cos(it["emb"], cq)

# ataque por embeddings: deixa um item de fora
ok_atk = {}
for it in atk:
    treino = [x for x in atk if x["id"] != it["id"]]
    ca = centroide([x["emb"] for x in treino if x["rotulo"] == "attack"]); cn = centroide([x["emb"] for x in treino if x["rotulo"] == "normal"])
    m = cos(it["emb"], ca) - cos(it["emb"], cn); it["margem_emb_loo"] = m
    ok_atk.setdefault(it["grupo"], [0, 0]); ok_atk[it["grupo"]][0] += (m > 0) == (it["rotulo"] == "attack"); ok_atk[it["grupo"]][1] += 1
out["embedding_ataque_loo"] = ok_atk

# cenarios do benchmark
try:
    B = json.load(open(f"{D}/medida_cenarios_bench.json"))
    out["bench"] = [{"id": b["id"], "rotulo": b["rotulo"], "chars": b["chars"], "p_deep": p(b, "p_deep"), "p_attack": p(b, "p_attack"),
                     "decisao": b["corridas"][0]["decisao"], "ms_sinal": media([c["ms_sinal_decision"] or 0 for c in b["corridas"]])} for b in B]
    EB = json.load(open(f"{D}/embeddings_bench.json"))
    cd = centroide([it["emb"] for it in dif if it["rotulo"] == "deep"]); cq = centroide([it["emb"] for it in dif if it["rotulo"] == "quick"])
    for b in out["bench"]:
        e = norm(EB[b["id"]]); b["margem_emb"] = cos(e, cd) - cos(e, cq)
except FileNotFoundError:
    pass

out["itens"] = [{"id": it["id"], "tarefa": it["tarefa"], "grupo": it["grupo"], "rotulo": it["rotulo"], "chars": it["chars"],
                 "p_deep": p(it, "p_deep"), "p_attack": p(it, "p_attack"), "decisao": it["corridas"][0]["decisao"],
                 "ms_sinal": media([c["ms_sinal_decision"] or 0 for c in it["corridas"]]),
                 "margem_emb": it.get("margem_emb_lodo", it.get("margem_emb_loo"))} for it in M]
json.dump(out, open(f"{D}/analise.json", "w"), indent=1, ensure_ascii=False)
for k, v in out.items():
    if k != "itens":
        print(k, json.dumps(v, ensure_ascii=False)[:600])
