# Calibrando os sinais do roteador: material para reproduzir

Acompanha o post "O roteador acerta 47 de 48 perguntas curtas e erra as 4 tarefas reais" (pt-BR e en), 2026-10-30.

## Ordem do experimento (rótulos antes da medição)

1. `data/conjunto.json`: 80 textos rotulados à mão (48 de dificuldade em 8 domínios, 3 `quick` + 3 `deep` cada; 32 de ataque: 8 diretos, 8 indiretos, 16 benignos parecidos).
2. `data/rotulos_congelados.txt`: SHA-256 do conjunto e horário (13:30 UTC). A primeira medição começou depois disso. Confira com `sha256sum data/conjunto.json`.
3. `data/rotulos_cenarios_bench.json`: rótulos dos 8 cenários do benchmark. Escritos antes de medir P(deep), **mas depois** de saber que nenhum cenário tinha ido para `deep-reasoning`. Por isso esse grupo é reportado à parte e não entra na escolha de limiar.

## Scripts (`scripts/`), rodar na raiz do lab

| Script | O que mede | Saída |
|---|---|---|
| `medir_calibracao.py` | P(deep), P(attack) e decisão de cada texto pela API de pré-visualização do roteador; embedding de cada texto | `data/medida.json` |
| `medir_cenarios_bench.py` | o mesmo para os 8 cenários longos do benchmark | `data/medida_cenarios_bench.json` |
| `medir_posicao_instrucao.py` | P(deep) da instrução sozinha, do prompt original e com a instrução repetida no fim | `data/medida_posicao_instrucao.json` |
| `analisar.py` | matriz de confusão nos limiares em uso, limiar escolhido com um domínio de fora, alternativa por embeddings | `data/analise.json` |
| `run_bench_v2.py` | benchmark A (roteador) e C (modelo direto), com streaming, TTFT real e cabeçalhos `X-Vsr-*` | `data/bench_v2/<cenário>/<braço>-<rodada>.json` |
| `make_figures.py` | figuras pt/en e capas; grava `ajuste_latencia.json` | SVG, PNG |

Variáveis de ambiente (sem valor padrão):

```sh
PREVIEW_URL=http://<HOST_ROTEADOR>:<PORTA_GESTAO>   # POST /api/v1/routing/preview
EMBED_URL=http://<HOST_EMBED>:8084                   # só medir_calibracao.py
EMBED_KEY=<CHAVE>                                    # idem; lida do ambiente, nunca gravada
ROUTER_URL=http://<HOST_ROTEADOR>:8899               # run_bench_v2.py
DIRECT_URL=http://<HOST_MODELO>:8080                 # run_bench_v2.py
```

Comandos:

```sh
python3 scripts/medir_calibracao.py data/conjunto.json data/medida.json 3
python3 scripts/medir_cenarios_bench.py data/rotulos_cenarios_bench.json data/medida_cenarios_bench.json
python3 scripts/medir_posicao_instrucao.py data/medida_posicao_instrucao.json
python3 scripts/analisar.py data               # usa data/embeddings_bench.json (embedding dos 8 cenários), se existir
OUT=data/bench_v2 python3 scripts/run_bench_v2.py --rodadas 2
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v $PWD:/w python:3.12-slim \
  sh -c 'pip install -q --user matplotlib && cd /w && python3 scripts/make_figures.py data /tmp/saida'
```

Saída esperada do `analisar.py` (resumo): `dificuldade_limiar_atual {"deep_ok": 23, "deep_perdido": 1, "quick_ok": 24, "quick_falso_deep": 0}`; `ataque_limiar_atual` com 7/8 diretos, 4/8 indiretos e 0/16 benignos bloqueados.

Atenção: a API de pré-visualização guarda em cache a resposta para o mesmo texto. As repetições 2 e 3 de cada texto vieram do cache (tempo ~0 ms) e **não** medem variação.

## Outros arquivos

- `cenarios/`: os 8 cenários sintéticos do benchmark (instrução + artefatos). Os segredos neles são fictícios.
- `config/sinais-e-regras.yaml`: trecho da configuração do roteador com os sinais e as regras usados; sem endereços.
- Sanitização: os nomes internos dos modelos no roteador foram trocados por `principal/qwen3.6-35b` e `fallback/qwen3-14b` nos dados e na configuração; nenhum outro valor foi alterado.
