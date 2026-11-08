# Gray failure em canary com Istio: material de reprodução da série

Material dos posts publicados em 2026-11-08 (e da versão 3 do post de 2026-10-28). Um único lab para a série, porque os posts saem do mesmo experimento e dos mesmos dados:

| Post | O que usa daqui |
|---|---|
| Gray failure em canary com Istio (versão 3) | `data/eval-v5.tar.gz`, `code/triage/eval_v5.py` |
| Flagger real contra detector por feature | `data/flagger-v6.tar.gz`, `code/triage/flagger_runner.py`, `eval_flagger.py`, `flagger/` |
| Pré-registro num laboratório de Kubernetes | `code/triage/PRE-REGISTRO.md`, `data/linha-do-tempo.json` |
| O critério de 29 de 29 | `code/triage/calib_lib.py`, `scripts/extrair.py` (seção `power`) |
| Um simulador que acerta a decisão e erra o nível | `data/gate-*.json`, `data/phase2-cal1-eval2.json`, `data/noise-sigma0.1.tar.gz`, `code/triage/decision_curve.py`, `gate_measure.py` |
| O endpoint que só existe no outro cluster | `data/pilot-flagger-caminho-*.tar.gz`, `data/caminho-medicoes.json` |
| Testes que testam os testes | `data/mutacao.json`, `code/triage/test_*.py` |

## Ambiente

| Item | Valor |
|---|---|
| Hospedeiro | um host Proxmox com duas VMs |
| Nós | um nó k0s por cluster; Debian 12, kernel 6.1; 6 vCPU; 12 GB (cluster a) e 16 GB (cluster b) |
| Kubernetes | k0s v1.36.4, containerd 2.3.5, kube-router v2.10.0 |
| Service mesh | Istio 1.31.1 (multi-primary entre os dois clusters; faixas de IP de pods sobrepostas, ver o post do endpoint) |
| Métricas | Prometheus v2.55.0, scrape de 15 s, retenção de 72 h |
| Progressive delivery | Flagger 1.45.0 (chart 1.45.0, `meshProvider=istio`) |
| App | `code/app/app_server.py` em `python:3.12-slim`, uma réplica por versão; `dashboard` ~1 ms, `heavy-reports` 3 s com ruído lognormal σ = 0,1 |
| Carga | `code/probes/probe_generator.py`, 2 pods × 8 workers, intervalo de 1 s, 30% das requisições em `heavy-reports` durante as falhas |
| Runner e análise | Python 3, só biblioteca padrão, fora do cluster, Prometheus por port-forward |

## Conteúdo

```
code/triage/      detector, coletor, runners, análises, testes e o PRE-REGISTRO.md
code/triage/flagger/  manifestos do laboratório do Flagger (namespace flagger-lab)
code/triage/plans/    planos congelados por hash (EVAL-V5, FLAGGER-V6, piloto)
code/app/, code/probes/  app e gerador de carga
data/*.tar.gz     coletas brutas por execução (JSONL por janela de 60 s) e runs.jsonl de cada cluster
data/*.json       resultados da simulação e do portão, linha do tempo, mutações, medições do caminho
data/figuras.json números das figuras (gerado por scripts/extrair.py)
scripts/          extrair.py (números), make_figures.py (figuras), mutar.py e mutantes/ (teste de mutação)
```

`data/SHA256SUMS` confere os arquivos. Os dados brutos são os mesmos que geraram os números dos posts. Os snapshots de ambiente dos clusters ficaram de fora.

## Como reproduzir os números e as figuras (sem cluster)

1. Pré-requisito: Python 3.11 ou mais novo. Critério: `python3 --version`.
2. Conferir os dados: `cd data && sha256sum -c SHA256SUMS`. Critério: todas as linhas `OK`.
3. Extrair os números: `python3 scripts/extrair.py`. Critério: imprime `v5: 122 ok, 0 descartes; flagger: 90 ok, 0 descartes` e a mediana de 6,24 min da reversão do Flagger.
4. Rodar as análises completas, iguais às dos posts:
   ```
   mkdir -p /tmp/gf && tar xzf data/eval-v5.tar.gz -C /tmp/gf && tar xzf data/flagger-v6.tar.gz -C /tmp/gf
   cd code/triage
   python3 eval_v5.py /tmp/gf/eval-v5 plans/EVAL-V5-sigma0.1.json --out /tmp/gf
   python3 eval_flagger.py /tmp/gf/flagger-v6 plans/FLAGGER-V6.json --out /tmp/gf
   ```
   Critério: `ANALISE-v5.md` com H1, H2, H3 passando e `ANALISE-flagger.md` com Flagger 0/30 em `dash10` e 30/30 em `heavy10`.
5. Testes do experimento: `cd code/triage && python3 -m unittest -q test_eval_v5 test_eval_flagger test_market_emul test_detector test_rules_df test_replay`. Critério: `OK`. (Alguns testes do conjunto completo leem dados que não estão neste lab e são pulados ou falham por arquivo ausente.)
6. Figuras (precisa de matplotlib; em container):
   ```
   docker run --rm -u $(id -u):$(id -g) -e HOME=/tmp -v "$PWD":/w -v <saida>:/out python:3.12-slim \
     sh -c 'pip install -q --user matplotlib && cd /w && python3 scripts/make_figures.py data/figuras.json /out'
   ```
7. Simulação e portão (opcional, ~1 min com 16 processos): `cd code/triage && python3 decision_curve.py --mode gate --seed 1 --replicates 200 --jobs 8 --measured ../../data/gate-measured-sigma0.1.json --out /tmp/gf` e depois `--mode phase2 --seed 1 --eval-seed 2 --out /tmp/gf`. Critério: mesmo veredito de `data/gate-result-seed1.json`.

## Como reproduzir no cluster

Os planos em `code/triage/plans/` têm o hash que os congela. `python3 runner.py dry-run plans/EVAL-V5-sigma0.1.json` e `python3 flagger_runner.py dry-run plans/FLAGGER-V6.json` mostram o hash e a duração; `run` exige `--confirm <12 primeiros hex>`. O runner faz pré-voo (nós, réplicas, variáveis, retenção do Prometheus, latência do caminho pelo Service), grava snapshot, restaura no fim e grava manifesto sha256 por cluster. Os contextos `home/cluster-a` e `home/cluster-b` são os nomes do meu kubeconfig; troque pelos seus.

Instalação do Flagger usada: `helm upgrade -i flagger flagger/flagger --version 1.45.0 -n flagger-system --create-namespace --set meshProvider=istio --set metricsServer=http://prometheus.observability:9090`, depois os manifestos de `code/triage/flagger/` e os dois jobs de `prometheus-jobs.yaml` no Prometheus.

## Perguntas de Gregg

1. **Limitador.** A detecção é limitada pelo número de requisições por janela (cauda do p95 com ~70 a 180 requisições) e pela regra de 3 janelas seguidas; o Flagger, por 5 checagens falhas acumuladas a cada minuto. Nenhum dos dois é limitado por CPU (o app usa 3 a 9 mCPU).
2. **Ajuste.** O detector usa os parâmetros fixados antes dos dados (pré-registro). O Flagger usa a análise relativa por versão (p99 canary/primary ≤ 1,15, sucesso ≥ 99%), mais forte que um limite absoluto; não foi ajustado depois de ver os dados. MetricTemplate por feature não foi testado.
3. **Limites físicos.** As latências estão dentro do timeout do VirtualService (10 s, 2 tentativas de 5 s); requisições acima disso viram erro e entram na taxa de erro.
4. **Erros.** Zero descartes nas duas rodadas válidas; dois pilotos inválidos estão documentados (caminho com endpoint morto; bug do orquestrador) e não entram na análise.
5. **Repetição.** 30 execuções por cenário em dois clusters; controle de 30 cluster-horas (v5) e 30 revisões completas sem falha (v6).
6. **Relevância.** Laboratório com tráfego sintético e um pod por versão. Os números não representam produção.
7. **Aconteceu?** Cada falha foi confirmada pela leitura de volta do admin do app (horário dentro de 10 s do planejado); cada decisão do Flagger, pelo status do Canary e pelos logs do controlador.
