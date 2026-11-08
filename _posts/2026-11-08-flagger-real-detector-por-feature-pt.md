---
title: "Flagger real contra detector por feature: 0 de 30 contra 30 de 30"
lang: pt-BR
permalink: /pt/2026/11/08/flagger-real-detector-por-feature/
description: "Instalei o Flagger nos dois clusters do laboratório e injetei a mesma falha parcial no dashboard 30 vezes. O Flagger promoveu as 30 versões com defeito; o detector por feature pegou as 30. Em heavy-reports, os dois detectaram."
resumo: "O Flagger, com análise relativa por versão, promoveu 30 de 30 versões com falha no dashboard. O detector por feature pegou as 30, sem alarme falso em 30 execuções de controle."
image: /assets/img/flagger-real-detector-por-feature/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/08/flagger-real-detector-por-feature/" | relative_url }})*

<p class="status"><span class="pill">Estudo em andamento</span> <span>Comparação v6 do pré-registro · 8 de novembro de 2026</span></p>

Uma falha em 10% das requisições do `dashboard` de uma versão canary, com 0,5 s a mais em cada uma, passou pelo Flagger nas 30 vezes em que a injetei: ele promoveu a versão com defeito todas as vezes. Nas mesmas execuções, o detector por feature disparou nas 30. Em `heavy-reports`, os dois detectaram.

É um laboratório, não produção. O Flagger foi configurado com a análise **relativa por versão**, a mais forte que eu esperaria de um usuário típico, e não com uma métrica por feature, que é o caminho óbvio para cobrir o `dashboard`. Isso está nos limites, logo abaixo do resumo.

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/execucoes-pt.svg" | relative_url }}" alt="Grade de 60 execuções em quatro linhas (Flagger real, detector por feature, análise por versão emulada, estilo Flagger emulado). Em dashboard 10%, o Flagger real tem 0 de 30 quadrados cheios e o detector por feature 30 de 30. Em heavy-reports 10%, Flagger 30 de 30, detector 28 de 30, emulações 30 e 29." loading="lazy">
<figcaption>Cada quadrado é uma execução: cheio quando o método detectou dentro da janela da falha. No <code>dashboard</code>, o Flagger real (vermelho) não detectou nenhuma das 30; o detector por feature (laranja) detectou todas. No <code>heavy-reports</code>, todos detectam; as duas faltas do detector estão no cluster b.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">0/30</div><div class="tile-label">versões com falha no dashboard que o Flagger reverteu (promoveu as 30)</div></div>
<div class="tile"><div class="tile-value">30/30</div><div class="tile-label">mesmas execuções detectadas pelo detector por feature</div></div>
<div class="tile"><div class="tile-value">0/30</div><div class="tile-label">alarmes falsos em 30 revisões de controle, nos quatro métodos</div></div>
<div class="tile"><div class="tile-value">59/60</div><div class="tile-label">execuções em que a emulação do Flagger da rodada anterior concordou com o Flagger real</div></div>
</div>

## Resumo

- **Dashboard (10% das requisições com +0,5 s):** o Flagger real promoveu 30 de 30 versões com a falha ativa. O detector por feature (regra D, fração de requisições acima de 250 ms) detectou 30 de 30. Pareando execução a execução, a diferença é significativa (McNemar exato com correção de Holm, p < 0,0001).
- **Heavy-reports (10% com +1,5 s):** o Flagger reverteu 30 de 30, com mediana de 6,2 minutos depois de ligar a falha. O detector por feature (regra B, p95 relativo) pegou 28 de 30. Não há diferença significativa, e a direção favorece o Flagger. As duas faltas não são truncamento pelo rollback.
- **Controle:** 30 revisões completas sem falha. Nenhum método disparou.
- **A emulação era fiel:** a análise "estilo Flagger" que eu tinha emulado na rodada anterior concordou com o Flagger real em 30/30 (dashboard) e 29/30 (heavy-reports). O resultado anterior, feito só com a emulação, se sustenta.
- **Limite principal:** testei só a análise por versão. Um MetricTemplate por feature provavelmente faria o Flagger enxergar o dashboard, ao custo de uma métrica escrita e mantida por feature. Não foi medido.

## A pergunta

Na [avaliação anterior]({{ "/pt/2026/10/28/gray-failure-canary-istio/" | relative_url }}) o detector por feature pegou falhas que a análise por versão não via. Só que a análise por versão era uma emulação minha. A pergunta desta rodada é se o Flagger, instalado de verdade e configurado como um usuário configuraria, se comporta como a emulação. As hipóteses, os critérios de aceite e o plano foram gravados no Git antes de qualquer dado (seção v6 do pré-registro [1]).

## Ambiente

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/ambiente-pt.svg" | relative_url }}" alt="Diagrama: um host Proxmox com dois clusters k0s; em cada um, Flagger 1.45.0, o par app-fl-primary e app-fl (canary), um gerador de carga com dois pods e um Prometheus com retenção de 72 horas. O runner e o coletor rodam fora dos clusters." loading="lazy">
<figcaption>O mesmo laboratório, montado duas vezes. Cada cluster roda as mesmas execuções em paralelo, e os resultados são somados (15 + 15 por cenário).</figcaption>
</figure>

| Item | Valor |
|---|---|
| Hospedeiro | um host Proxmox, duas VMs, um nó k0s em cada |
| Nós | Debian 12, kernel 6.1, 6 vCPU, 12 GB (a) e 16 GB (b) |
| Kubernetes | k0s v1.36.4, containerd 2.3.5, kube-router v2.10.0 |
| Service mesh | Istio 1.31.1, multi-primary |
| Métricas | Prometheus v2.55.0, scrape de 15 s, retenção de 72 h |
| Flagger | 1.45.0 (chart 1.45.0, `meshProvider=istio`) |
| App | servidor HTTP em Python, uma réplica por versão; `dashboard` ~1 ms, `heavy-reports` 3 s com ruído lognormal σ = 0,1 |
| Carga | 2 pods × 8 workers, 1 requisição por segundo por worker, 30% em `heavy-reports`, metade com o header `x-canary` |
| Estado | nada mais rodando nos namespaces do teste; duas rodadas válidas entre 7 e 8 de novembro |

## Como o teste funciona

O Flagger cria `app-fl-primary` (a versão estável) e passa a tratar o Deployment `app-fl` como canary. Usei o modo A/B dele: requisições com o header `x-canary: insider` vão para o canary, as outras para o primary. O gerador põe o header em metade das requisições, o que reproduz o 50/50 do laboratório original.

<pre class="mermaid">
flowchart LR
  G["gerador (50% com x-canary)"] --> S["sidecar Envoy"]
  S -->|"sem header"| P["app-fl-primary"]
  S -->|"x-canary"| C["app-fl (canary)"]
  P -. "métricas do destino" .-> M["Prometheus"]
  C -. "métricas do destino" .-> M
  S -. "métricas do cliente, por feature" .-> M
  M --> F["Flagger: p99 canary/primary e sucesso"]
  M --> D["detector por feature"]
  F --> R["promove ou reverte"]
</pre>

A análise do Flagger foi congelada antes dos dados:

```yaml
analysis:
  interval: 1m
  iterations: 16
  threshold: 5            # reverte com 5 checagens falhas
  match:
  - headers:
      x-canary:
        exact: "insider"
  metrics:
  - name: request-success-rate
    thresholdRange: { min: 99 }
    interval: 1m
  - name: p99-ratio       # MetricTemplate: p99 do canary / p99 do primary
    templateRef: { name: p99-ratio, namespace: flagger-lab }
    thresholdRange: { max: 1.15 }
    interval: 1m
```

Escolhi a razão de p99 entre canary e primary porque ela compara as duas versões no mesmo minuto, como o meu detector faz. Um limite absoluto de `request-duration` seria mais fraco neste caso: 0,5 s a mais numa feature de 1 ms não move o p99 de um serviço em que 30% das requisições levam 3 s.

Cada execução é uma revisão nova do canary. O runner espera a fase `Progressing`, alinha o início da coleta ao minuto, liga a falha pelo endpoint de administração do pod do canary 3 minutos depois, desliga 8 minutos depois disso e espera mais 3. O Flagger decide sozinho. O meu detector e as emulações leem o mesmo tráfego, do lado do cliente, com o rótulo de feature.

Contei acerto quando o método age dentro da falha: o Flagger reverte, ou o detector dispara, entre o início da falha e um minuto depois do fim. Reverter antes da falha conta como alarme falso.

## Resultado 1: o Flagger não vê uma falha que fica dentro de uma feature

No `dashboard`, o Flagger passou pelas 16 iterações de análise sem nenhuma checagem falha em 30 de 30 revisões, e promoveu a versão com a falha ativa. Era o esperado: a métrica dele é da versão inteira, e 7% do tráfego total ficando 0,5 s mais lento não muda nem a taxa de sucesso nem o p99, que é dominado pelos 3 s de `heavy-reports`.

O detector por feature detectou as 30, em 3 minutos na mediana. A regra usada no `dashboard` (regra D) compara a fração de requisições acima de 250 ms na v2 com a da v1 no mesmo minuto, com um teste de duas proporções. Ela foi escolhida antes dos dados, por simulação, porque a regra do p95 relativo é cega aqui: o piso dela, de 1 s, fica acima da falha.

| Cenário | Flagger real | Detector por feature | Por versão (emulado) | Estilo Flagger (emulado) |
|---|---|---|---|---|
| `dashboard`, 10%, +0,5 s | 0/30 | 30/30 | 0/30 | 0/30 |
| `heavy-reports`, 10%, +1,5 s | 30/30 | 28/30 | 30/30 | 29/30 |
| controle (alarme falso) | 0/30 | 0/30 | 0/30 | 0/30 |

Leitura da tabela: a linha do `dashboard` é o argumento do estudo. A do `heavy-reports` mostra que, quando a falha é grande o bastante para mexer na versão inteira, a análise por versão funciona e o Flagger é até um pouco melhor.

## Resultado 2: no heavy-reports, os dois agem, em escalas diferentes

<figure class="fig">
<img src="{{ "/assets/img/flagger-real-detector-por-feature/tempo-pt.svg" | relative_url }}" alt="Pontos por execução de heavy-reports 10%: o detector por feature dispara em 3 minutos na maioria (mediana 3), alguns entre 4 e 8; o Flagger reverte entre 5,7 e 8,7 minutos (mediana 6,2). Duas execuções sem detecção do detector." loading="lazy">
<figcaption>Minutos desde o início da falha. O detector por feature (laranja) precisa de 3 minutos seguidos degradados; o Flagger (vermelho) precisa de 5 checagens falhas. Os tempos não são comparáveis um a um: o Flagger reverte o canary inteiro, e o detector só registra.</figcaption>
</figure>

O Flagger reverteu as 30 execuções entre 5,7 e 8,7 minutos depois de ligar a falha. Isso bate com 5 checagens falhas a cada minuto, mais o atraso até a primeira janela completa. O detector por feature disparou em 3 minutos em 21 das 28 detecções.

As duas execuções que o detector perdeu estão no cluster b. Conferi se o rollback do Flagger tinha cortado a coleta antes de o detector ter dados: não. Havia 8 e 10 janelas utilizáveis antes da reversão, e a regra B não chegou a 3 janelas seguidas acima do limiar. É consistente com o que a simulação previa para esse cenário (cerca de 97,5% por execução, ou 29 de 30), e com a diferença de desenho: o Flagger soma falhas, a regra B exige sequência.

## Resultado 3: a emulação da rodada anterior era fiel

Na avaliação anterior eu tinha comparado o detector com uma emulação da análise do Flagger, aplicada aos mesmos dados. Agora há o Flagger real e a emulação rodando lado a lado: concordaram em 30 de 30 execuções no `dashboard` e em 29 de 30 no `heavy-reports`. O critério gravado antes era pelo menos 28 de 30 por cenário. Com isso, o resultado anterior, de que a análise por versão não vê a falha do `dashboard`, deixa de depender da minha emulação.

## O que deu errado (antes dos dados)

| Sintoma | Causa | Correção |
|---|---|---|
| No primeiro piloto, o `dashboard` (que responde em 2 ms) teve p95 de 9 a 25 s | Os dois clusters estão em multicluster com faixas de IP de pods sobrepostas; o Service criado pelo Flagger herdou um endpoint inalcançável do outro cluster, e parte das requisições esperava o timeout de conexão de 10 s | `clusterLocal` para o namespace do teste no MeshConfig dos dois clusters, e uma checagem de latência pelo Service no pré-voo. Detalhes em [um post próprio]({{ "/pt/2026/11/08/istio-multicluster-endpoint-fantasma/" | relative_url }}) |
| O segundo piloto descartou todas as tentativas em segundos | Logo depois de uma revisão nova, o Canary ainda mostra a fase da revisão anterior, e o meu orquestrador tratava isso como fim | Só a fase `Progressing` encerra a espera; um teste reproduz o defeito |

Os dados dos dois pilotos inválidos não entram na análise. Estão no material de reprodução, porque mostram o defeito.

## Limites

- **MetricTemplate por feature não foi testado.** O Istio expõe o rótulo de feature, e o Flagger aceita qualquer consulta PromQL. Uma métrica por feature provavelmente pegaria o `dashboard`. O que este post mede é a análise por versão, que é o padrão; o custo da alternativa é uma métrica, um limiar e um teste por feature, mantidos por quem opera.
- **O Flagger age; o detector só registra.** A reversão do Flagger derruba o canary inteiro. O detector por feature, nesta fase, não mitiga nada. Comparar mitigação por feature com rollback é outro experimento.
- **Um nível de ruído** (σ = 0,1), uma réplica por versão, tráfego sintético, dois clusters num só host.
- **30 execuções por cenário.** 30 de 30 dá um limite inferior unicaudal de 95% de 0,905 para a taxa real; 0 de 30 dá um limite superior de 0,095.
- **Argo Rollouts e Kayenta não foram testados.** Kayenta usa testes estatísticos entre canary e baseline e pode se comportar diferente.

## Como reproduzir

Material completo em [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio): código do runner e das análises, manifestos do Flagger, plano congelado por hash, dados brutos das 90 execuções e o script das figuras.

1. Sem cluster, refazer os números: `python3 scripts/extrair.py`. Deve imprimir `flagger: 90 ok, 0 descartes`.
2. A análise completa: `python3 eval_flagger.py <dados>/flagger-v6 plans/FLAGGER-V6.json`. Deve mostrar Flagger 0/30 no `dashboard` e 30/30 no `heavy-reports`.
3. Com cluster: instalar o Flagger (`helm upgrade -i flagger flagger/flagger --version 1.45.0 -n flagger-system --create-namespace --set meshProvider=istio --set metricsServer=http://prometheus.observability:9090`), aplicar os manifestos de `code/triage/flagger/`, conferir com `python3 flagger_runner.py preflight plans/FLAGGER-V6.json --cluster <c>` (deve responder `pré-voo OK`) e rodar `run` com o `--confirm` que o `dry-run` mostra. Cada cluster leva cerca de 15 horas.
4. Variações que mudariam o resultado: um limite absoluto de `request-duration` (deve ver menos), uma métrica por feature (deve ver o `dashboard`), um `threshold` menor (reverte mais cedo, com mais risco de alarme falso).

## Referências

1. Pré-registro do experimento, seções v6 e "Resultado da comparação com o Flagger real". [`code/triage/PRE-REGISTRO.md`](https://github.com/mariomenezes/mariomenezes.github.io/blob/main/labs/gray-failure-canary-istio/code/triage/PRE-REGISTRO.md). Sustenta: hipóteses e critérios gravados antes dos dados.
2. Flagger, "Istio A/B Testing". <https://docs.flagger.app/tutorials/istio-ab-testing>. Sustenta: roteamento por header, `iterations` e `threshold`.
3. Flagger, "Metrics Analysis". <https://docs.flagger.app/usage/metrics>. Sustenta: MetricTemplate e `templateRef` com consulta PromQL própria.
4. Istio, "Multicluster Traffic Management". <https://istio.io/latest/docs/ops/configuration/traffic-management/multicluster/>. Sustenta: `clusterLocal` via `MeshConfig.serviceSettings`.
5. Q. McNemar, "Note on the sampling error of the difference between correlated proportions or percentages", Psychometrika, 1947. Sustenta: o teste pareado usado na comparação.
6. S. Holm, "A simple sequentially rejective multiple test procedure", Scandinavian Journal of Statistics, 1979. Sustenta: a correção para vários testes.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
