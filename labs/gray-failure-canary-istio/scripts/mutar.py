"""Teste de mutação feito à mão, usado em todo o experimento.

Uso (dentro de code/triage): python3 ../../scripts/mutar.py ARQUIVO "teste1 teste2" ../../scripts/mutantes/X.json
X.json é uma lista de pares [trecho_original, trecho_mutante]. Para cada par: aplica o mutante (o trecho
original precisa aparecer exatamente uma vez), mostra o diff como prova de que foi aplicado, apaga o
bytecode em cache, roda os testes sem gravar bytecode e restaura o arquivo, mesmo em erro.
MORTO = algum teste falhou (bom); VIVO = nenhum teste percebeu (falta teste, ou o mutante é equivalente).

Por que apagar o bytecode: o Python valida o .pyc pela data de modificação (em segundos) e pelo tamanho
do fonte. Um mutante do mesmo tamanho gravado no mesmo segundo do original faz o interpretador rodar o
bytecode velho, e o resultado do mutante fica errado.
"""
import difflib
import json
import os
import subprocess
import sys

path, tests, muts = sys.argv[1], sys.argv[2].split(), json.load(open(sys.argv[3]))
orig = open(path).read()
killed = 0
try:
    for i, (old, new) in enumerate(muts, 1):
        if orig.count(old) != 1:
            print(f"M{i}: ALVO NÃO ÚNICO ({orig.count(old)}x): {old!r}")
            continue
        open(path, "w").write(orig.replace(old, new))
        cur = open(path).read()
        changed = [l.strip() for l in difflib.unified_diff(orig.splitlines(), cur.splitlines(), n=0, lineterm="")
                   if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        for d in ("__pycache__", "../app/__pycache__"):
            subprocess.run(["rm", "-rf", d])
        r = subprocess.run([sys.executable, "-B", "-m", "unittest", "-q", *tests], capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        dead = r.returncode != 0
        killed += dead
        print(f"M{i}: {'MORTO' if dead else 'VIVO '} | diff: {changed[-2:]}")
finally:
    open(path, "w").write(orig)
print(f"{killed}/{len(muts)} mortos")
