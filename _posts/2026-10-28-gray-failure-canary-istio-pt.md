---
title: "Gray failure em canary com Istio: por que o p95 por versão engana, e o que medi separando por feature"
lang: pt-BR
permalink: /pt/2026/10/28/gray-failure-canary-istio/
description: "Notas de laboratório (estudo em andamento): detectar uma feature degradada dentro de um canary com métricas do Istio, regras determinísticas e medições com falha injetada."
image: /assets/img/gray-failure-canary-istio/cover-pt.png
---

*[Read in English]({{ "/en/2026/10/28/gray-failure-canary-istio/" | relative_url }})*

<p class="status"><span class="pill">Estudo em andamento</span> <span>Versão 2 · 28 de outubro de 2026 · <a href="#o-que-mudou">o que mudou</a></span></p>

Uma versão canary pode estar quebrada para **uma** funcionalidade e saudável para todo o resto. A análise de canary mais comum olha a versão inteira: taxa de erro e p95 da v2 contra a v1. Este post registra um experimento de laboratório que mede o que essa visão deixa passar, e o que muda quando a detecção é feita por `(cluster, versão, feature)`.

É um laboratório, não produção, e o estudo ainda está em andamento. Os números valem para o ambiente descrito abaixo, e os limites estão no fim do texto.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/fault-noise-pt.gif" | relative_url }}" alt="Animação: p95 por minuto da v1 e da v2 de heavy-reports. A falha em 10% das requisições começa no minuto 5, o p95 da v2 cruza o limiar e o alarme dispara no minuto 8, enquanto o p95 da versão inteira quase não muda." loading="lazy">
<figcaption>Uma execução real do laboratório. Com 10% das requisições de <code>heavy-reports</code> da v2 mais lentas, o p95 da feature (laranja) cruza o limiar atual (tracejado) e o alarme sai no minuto 8. O p95 da versão inteira (cinza) quase não se mexe. O limiar antigo, de 1,3× (pontilhado), não teria disparado.</figcaption>
</figure>

<div class="tiles">
<div class="tile"><div class="tile-value">10/10</div><div class="tile-label">execuções em que a visão por feature pegou uma falha em 10% das requisições de uma feature, com ruído</div></div>
<div class="tile"><div class="tile-value">0/10</div><div class="tile-label">execuções em que a visão da versão inteira pegou a mesma falha</div></div>
<div class="tile"><div class="tile-value">0</div><div class="tile-label">alarmes falsos em cerca de 16 horas-cluster de tráfego saudável</div></div>
</div>

## Resumo

- **A visão da versão inteira deixa passar uma falha parcial em uma feature.** Uma falha em 10% das requisições de uma feature passou despercebida pela versão inteira em 16 de 16 execuções (6 sem ruído, 10 com ruído), tanto comparada com o próprio histórico quanto com a v1 na mesma janela. A visão por feature pegou 16 de 16.
- **Uma mudança de proporção engana o alarme da versão que olha o próprio histórico.** Sem falha nenhuma, só mudar a participação de `heavy-reports` disparou esse alarme em 10 de 10 execuções. Comparado com a v1 na mesma janela, ficou quieto (0 de 10), e a visão por feature também (0 de 10). Na primeira versão do post eu mostrei só o 10 de 10; agora a comparação está completa.
- **Por feature, com o p95 comparado ao da v1 da mesma feature na mesma janela**, a falha parcial de 10% e 20% foi detectada em 10 de 10 execuções por fração, mesmo com latência variável. Não houve alarme em nenhuma feature saudável.
- **A forma da regra importa.** "p95 dobrou" não detectou nenhuma das falhas abaixo do timeout. A média dilui a falha parcial (0 de 18). Um limiar relativo no p95 funciona, mas o primeiro valor que escolhi (1,3×) deixou de detectar quando o ruído entrou. O ajuste para 1,15× foi previsto por simulação antes de medir, e o cluster confirmou.
- **Falso alarme:** zero em cerca de 16 horas-cluster de tráfego saudável, com e sem ruído. A folga é pequena: janelas saudáveis chegam a 1,12× contra um limiar de 1,15×.
- **Não há IA na decisão.** Tudo é regra fixa sobre métricas do Prometheus.

## O que mudou nesta versão {#o-que-mudou}

<div class="callout">
<p>Voltei aos dados brutos por janela e reanalisei todas as rodadas. Três coisas mudaram:</p>
<ul>
<li><strong>O Resultado 1 estava incompleto.</strong> O alarme da versão inteira que mostrei compara a versão com o próprio valor inicial. Contra a v1 na mesma janela ele não dispara, porque neste laboratório as duas versões recebem a mesma mistura. O resultado foi reescrito com as três visões lado a lado.</li>
<li><strong>O baseline agora está explícito.</strong> O agente compara a v2 com a v1 da mesma feature na mesma janela. Os Resultados 1 a 3 foram analisados primeiro contra a primeira janela da própria v2. Reanalisei com os dois baselines: as contagens por feature são idênticas.</li>
<li><strong>Medições novas:</strong> requisições por janela, a margem entre janelas saudáveis e com falha, e uma varredura do limiar. A varredura mostra que 1,15× está na borda de um platô, não num ótimo ajustado.</li>
</ul>
</div>

## O laboratório

- Um host Proxmox com dois clusters k0s (um nó cada), Istio 1.24.2 em multi-primary e Cilium ClusterMesh.
- Um app HTTP em Python com duas features:
  - `dashboard`: rápido, p95 de 1 a 5 ms;
  - `heavy-reports`: lento, cerca de 3 s.
- Duas versões, v1 (stable) e v2 (canary), com 50/50 no VirtualService. O VirtualService tem `perTryTimeout: 5s` e 2 tentativas.
- Um gerador de tráfego sintético por cluster, que manda o header `X-Feature-Context` com a feature de cada requisição. O gerador fica antes da divisão 50/50, então as duas versões recebem a mesma mistura.
- As falhas são injetadas por variáveis de ambiente no app, **só na v2**. Assim sei exatamente o que foi quebrado, quando e em que fração.
- Volume por janela de 60 s, em 1.424 janelas por versão e feature: `heavy-reports` tem mediana de 75 a 85 requisições (49 a 127), `dashboard` de 128 a 173 (61 a 229). Nenhuma janela teve menos de 30.

<pre class="mermaid">
flowchart LR
  G["gerador de tráfego (header X-Feature-Context)"] --> S["sidecar Envoy (label feature)"]
  S -->|50%| V1["app v1 (stable)"]
  S -->|50%| V2["app v2 (canary)"]
  S -. "métricas, reporter=source" .-> P["Prometheus (allow-list de features)"]
  P --> D["detector: v2 contra v1 da mesma feature"]
  D --> E["evento registrado (modo sombra)"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

## Medindo por feature com o Istio

As métricas padrão do Istio não têm a dimensão "feature". O que usei para criá-la:

**1. Um recurso `Telemetry` que copia o header para um label**, só no lado cliente:

```yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: feature-dimension
  namespace: lab-apps
spec:
  metrics:
  - providers:
    - name: prometheus
    overrides:
    - match: { metric: REQUEST_DURATION, mode: CLIENT }
      tagOverrides:
        feature:
          operation: UPSERT
          value: "request.headers['x-feature-context']"
    # o mesmo para REQUEST_COUNT
```

**2. A annotation `proxy.istio.io/config` com `extraStatTags: [feature]`** nos pods que originam o tráfego. Sem ela, o Envoy não expõe o label.

**3. Um allow-list no scrape do Prometheus.** O header é livre, e um label livre explode a cardinalidade. Por isso, um `metric_relabel_configs` transforma tudo que não for `dashboard` ou `heavy-reports` em `other`.

**4. `reporter="source"`** nas consultas. Do lado do destino, os 504 gerados pelo sidecar do chamador (timeout, retry) não aparecem.

**5. Buckets de histograma mais finos.** Os buckets padrão do Istio pulam de 2500 para 5000 ms. Com todas as amostras de `heavy-reports` (~3 s) no mesmo bucket, o p95 interpolado ficava preso em 4875 ms, e qualquer regressão dentro do bucket era invisível. A annotation `sidecar.istio.io/statsHistogramBuckets` com bordas a cada 250 ms entre 2500 e 4750 ms resolveu isso.

A consulta de p95 fica assim:

```promql
histogram_quantile(0.95,
  sum by (destination_canonical_revision, feature, le) (
    rate(istio_request_duration_milliseconds_bucket{
      job="probe-generator",
      destination_service_name="app-service",
      reporter="source"
    }[1m])))
```

## A regra de detecção

- Janelas de 60 s. Uma janela só conta se tiver pelo menos 30 requisições.
- A v2 de cada feature é comparada com a **v1 da mesma feature, na mesma janela**. Assim, o p95 de 3 s de `heavy-reports` nunca é comparado com o p95 de 2 ms de `dashboard`.
- A feature é considerada degradada depois de **3 janelas seguidas** em que vale uma destas condições:
  - erro acima de 5%; ou
  - latência acima do limiar.
- Comparei três regras de latência:
  - **A:** p95 > 2× o baseline (a regra inicial);
  - **B:** p95 > 1,3× o baseline (1,15× a partir do Resultado 4) **e** p95 > baseline + 500 ms;
  - **C:** como B, mas sobre a média (`sum/count`), que não depende de bucket.
- As três têm um piso de 1000 ms: abaixo disso, latência não é avaliada.
- A regra A é uma referência fraca de propósito. Com baseline de 3 s e timeout de 5 s, ela não consegue disparar antes de o timeout virar erro. Ela mostra o ponto cego de um multiplicador ingênuo, não o comportamento de uma ferramenta de canary de verdade.

Para ver o que a separação por feature acrescenta, comparei três **visões** do mesmo tráfego, todas com a mesma regra:

1. **Versão inteira contra o próprio histórico:** o p95 de todas as requisições da v2 contra o valor da v2 no início da execução. É o que faz um alarme estático ou baseado em histórico.
2. **Versão inteira contra a v1:** o p95 de todas as requisições da v2 contra o de todas as da v1 na mesma janela.
3. **Por feature contra a v1:** o p95 de cada feature da v2 contra o da mesma feature na v1 na mesma janela.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/views-pt.svg" | relative_url }}" alt="Barras horizontais agrupadas. Só com mudança de proporção, a versão inteira contra o próprio histórico alarma em 10 de 10 execuções; as outras duas visões, em 0 de 10. Com falhas, as três visões pegam a regressão uniforme e a falha parcial de 20%. Em 10% parcial, as visões da versão inteira pegam 0 de 6 e a visão por feature 6 de 6. Em 5%, 0 de 6 contra 3 de 6. Com ruído, a falha de 20% é pega em 8, 7 e 10 de 10 execuções, e a de 10% em 0, 0 e 10 de 10." loading="lazy">
<figcaption>As mesmas execuções vistas por três ângulos. Só a visão por feature (roxo) pega falhas em 10% das requisições de uma feature, com ou sem ruído.</figcaption>
<details>
<summary>Tabela de dados</summary>
<table class="data">
<thead><tr><th>Cenário</th><th>Execuções</th><th>Versão vs próprio histórico</th><th>Versão vs v1</th><th>Por feature vs v1</th></tr></thead>
<tbody>
<tr><td>Proporção 0% → 30% (alarme falso)</td><td>10</td><td>10</td><td>0</td><td>0</td></tr>
<tr><td>Regressão uniforme 3 → 4,5 s</td><td>10</td><td>10</td><td>10</td><td>10</td></tr>
<tr><td>Parcial, 20% das requisições</td><td>6</td><td>6</td><td>6</td><td>6</td></tr>
<tr><td>Parcial, 10%</td><td>6</td><td>0</td><td>0</td><td>6</td></tr>
<tr><td>Parcial, 5%</td><td>6</td><td>0</td><td>0</td><td>3</td></tr>
<tr><td>Parcial 20% com ruído</td><td>10</td><td>8</td><td>7</td><td>10</td></tr>
<tr><td>Parcial 10% com ruído</td><td>10</td><td>0</td><td>0</td><td>10</td></tr>
</tbody>
</table>
</details>
</figure>

## Resultado 1: uma mudança de proporção engana o alarme da versão que olha o próprio histórico

Mantive a latência de cada feature constante e só mudei a participação de `heavy-reports` no tráfego, de 0% para 30%. Nenhuma falha. As duas versões recebem a mesma mistura, porque o gerador fica antes da divisão 50/50.

O p95 da versão inteira foi de 1–5 ms para cerca de 3 s nas **duas** versões, porque a mistura passou a ter requisições lentas. As duas features continuaram exatamente iguais.

| Visão (10 execuções) | Alarme falso |
|---|---|
| Versão inteira contra o próprio histórico | 10/10 |
| Versão inteira contra a v1, mesma janela | 0/10 |
| Por feature contra a v1, mesma janela | 0/10 |
{: .data}

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/mix-pt.svg" | relative_url }}" alt="Dois gráficos empilhados em escala log. Em cima: o p95 da v1 e da v2 inteiras saltam juntos de cerca de 1 ms para cerca de 3 s quando heavy-reports entra; dashboard fica em 1 ms. Embaixo: a razão da versão inteira contra a própria primeira janela salta para cerca de 3.000 vezes, enquanto a razão da v2 inteira contra a v1 inteira e a razão de heavy-reports v2 contra v1 ficam em 1." loading="lazy">
<figcaption>Em cima: o p95 das duas versões salta junto quando a mistura muda. Embaixo: contra a própria primeira janela, a versão parece 3.000× pior; contra a v1 na mesma janela, nada se mexe.</figcaption>
<details>
<summary>Tabela de dados</summary>
<table class="data">
<thead><tr><th>Minuto</th><th>v2 inteira ÷ sua primeira janela</th><th>v2 inteira ÷ v1 inteira</th><th>heavy-reports v2 ÷ v1</th></tr></thead>
<tbody>
<tr><td>1 a 5</td><td>0,9 a 1,0×</td><td>0,99 a 1,00×</td><td>sem tráfego ainda</td></tr>
<tr><td>6</td><td>3.038×</td><td>1,00×</td><td>1,00×</td></tr>
<tr><td>7 a 12</td><td>3.092 a 3.104×</td><td>1,00×</td><td>1,00×</td></tr>
</tbody>
</table>
</details>
</figure>

A primeira versão deste post mostrava só a primeira linha, e essa é a comparação mais fraca: um alarme de versão que compara com a v1 na mesma janela ignora uma mistura que muda para as duas. O que continua valendo é mais estreito. Qualquer alarme ancorado em histórico ou em valor fixo dispara quando o perfil de uso muda durante um canary.

O que não testei: uma mistura diferente entre v1 e v2 (sticky sessions, roteamento por header, canary muito pequeno). Nesse caso, a comparação da versão inteira contra a v1 também seria enganada, e espero que a visão por feature não seja. Este laboratório não consegue mostrar isso.

## Resultado 2: "p95 dobrou" não vê regressão real abaixo do timeout

Na v2, `heavy-reports` passou de 3 s para 4,5 s em todas as requisições.

| Regra | Detectou (10 execuções) |
|---|---|
| A (2×) | 0/10 |
| B (1,3× e +500 ms) | 10/10 |
| C (média) | 10/10 |
| Versão inteira, regra B | 10/10 |
{: .data}

Com baseline de 3 s, a regra A só dispararia acima de 6 s. Mas com `perTryTimeout` de 5 s, isso já vira erro. Na prática, A não detecta nenhuma regressão de latência nessa feature. Uma regressão uniforme desse tamanho também mexe no p95 da versão inteira, então as três visões a pegam.

## Resultado 3: falha parcial, onde o p95 vence a média

Gray failure de verdade costuma ser parcial: uma fração das requisições fica lenta. Injetei +1,5 s em 20%, 10% e 5% das requisições de `heavy-reports` da v2, com 6 execuções por fração.

| Fração lenta | A | B por feature | C | Versão vs próprio histórico | Versão vs v1 |
|---|---|---|---|---|---|
| 20% | 0/6 | **6/6** | 0/6 | 6/6 | 6/6 |
| 10% | 0/6 | **6/6** | 0/6 | 0/6 | 0/6 |
| 5% | 0/6 | 3/6 | 0/6 | 0/6 | 0/6 |
{: .data}

- **A média dilui a falha.** Com 20% das requisições +1,5 s, a média subiu no máximo 454 ms, abaixo do delta de 500 ms de C. O p95 caiu dentro do grupo lento e subiu para cerca de 4,6 s.
- **A visão da versão inteira só pegou a falha de 20%**, com qualquer um dos baselines.
- **5% é um limite do próprio p95.** Uma janela tem cerca de 75 requisições de `heavy-reports`, então os 5% mais lentos são cerca de 4 requisições. Quando a fração lenta está perto de 5%, o p95 fica na fronteira entre o grupo rápido e o lento e nem sempre se mantém 3 janelas seguidas acima do limiar. É aritmética, não ajuste.
- **Nenhum alarme na v1 nem em `dashboard`**, em nenhuma das execuções.

## Resultado 4: com ruído, o limiar precisou cair, e a simulação acertou antes

Até aqui o app tinha latência fixa (`sleep(3)`). O p95 de `heavy-reports` teve um único valor em 244 janelas seguidas. Isso facilita a detecção e esconde a pergunta mais importante: a regra sobrevive a latência variável?

Antes de mexer no cluster, escrevi um simulador que reproduz os buckets, a interpolação do `histogram_quantile`, o retry do VirtualService, o volume de requisições por janela e as regras reais do detector. Calibrado sem ruído, ele reproduz o que foi medido. Com ruído lognormal (σ=0,1), ele mostrou o problema:

- o ruído aumenta o p95 normal da v1;
- o limiar de 1,3× sobe junto e passa acima das requisições lentas da falha;
- a detecção da falha de 10% caía para cerca de 4%.

O ajuste para **1,15×** recuperava a detecção sem gerar alarme falso na simulação. Registrei esse valor **antes** de medir e depois rodei no cluster: ruído σ=0,1 nas duas versões, 10 execuções por fração e 8 horas-cluster de controle com ruído.

| Regra | Falha 20% | Falha 10% | Alarme falso (8 h) | Previsão da simulação |
|---|---|---|---|---|
| B (1,3×) | 7/10 | 1/10 | 0 | ~65% / ~4% |
| **B (1,15×)** | **10/10** | **10/10** | **0** | ~100% / ~97% |
| C (média) | 0/10 | 0/10 | 0 | — |
| Versão inteira vs v1 (1,15×) | 7/10 | 0/10 | 0 | — |
{: .data}

- O ruído foi real: o p95 de `heavy-reports` variou de 3384 a 3894 ms entre janelas.
- A detecção saiu 3 a 5 minutos depois do início da falha.
- Contra o próprio histórico, a versão inteira pegou 8 de 10 em 20% e 0 de 10 em 10%.
- Reanalisei as 56 execuções anteriores com 1,15×: o resultado foi idêntico em todas. Sem ruído, quem decide o limiar é o delta de 500 ms.

A regra que ficou: **p95 > 1,15× o p95 da v1 da mesma feature e > +500 ms, por 3 janelas.**

### Quão sensível é o 1,15×?

Variei a razão sobre as mesmas execuções com ruído. Até 1,15× nada muda: com baseline perto de 3,5 s, 500 ms já são 14%, então quem decide é o delta, não a razão. Acima de 1,15×, a detecção cai.

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/sweep-pt.svg" | relative_url }}" alt="Gráfico de linhas da detecção contra a razão do limiar. De 1,05 a 1,15 as duas falhas são detectadas em 10 de 10 execuções. Em 1,20 a falha de 10% cai para 8 de 10, em 1,25 para 5 de 10, em 1,30 para 1 de 10 e em 1,40 para 0. A falha de 20% se mantém em 10 de 10 até 1,25, depois 7 de 10 em 1,30 e 0 em 1,40. Alarmes falsos são zero em todas as razões." loading="lazy">
<figcaption>Detecção contra a razão do limiar, 10 execuções com ruído por falha. Alarmes falsos no controle de 8 horas são zero em todas as razões, porque o delta de +500 ms mantém o limiar efetivo acima das janelas saudáveis.</figcaption>
<details>
<summary>Tabela de dados</summary>
<table class="data">
<thead><tr><th>Razão</th><th>Falha 20% (de 10)</th><th>Falha 10% (de 10)</th><th>Alarmes falsos (8 h)</th></tr></thead>
<tbody>
<tr><td>1,05 a 1,12</td><td>10</td><td>10</td><td>0</td></tr>
<tr><td>1,15</td><td>10</td><td>10</td><td>0</td></tr>
<tr><td>1,20</td><td>10</td><td>8</td><td>0</td></tr>
<tr><td>1,25</td><td>10</td><td>5</td><td>0</td></tr>
<tr><td>1,30</td><td>7</td><td>1</td><td>0</td></tr>
<tr><td>1,40</td><td>0</td><td>0</td><td>0</td></tr>
</tbody>
</table>
</details>
</figure>

Então 1,15× é a borda de um platô, não um ótimo ajustado. Duas consequências. A razão importa menos que o delta de +500 ms, e um delta fixo significa coisas diferentes para cada feature: 500 ms são 14% de um baseline de 3,5 s, 50% de um de 1 s e 5% de um de 10 s. O delta deveria ser relativo ou por feature. E mais ruído empurraria a detecção para baixo: na simulação, com σ=0,15 a falha de 10% é detectada em cerca de 70% das execuções (141 de 200) a 1,15×. Não medi ruído acima de σ=0,1 no cluster.

## Resultado 5: falso alarme em tráfego saudável

| Controle | Duração | Alarmes (todas as regras) |
|---|---|---|
| Sem ruído | ~8,2 horas-cluster | 0 |
| Com ruído (σ=0,1) | 8 horas-cluster | 0 |
{: .data}

<figure class="fig">
<img src="{{ "/assets/img/gray-failure-canary-istio/margin-pt.svg" | relative_url }}" alt="Histogramas sobrepostos da razão do p95 da v2 sobre o da v1. Janelas saudáveis ficam centradas em 1,0 e chegam no máximo a 1,12. Janelas com falha de 10% se centram perto de 1,26 e com falha de 20% perto de 1,32. Uma linha tracejada marca o limiar de 1,15 e uma pontilhada o antigo limiar de 1,3." loading="lazy">
<figcaption>Janelas saudáveis (cinza) contra janelas com falha (laranja) nas execuções com ruído. O limiar de 1,15× separa os dois grupos, com cerca de 3 pontos de folga do lado saudável.</figcaption>
<details>
<summary>Tabela de dados</summary>
<table class="data">
<thead><tr><th>Janelas</th><th>Quantidade</th><th>Mediana</th><th>Máximo</th><th>Acima de 1,15×</th></tr></thead>
<tbody>
<tr><td>Saudáveis (controle de 8 h)</td><td>480</td><td>1,00×</td><td>1,09×</td><td>0%</td></tr>
<tr><td>Saudáveis (controle + 80 janelas antes da falha)</td><td>560</td><td>1,00×</td><td>1,12×</td><td>0%</td></tr>
<tr><td>Falha em 10%</td><td>80</td><td>1,26×</td><td>1,39×</td><td>79%</td></tr>
<tr><td>Falha em 20%</td><td>80</td><td>1,32×</td><td>1,41×</td><td>88%</td></tr>
</tbody>
</table>
</details>
</figure>

No controle de 8 horas com ruído, a razão entre o p95 da v2 e o da v1 em cada minuto ficou entre 0,91 e 1,09. Somando as 80 janelas anteriores a cada falha, o máximo é 1,12. Essa folga até 1,15 é o que mantém o alarme falso em zero. Ela é pequena, e só cobre ruído independente entre pods.

Janelas individuais com falha ainda podem ficar abaixo do limiar (21% das janelas da falha de 10% não passaram de 1,15×). A detecção exige 3 janelas seguidas, e por isso saiu 3 a 5 minutos depois do início da falha.

Zero alarmes não quer dizer taxa zero. Com esse volume, o limite superior de 95% é de cerca de 0,37 alarme falso por hora-cluster em cada condição.

## Pegadinhas do ambiente

- **Pod CIDRs iguais nos dois clusters.** Em multi-primary, o sidecar passou a balancear metade das requisições para IPs de pods do outro cluster, que eram inalcançáveis. Resultado: 32% de erro e p95 de 10 s. Mitigado com `clusterLocal` para o serviço. O correto é usar CIDRs distintos.
- **`reporter="destination"` esconde 504.** Use `source` quando quiser ver o que o cliente recebe.
- **Buckets do histograma** definem o que você consegue enxergar. Confira onde a latência da sua feature cai antes de confiar em p95.
- **Retry transforma cauda em latência ou em erro.** Com a falha e o ruído juntos, requisições acima de 5 s foram refeitas, e a taxa de erro chegou a 4,9%, perto do limite de 5% da regra de erro.

## Limites (leia antes de generalizar)

- Laboratório com um host, uma réplica por versão e tráfego sintético.
- Um nível de ruído medido (σ=0,1), independente e igual nas duas versões. Um pod que fica lento sozinho, por contenção de CPU ou rajadas, não foi testado. É a fonte mais provável de alarme falso real, e o caso mais próximo da ideia original de gray failure.
- Uso "gray failure" para degradação parcial, por feature, dentro de um canary, no espírito de [Huang et al. (HotOS 2017)](https://www.microsoft.com/en-us/research/publication/gray-failure-achilles-heel-cloud-scale-systems/): um sistema que parece saudável para os próprios health checks enquanto está degradado para os usuários. O laboratório reproduz a degradação parcial. Não reproduz um único pod com mau comportamento escondido atrás de checks saudáveis.
- Amostras pequenas: 10 de 10 detecções dão um limite inferior de 95% de cerca de 74% para a taxa real (unilateral; 69% bilateral).
- A mistura foi a mesma nas duas versões. Uma mistura diferente entre versões não foi testada.
- **Features rápidas continuam sem detecção de latência.** Com `dashboard` lento em 20% das requisições (+0,5 s), o p95 foi para 447–909 ms. Ficou abaixo do piso de 1000 ms, e nenhuma regra disparou. O piso precisa ser por feature.
- **Falhas abaixo de cerca de 5% das requisições de uma feature estão fora do alcance de um p95 de 60 s** com esse volume.
- Nada disso foi comparado ainda com Flagger ou outra ferramenta de análise de canary. Não estou afirmando que essa abordagem é melhor. Separar por endpoint ou por feature também não é uma ideia nova. O que este post traz são as medições.

## Próximos passos

1. Piso por feature e delta relativo, para que `dashboard` também seja detectável.
2. Degradar um único pod, com três ou mais réplicas por versão, e medir alarmes falsos.
3. Medir ruído acima de σ=0,1 e uma mistura diferente entre versões.
4. Comparar com o Flagger no mesmo cenário de falha parcial. O Flagger faz rollback do canary inteiro; aqui a pergunta é se dá para isolar só a feature afetada.
5. Testar a fração de requisições acima de uma latência fixa, em vez do p95, para falhas abaixo de 5%.
6. Mitigação por feature: desviar só a feature degradada para a v1 e bloquear a promoção do canary. Primeiro em modo sombra, só registrando o que seria feito.

Sobre IA: ela não entra na detecção nem na decisão. Se entrar, vai ser só para escrever a explicação depois de o evento ter sido detectado por regra, e só se mostrar valor medido.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
