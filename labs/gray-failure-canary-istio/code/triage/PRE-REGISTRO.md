# Pré-registro: avaliação do detector por feature e comparação com a análise por versão

Versão 5, 2026-11-05. Base de código: commit `c84b1a5` (branch `feat/local-llm-semantic-router`). Plano de cluster: `plans/EVAL-V5-sigma0.1.json`, hash `fca42706d8ba7bb1e067a711f41cc11ab36d87d4df1e41f4b501445a6c2e6bbb` (`--confirm fca42706d8ba`). Versões anteriores: v1 `b19c4b5`, v2 `fa3425d`, v3 em `538f139`, v4 em `b7cac44` e `45abbeb` (histórico no fim).

**Objetivo da avaliação.** Validar o detector por feature em cluster e compará-lo, nos mesmos dados, com a análise por versão que as ferramentas de mercado fazem (Flagger, Argo Rollouts, Kayenta: métricas agregadas sobre todo o tráfego da versão). A comparação com as ferramentas instaladas é a rodada seguinte.

Este arquivo fixa o que será testado, com quais parâmetros e com quais critérios, antes de novas rodadas. Qualquer mudança vira uma nova versão, com data e justificativa no histórico. Não se altera a versão atual para acomodar um resultado.

**Ordem da v4.** Escrita (1) antes de qualquer dado de cluster da avaliação v4 e (2) antes de rodar o portão de validade do simulador e a seleção da regra (seções "Portão" e "Seleção"). Os valores medidos que o portão usa (suíte G4, σ=0,1, `results/noise`) já foram vistos em 2026-10-28, como estatística descritiva; os intervalos previstos pelo simulador ainda não foram calculados quando este texto foi gravado. Os resultados offline entram depois, na seção "Resultado da Fase 2", sem mudar nada acima dela.

**Limite herdado.** Os dados de cluster já coletados (controles, G4, parcial, step3) foram vistos ao desenhar as regras. A avaliação v4 em cluster é a primeira fora da amostra.

## Perguntas e hipóteses

- **H1 (gray failure por feature).** Uma falha parcial de uma feature (fração `f` das requisições com atraso extra, só na v2) é detectada pelo detector por feature, com a regra primária daquela feature (seleção da Fase 2: B em `heavy-reports`, D em `dashboard`). Cenários primários: `heavy10` e `dash10` (f = 10%); secundários: `heavy20` e `dash20`. Aceite (v5): 30 execuções por cenário e limite inferior unicaudal de 95% de Clopper-Pearson ≥ 0,80 (até 2 falhas em 30). A taxa observada também é comparada com a meta descritiva de 90%. Motivo da mudança em relação à v4: com 29 execuções e limite ≥ 0,90 só 29/29 passa, e a simulação prevê 97,5% de detecção em `heavy10`, o que daria 48% de chance de aprovar um detector que funciona; com o critério v5 a chance é 96% (81% se a taxa real for 95%), e a de aprovar um detector com taxa real de 70% é 0,2%.
- **H2 (isolamento).** Nenhum alarme em `(v1, feature)`, nem em features não injetadas, durante a falha de outra feature.
- **H3 (falso alarme).** Falso alarme abaixo de 0,1 por cluster-hora (limite superior unicaudal de 95% de Poisson) em σ = 0,1, com 30 cluster-horas (15 h de relógio por cluster), por feature e regra primária. σ = 0,3 fica fora desta rodada de cluster (v5): a simulação já prevê falha de H1 e H3 em `heavy-reports` (~1 alarme falso por hora com B), e a rodada dobraria. Fica como previsão simulada e limitação declarada.
- **H5 (por feature contra por versão).** Nas mesmas execuções, a análise por feature detecta mais que a análise por versão estilo mercado (`market_emul.py`: `agg_b` e `flagger_rel`). Teste: McNemar exato unicaudal por cenário, pareado por execução, α = 0,05 com Holm sobre os 4 cenários × 2 métodos. Previsão: a vantagem aparece nos cenários de `dashboard` (o atraso de 0,5 s numa feature de ~1 ms some no p99 agregado, dominado por `heavy-reports`); em `heavy-reports` a análise por versão também deve detectar (3% ou mais do tráfego total fica lento, o que move o p99 agregado), e H5 pode não se confirmar ali. Falso alarme das análises por versão: medido no controle, em blocos consecutivos de 14 janelas (o tamanho de uma execução), sem previsão simulada.
- **H4 (lentidão em um pod).** Sem injeção por pod: só simulada (ver "Ainda não testável").
- **G5 (dashboard).** Não há SLO de produto para `dashboard`. O padrão é decisão de engenharia (BF com piso 250 ms; D com L = 250 ms e Δ = 5 pp), reportado com curva de sensibilidade para L ∈ {100, 250, 500} ms e Δ ∈ {2, 5, 10} pp. A curva é descritiva e não muda a regra.

## Regras de detecção (fixas)

Por janela de 60 s e por `(cluster, versão, feature)`, sempre contra a v1 da mesma feature na mesma janela; 3 janelas seguidas para degradar e 3 para recuperar; erro > 5% degrada em todas as regras.

| Regra | Definição | Papel |
|---|---|---|
| A | p95 > 2 × v1 e > 1000 ms | contraexemplo |
| B | p95 > 1,15 × v1, > v1 + 500 ms e > 1000 ms | padrão do agente |
| C | B sobre a média `sum/count` | registro |
| BF | B com piso e delta por feature: `dashboard` piso 250 ms e delta 0 ms; demais iguais a B | candidata |
| D | fração acima de L na v2 maior que na v1: diferença ≥ 5 pp e z unicaudal de duas proporções (variância combinada) ≥ 1,645 | candidata |

Detalhes da regra D: L é borda de bucket existente (`heavy-reports` 3750 ms, `dashboard` 250 ms); a fração lenta é `+Inf − le=L` sobre o total `+Inf` do mesmo histograma, nas duas versões (n e base_n vêm do histograma, não de `istio_requests_total`); v1 com base_n < 30 ou sem buckets é janela insuficiente (não avança nem zera); feature sem L é erro, não silêncio.

Amostra mínima: n ≥ 30; janela menor não avança nem zera as contagens.

## Tempo e rótulos (fixos)

- A janela de rótulo m é o `increase[1m]` avaliado em m e cobre [m−60, m). Com a falha em [t_on, t_off), as janelas com falha são os rótulos em (t_on, t_off]. Vale no runner (descarte) e na análise (detecção dentro da falha, tempo até detecção).
- Duplicata: amostra a menos de 55 s da última mantida (fica a primeira). Buraco: mais de 90 s entre amostras mantidas zera as contagens de janelas seguidas, mantendo o estado.
- O agente ao vivo não zera as contagens em `source_error`; o replay, que é o analisador desta avaliação, zera em buracos.

## Seleção da regra (só com a calibração)

O plano que numerava este passo como "critério 2.4" não está no disco; o critério fica definido aqui.

1. **Dados.** Simulação `decision_curve.py --mode phase2 --seed 1 --eval-seed 2`: por feature (`heavy-reports`, `dashboard`), por modelo de cluster (a, b) e por σ ∈ {0,1; 0,3}, 72 h saudáveis e 200 execuções por cenário de falha (5 janelas de base + 8 de falha). Falhas: `heavy-reports` f ∈ {20, 10, 5}% com +1,5 s; `dashboard` f ∈ {20, 10, 5}% com +0,5 s.
2. **Candidatas.** B, BF e D com os parâmetros da tabela. As variantes de sensibilidade (piso de BF; L e Δ de D) não são selecionáveis.
3. **Elegível** por (feature, σ): falso alarme com UB95 < 0,1 por cluster-hora nos dois modelos de cluster, na semente de calibração.
4. **Escolha** entre as elegíveis: maior detecção no pior cluster em f = 10%; desempate pela detecção no pior cluster em f = 5%; depois pelo pior tempo mediano até detecção em f = 10% (menor vence; sem detecção perde); depois pela ordem B, BF, D (mais simples primeiro).
5. **Nenhuma elegível:** a regra primária daquela (feature, σ) é B, e esta versão registra a previsão de que H3 falha nessa célula.
6. A semente de avaliação (2) só é reportada; nunca entra na escolha. `test_phase2.CalibrationOnlyTest` garante isso no código.
7. A regra primária de cada (feature, σ) é a usada para H1 e H3 no cluster. As outras são reportadas como secundárias, sem correção de multiplicidade e sem peso de aceite.

## Portão de validade do simulador (σ = 0,1)

Antes de usar a simulação para escolher, ela tem de reproduzir o que já foi medido em σ = 0,1 no cluster.

- **Medido** (`gate_measure.py`, `results/noise`): por cluster, controle de 4 h (`ncontrol-<c>`) e 5 execuções por fração (`np0.2r*`, `np0.1r*`), `heavy-reports`. Métricas: mediana e quantil 99% da razão p95(v2)/p95(v1) por janela; alarmes de B (1,15×) no controle; execuções detectadas por B 1,15× e por 1,30× em f = 20% e 10%; mediana do p95 e da média da v1 (nível).
- **Previsto** (`decision_curve.py --mode gate --seed 1 --replicates 200`): 200 campanhas simuladas com o mesmo desenho (240 janelas de controle; 5 execuções por fração); intervalo central de 95% de cada métrica, inclusivo.
- **Consequências** (fixas antes de rodar):
  - Alguma métrica de decisão (razão, alarmes, detecções) fora do intervalo em qualquer cluster: o simulador é inválido para decidir. A seleção por simulação não é usada; a regra primária é B em todas as células; BF e D ficam exploratórias no cluster; previsões simuladas para σ = 0,3 e H4 não são citadas como evidência.
  - Só métricas de nível (p95 e média da v1) fora: as regras relativas (B, BF) seguem selecionáveis; D não pode ser escolhida para `heavy-reports` (a fração lenta saudável depende do nível absoluto); se a seleção apontar D ali, vale a próxima elegível pela mesma ordem.
  - O modelo do `dashboard` foi montado com os números do controle (latência base logo abaixo de 1 ms no cluster a e logo acima no b), então não tem validação offline independente. A escolha para `dashboard` é condicional ao portão do cluster.
- **No cluster.** O mesmo portão é reaplicado aos dados novos de σ = 0,1 (controle e execuções da avaliação v4), com os intervalos recalculados para o desenho novo **antes** de olhar os dados. Se falhar, as afirmações baseadas em simulação são reportadas como inválidas; os resultados de cluster valem por si.

## Critérios de aceite

- **Detecção:** por cenário, taxa com Clopper-Pearson; H1 pelo limite inferior unicaudal de 95% (seção de hipóteses).
- **Falso alarme:** UB95 de Poisson por cluster-hora, por σ. H3 se < 0,1.
- **Tempo até detecção:** mediana e p90, em janelas, contado de t_on (o rótulo t_on + 60 vale 1).
- **Acerto numa execução:** primeira detecção com rótulo em (t_on, t_off + 60]; detecção com rótulo ≤ t_on é alarme falso antes da falha (`market_emul.detect`, igual para todos os métodos).
- **Isolamento:** alarmes fora de `(v2, feature injetada)`.

Se um critério falhar, o resultado é reportado como falha.

## Protocolo de cluster

- σ = 0,1, igual na v1 e na v2 (v5). Prometheus com retenção ≥ 72 h. Controle: 15 h de relógio por cluster (30 cluster-horas). A exposição do controle é o número de janelas válidas; o controle não é descartado por janelas faltando.
- Execução com falha: 3 min de base, 8 de falha, 3 depois; `HEAVY_RATIO=0,3` (`FAULT_HEAVY_RATIO`). Controle com o `HEAVY_RATIO` original de cada cluster.
- Runner (`runner.py`): pré-voo (nós prontos, uma réplica em `app-service-v1` e `v2`, `triage-agent` em zero, admin com contador de mudanças, variáveis padrão, retenção, disco, lock, manifesto existente íntegro), snapshot único, restauração só das chaves do runner, `--confirm` com o hash do plano (o hash inclui as constantes de descarte).
- Descarte: leitura de volta divergente; nó NotReady; mais de 2 janelas inválidas entre os rótulos (t_on, t_off]; v1 com falha; horário do app a mais de 10 s do planejado; controle retomado depois de rollout, restauração ou mudança no admin desde o t0 (recomeça com t0 novo). Detecção nunca é motivo. Até 3 descartes por cenário; acima disso o bloco para.
- Saída por cluster em `OUT/<cluster>/`, com manifesto sha256 verificado no início de cada bloco.
- Plano: `plans/EVAL-V5-sigma0.1.json` (hash no topo). 15 execuções por cluster em cada cenário (30 no total), ordem dash10, heavy10, dash20, heavy20 e depois o controle; ~31 h por cluster, os dois em paralelo. A análise (replay e `market_emul`) roda sobre os arquivos do runner sem `--skip` (a falha liga pelo admin, sem rollout).

## Notas de desenho (limitações conhecidas, não corrigidas)

- O controle roda com o `HEAVY_RATIO` original (0,5 no cluster b) e as falhas com 0,3. No b, a taxa de falso alarme medida no controle vem de outra mistura de tráfego que a das execuções com falha.
- O app lê os parâmetros da falha no início da requisição, antes do atraso base (3 s em `heavy-reports`). Requisições iniciadas pouco antes de t_off ainda recebem o extra e terminam depois: a janela de rótulo t_off + 60 pode ter alguns segundos de falha.
- Skew de relógio host/pod é aceito até 10 s (`TOLERANCE_S`); acima disso a execução é descartada.
- `prom.slow_count` mascara contagem negativa (`max(0, ...)`) e casa a borda por valor numérico; um vetor com duas grafias da mesma borda (`"3750"` e `"3750.0"`) não é recusado.
- `validate_plan` não recusa dois clusters com o mesmo `prom_port` (o port-forward do segundo falha no pré-voo por porta em uso, mas não há checagem explícita).

## Resultado da Fase 2 (offline, v4, antes de qualquer dado de cluster)

Gravado depois de `b7cac44` (texto acima), commits `c395269` e `983488f`. Saídas em `phase2/`.

**Portão (semente 1, 200 campanhas).** Todas as métricas de decisão dentro do intervalo nos dois clusters: razão p95 v2/v1 (mediana e q99), zero alarmes de B no controle, detecções de B 1,15× (5/5 em 20% e 10%) e de B 1,30× (a: 5/5 e 1/5; b: 2/5 e 0/5). As métricas de nível ficaram fora nos dois clusters: mediana da média da v1 medida 3016 (a) e 3012 ms (b) contra [3059, 3071] previstos; mediana do p95 da v1 3468 (a) e 3552 ms (b) contra [3605, 3632]. O simulador superestima o nível em ~50 ms na média e ~2 a 4% no p95. Consequência aplicada: D não pode ser escolhida para `heavy-reports`.

**Seleção final (calibração, semente 1; portão aplicado).**

| Feature, σ | Regra primária | Elegíveis | Observação |
|---|---|---|---|
| heavy-reports, 0,1 | B | B, BF, D | B e BF idênticas aqui; D tinha f10 menor |
| heavy-reports, 0,3 | B | nenhuma | B e BF com ~1 alarme por hora (UB95 1,1 a 1,2); D era a única elegível e caiu pelo portão; **H3 deve falhar** |
| dashboard, 0,1 | D (L = 250 ms, Δ = 5 pp) | B, BF, D | D vence BF só no desempate de f = 5% (57 contra 55 de 200): empate prático; B é cega (0%) |
| dashboard, 0,3 | D | B, BF, D | idem (o σ não age no dashboard) |

**Previsões para o cluster (semente de avaliação 2, pior cluster).** heavy-reports σ = 0,1, B: f = 20% 100%; f = 10% 97,5%, o que dá chance de só 48% de 29/29 (H1 pode falhar mesmo com o detector funcionando como simulado). heavy-reports σ = 0,3, B: f = 10% 45%, f = 20% 78%, com ~1 falso alarme por hora: H1 e H3 devem falhar. dashboard, D: f = 10% e 20% em 99,5 a 100%; zero falso alarme simulado.

**Sensibilidade do dashboard (G5).** Com o modelo atual, piso de BF (100, 250, 500 ms) e L de D (100, 250, 500 ms) não mudam nada: o saudável fica em ~1 ms e a falha acima de 500 ms. Só Δ muda: 2 pp detecta 92% em f = 5%; 5 pp, 28 a 40%; 10 pp, 0% em f = 5% e 36 a 38% em f = 10%. Limite: o modelo do dashboard não tem cauda saudável (o controle de 30 h teve uma razão de 3,29), então o falso alarme dessas variantes não foi realmente exercitado.

## Resultado da avaliação v5 em cluster (2026-11-06 a 07)

Plano `fca42706d8ba`, commit do analisador `eadb737`. 122 execuções válidas: 120 com falha (15 por cluster em cada um de 4 cenários) e 2 controles de 15 h (um por cluster, 1.800 janelas), **0 descartes**, restauração e manifestos verificados. Relatório: `results/eval-v5/ANALISE-v5.md`. Nada acima desta seção foi alterado depois dos dados.

- **H1: passa.** `dash10` (regra D) 30/30 e `heavy10` (regra B) 30/30, limite inferior 0,905 (critério ≥ 0,80). Secundários `dash20` e `heavy20`: 30/30. TTD mediano 3 janelas.
- **H2: passa.** 0 detecções fora da feature injetada.
- **H3: passa, no limite.** 0 alarmes em 30 cluster-horas por feature (UB95 0,0999 < 0,1). Qualquer alarme teria reprovado.
- **H5: confirmada no dashboard, sem diferença no heavy-reports**, como previsto. dashboard (10% e 20%): por feature 30/30 contra 0/30 da análise por versão (`agg_b` e `flagger_rel` emulado), McNemar com Holm p < 0,0001. heavy-reports: as três detectam 30/30 (0 contra 0). Falso alarme das análises por versão: 0 em 128 blocos de 14 janelas.
- **Secundárias:** B é cega no dashboard (0/30); BF detecta 30/30 em tudo; D detecta 25/30 em `heavy10` (a regra primária ali é B).
- **Limites:** σ = 0,1; falhas de +0,5 s (dashboard) e +1,5 s (heavy) em 10% e 20% das requisições; dois clusters, um pod por versão. O "Flagger" desta rodada é uma emulação (`market_emul.py`), não a ferramenta. σ = 0,3 não foi testado em cluster (a simulação previa falha em heavy-reports).

## v6: comparação com o Flagger real (escrita antes de qualquer dado da rodada)

**Pergunta.** O resultado da v5 (H5) usou uma emulação do Flagger. Com o Flagger instalado, ele enxerga a falha por feature? E a emulação é fiel? Plano `plans/FLAGGER-V6.json`, hash `8dce1637419e02cef69e25661299fe7ea7a5906c10ce007e3feecb119cf0c086` (`--confirm 8dce1637419e`), análise em `eval_flagger.py`, testada antes dos dados.

**Montagem (congelada).** Flagger 1.45.0 (chart 1.45.0, meshProvider istio) no namespace `flagger-system`, Istio 1.31.1, Kubernetes 1.36.4+k0s, nos dois clusters. Laboratório em `flagger-lab` (manifestos em `flagger/`): mesmo `app_server.py` e mesmas variáveis do lab (`SLOW_DELAY_S=3`, `SLOW_JITTER_SIGMA=0,1`), mesmo gerador de carga (2 pods × 8 workers, intervalo 1 s, `HEAVY_RATIO=0,3` nos dois clusters), buckets iguais, retry e timeout iguais (2 tentativas de 5 s, 10 s). O Flagger cria o par `app-fl-primary` e `app-fl` (canary); o roteamento é o **A/B do Flagger**: metade das requisições leva o header `x-canary` e vai ao canary, o resto ao primary, o que reproduz o split 50/50 do lab.

**Análise do Flagger (congelada).** `iterations: 16`, `interval: 1m`, `threshold: 5` (reverte com 5 checagens falhas acumuladas); métricas `request-success-rate` ≥ 99% e `p99-ratio` (MetricTemplate: p99 do canary dividido pelo p99 do primary, ambos do lado do destino, janela de 1 min) ≤ 1,15. Escolhi a análise **relativa** por ser a mais forte que um usuário típico configuraria: se ela não vê o `dashboard`, um limite absoluto de `request-duration` também não veria. Não testada: limite absoluto, outros intervalos e limiares, e MetricTemplate **por feature**.

**Protocolo.** Uma execução = uma revisão do Canary (anotação `bench/rev` no Deployment). Espera-se a fase `Progressing`; o início da coleta é o próximo minuto depois de `Progressing + 60 s`; falha ligada pelo admin do pod do canary em t_on = início + 3 min e desligada em t_off = t_on + 8 min; análise de 14 minutos (3 + 8 + 3). O Flagger decide sozinho. Cenários: `dash10` (dashboard, 10% das requisições, +0,5 s) e `heavy10` (heavy-reports, 10%, +1,5 s), 15 execuções por cluster em cada (30 por cenário), e controle sem falha, 15 execuções por cluster (30), cada uma também uma revisão completa. Dois clusters em paralelo, ~15 h por cluster. Nosso detector, `agg_b` e `flagger_rel` rodam nos mesmos dados (job de Prometheus `probe-flagger`, lado cliente, com o workload mapeado para versão: primary = v1, canary = v2).

**Acerto e alarme falso.** Flagger real: acerto se `Failed` com horário em (t_on, t_off + 60]; `Failed` com horário ≤ t_on é alarme falso antes da falha; no controle, qualquer `Failed` é alarme falso. Demais métodos: `market_emul.detect`.

**Hipóteses e critérios.**
- **H6a (Flagger cego ao dashboard).** Em `dash10`, no máximo 2 reversões em 30 (limite superior unicaudal de 95% de Clopper-Pearson < 0,20). Previsão: 0.
- **H6b (Flagger vê heavy-reports).** Em `heavy10`, limite inferior unicaudal de 95% ≥ 0,80 (pelo menos 28 de 30). Previsão: o p99 do canary sobe com 10% de +1,5 s sobre 30% de tráfego lento.
- **H6c (controle).** 0 reversões em 30 execuções do controle (UB95 < 0,10 exige 29 ou mais execuções sem reversão).
- **H7 (nosso detector contra o Flagger real).** McNemar exato unicaudal pareado por (cluster, execução), Holm sobre `dash10` e `heavy10`, α = 0,05. Previsão: rejeita em `dash10`, não em `heavy10`.
- **H8 (fidelidade da emulação).** Em cada cenário, `flagger_rel` concorda com o Flagger real (acerto ou não) em pelo menos 28 de 30 execuções (LI95 ≥ 0,80). Se falhar, a emulação da v5 não vale como proxy do Flagger e a H5 fica só como resultado sobre a emulação.
- **Descritivos, sem critério de aceite:** tempo até reversão (em minutos, **não comparável** com o nosso em janelas: o Flagger precisa de 5 falhas acumuladas); alarme falso de nosso detector, `agg_b` e `flagger_rel` no controle.

**Descarte.** Leitura de volta divergente; nó NotReady; horário da falha a mais de 10 s do planejado (lido do `set_at` do PUT); o Canary não entra em `Progressing` em 10 min; pré-voo reprovado (inclui latência do `dashboard` pelo Service ≤ 1 s em 10 requisições). Reversão do Flagger não é motivo de descarte. Até 3 descartes por cenário; acima disso o bloco para.

**Incidentes do piloto antes dos dados (resolvidos, registrados para não reaparecerem).** (1) Os dois clusters são multicluster com CIDRs sobrepostos: o Service do Flagger herdava um endpoint morto do outro cluster e metade das requisições esperava 10 s (dashboard com p95 de 9 s). Mitigação: `*.flagger-lab.svc.cluster.local` em `serviceSettings.clusterLocal` do mesh config dos dois clusters e em `modules/istio/main.tf`, mais a checagem de caminho no pré-voo. (2) O orquestrador tratava a fase velha do Canary (Failed do run anterior) como fim da espera e descartava as tentativas; corrigido com teste que reproduz o defeito. Os dados dos pilotos não entram na análise.

**Limites declarados.** O Flagger pode ser configurado com MetricTemplate por feature (o Istio expõe o rótulo `feature`); isto não foi testado e é um resultado possível a favor dele, ao custo de uma métrica escrita e mantida por feature. A reversão do Flagger é do canary inteiro; mitigação por feature não é comparada. σ = 0,1 apenas. Argo Rollouts e Kayenta não foram instalados.

## Resultado da comparação com o Flagger real (v6, 2026-11-07 a 08)

Plano `8dce1637419e`; 90 execuções válidas (30 `dash10`, 30 `heavy10`, 30 de controle), **0 descartes**, manifestos íntegros, estado final dos clusters limpo. Relatório: `results/flagger-v6/ANALISE-flagger.md`. Nada acima desta seção foi alterado depois dos dados.

| Cenário | Flagger real | Nosso detector (regra primária) | `agg_b` (emul.) | `flagger_rel` (emul.) |
|---|---|---|---|---|
| `dash10` | **0/30** | **30/30** | 0/30 | 0/30 |
| `heavy10` | **30/30** | 28/30 | 30/30 | 29/30 |
| Controle (alarme falso em 30 execuções) | 0 | 0 | 0 | 0 |

- **H6a passa:** o Flagger real não reverteu nenhuma das 30 revisões com falha no dashboard (UB95 0,095 < 0,20). Em todas elas promoveu a versão com a falha ativa.
- **H6b passa:** reverteu as 30 de `heavy10` (LI95 0,905), em 5,7 a 8,7 minutos (mediana 6,25) depois de ligar a falha.
- **H6c passa:** 0 reversões em 30 execuções de controle.
- **H7:** rejeita H0 em `dash10` (só o nosso detector acertou em 30 de 30 pares; McNemar com Holm p < 0,0001). Em `heavy10` não rejeita: 2 execuções só do Flagger e nenhuma só nossa (p = 1,0 unicaudal a nosso favor; a direção observada favorece o Flagger).
- **H8 passa:** `flagger_rel` concorda com o Flagger real em 30/30 (`dash10`) e 29/30 (`heavy10`). A emulação da v5 era um proxy fiel nestas condições.
- **Leitura das 2 execuções de `heavy10` só do Flagger** (cluster b, repetições 3 e 14): não é truncamento. Havia 8 e 10 janelas utilizáveis antes do rollback e a regra B não disparou. É compatível com os ~97,5% previstos pela simulação para esse cenário (≈ 29 em 30) e com o desenho do Flagger, que acumula 5 falhas em vez de exigir 3 seguidas.
- **Descritivo, sem critério:** nosso TTD mediano 3 janelas (p90 7); Flagger 6,25 minutos até reverter. Não comparáveis (o Flagger precisa de 5 falhas acumuladas e age sobre o canary inteiro).
- **Limites:** configuração relativa por versão apenas; **MetricTemplate por feature não testado** e é o caminho óbvio para o Flagger cobrir o dashboard, ao custo de uma métrica escrita e mantida por feature; σ = 0,1; dois clusters com um pod por versão; reversão do canary inteiro não comparada com mitigação por feature; Argo Rollouts e Kayenta não testados.

**Correção (2026-11-08):** a primeira redação desta seção dizia "300 execuções válidas". O número certo é 122 (120 com falha e 2 controles de 15 h). Nenhuma taxa, hipótese ou conclusão muda: todas são por cenário, sobre 30 execuções.

## Ainda não testável

- Lentidão de um pod no cluster (H4): sem injeção por pod.
- Comparação com Flagger, Argo Rollouts e Kayenta: não instalados.

## Histórico

- **v1, 2026-10-29.** Primeira versão. Congela a regra B (1,15×, +500 ms, piso 1000 ms, 3 janelas, n ≥ 30) e a regra de calibração, commit `bc3431a`.
- **v2, 2026-10-29.** Controle de cluster de 72 h para 30 h por tipo de ruído (30 h bastam para UB95 < 0,1 com zero alarmes). Nenhuma regra mudou.
- **v3, 2026-10-30.** Define a contagem das 1800 janelas do controle (minuto com amostra sem erro, sem repetir minutos), depois da suspensão do host. Nenhuma regra mudou.
- **v6, 2026-11-07.** Comparação com o Flagger real (seção própria), escrita antes de qualquer dado da rodada. Não altera nada de v1 a v5.
- **v5, 2026-11-05 (resultado registrado em 2026-11-07, seção própria).** Antes de qualquer dado de cluster. H1: 30 execuções e limite inferior ≥ 0,80 (motivo na hipótese); σ = 0,3 fora da rodada de cluster; H5 (comparação pareada com a análise por versão estilo mercado, definida em `market_emul.py`); definição de acerto por execução; plano congelado pelo hash. Nada do resultado offline da Fase 2 mudou.
- **v4, 2026-11-05.** Avaliação por feature fora da amostra. Acrescenta as candidatas BF e D, o `dashboard` (G5), a seleção só na calibração, o portão de validade do simulador, as regras de tempo (rótulo, DUP_S = 55 s, GAP_S = 90 s), H1 com 29 execuções e limite unicaudal, H3 por σ com 30 cluster-horas, e o protocolo do runner. A regra de calibração por quantil da v1 deixa de ser o critério de escolha (vira a seleção acima). Escrita antes de qualquer dado de cluster da v4 e antes de rodar o portão e a seleção.
