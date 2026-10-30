# Multimodelo em duas GPUs: material para reproduzir

Acompanha o post "Dois servidores na mesma GPU AMD deixaram a placa em 100% sem trabalho; uma variável resolveu" (pt-BR e en), versão 2 de 2026-10-30.

## Ambiente

AMD Ryzen 5 5600G, 62 GB, Proxmox VE 8.4.19 (kernel 6.14.11), 2 × Radeon RX 9060 XT 16 GB (RDNA4), container LXC Ubuntu 24.04 com ROCm 7.2.3 e llama.cpp build 216 (`f12cc6d`, backend HIP). Detalhes no post.

## Scripts (`scripts/`)

| Script | O que faz | Saída |
|---|---|---|
| `experimento_a.sh` | desliga um servidor por vez, depois os dois, religa e manda 1 pedido a cada um (7 fases × 90 s) | `amostras.csv`, `eventos.csv` |
| `experimento_b.sh` | mesma coisa em outra ordem + 2º processo temporário na GPU 0 (6 × 60 s) | idem |
| `experimento_c.sh` | `GPU_MAX_HW_QUEUES` ausente, `=1`, `=2`, ausente (4 × 60 s) | idem |
| `experimento_d.sh` | custo do contorno: 30 embeddings + 10 completações por configuração, depois 60 s ociosa (2 rodadas) | `latencias.csv`, `ocioso.csv` |
| `make_figures.py` | figuras pt/en, capas e `resumo_fases.json` | SVG e PNG |
| `estilo.py` | paleta e tipografia comuns das figuras do blog | — |
| `amostrar_gpu.sh` | amostragem simples da versão 1 do post (5 min) | `gpu_amostra.csv` |

Os experimentos rodam **no hospedeiro Proxmox** (leem o sysfs das GPUs e usam `pct exec` no container). Variáveis:

```sh
CT=<id do container>                 # obrigatório
ENV_CHAVE=<arquivo no container que define LLAMA_API_KEY>
LLAMA_BIN=<caminho do llama-server no container>   # experimento_b
MODELO_EMBED=<caminho do GGUF de embedding>        # experimento_b
FASE_S=60                             # duração de cada fase
```

Os nomes de serviço (`llama-fim`, `llama-embed`) e as portas 8083 e 8084 são os do laboratório; ajuste aos seus. Os experimentos C e D criam e removem um override temporário do systemd (`zz-teste-hwq.conf`).

## Comando único das figuras

```sh
docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v $PWD:/w python:3.12-slim \
  sh -c 'pip install -q --user matplotlib && cd /w/scripts && python3 make_figures.py ../data /tmp/saida'
```

Saída esperada no terminal: uma linha por fase e `ok`. Valores-chave em `data/resumo_fases.json`: fases com 2 processos e configuração padrão com `busy1_mediana` 100; com 1 processo, 2; `D/hwq1` com `busy1_mediana` 2 e `embedding_ms_mediana` ≈ 10,2.

## Dados (`data/`)

- `exp_a/`, `exp_b/`, `exp_c/`: `amostras.csv` (t, fase, uso %, potência W, clock) e `eventos.csv` (início de cada fase).
- `exp_d/`: `latencias.csv` (configuração, tipo, i, segundos, HTTP) e `ocioso.csv`.
- `gpu_amostra.csv`: a amostra de 5 min da versão 1.
- `resumo_fases.json`: medianas por fase, gerado pelo `make_figures.py`.
