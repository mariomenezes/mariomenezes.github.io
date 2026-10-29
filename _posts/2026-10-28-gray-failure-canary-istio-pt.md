---
title: "Gray failure em canary com Istio: por que o p95 por versão engana, e o que medi separando por feature"
lang: pt-BR
permalink: /pt/2026/10/28/gray-failure-canary-istio/
description: "Notas de laboratório: detectar uma feature degradada dentro de um canary com métricas do Istio, regras determinísticas e medições com falha injetada."
---

*[Read in English]({{ "/en/2026/10/28/gray-failure-canary-istio/" | relative_url }})*

Uma versão canary pode estar quebrada para **uma** funcionalidade e saudável para todo o resto. A análise de canary mais comum olha a versão inteira: taxa de erro e p95 da v2 contra a v1. Este post registra um experimento de laboratório que mede o que essa visão deixa passar, e o que muda quando a detecção é feita por `(cluster, versão, feature)`.

É um laboratório, não produção. Os números valem para o ambiente descrito abaixo, e os limites estão no fim do texto.

## Resumo

- **O p95 por versão engana nas duas direções.** Só mudar a proporção entre features, sem nenhuma falha, disparou o alarme da versão em 10 de 10 execuções. E uma falha real em 10% das requisições de uma feature passou despercebida pela versão em 6 de 6.
- **Separando por feature**, com o p95 comparado ao da v1 da mesma feature na mesma janela, a falha parcial de 10% e 20% foi detectada em 10 de 10 execuções por fração, mesmo com latência variável. Não houve alarme em nenhuma feature saudável.
- **A forma da regra importa.** "p95 dobrou" não detectou nenhuma das falhas abaixo do timeout. A média dilui a falha parcial (0 de 18). Um limiar relativo no p95 funciona, mas o primeiro valor que escolhi (1,3×) deixou de detectar quando o ruído entrou. O ajuste para 1,15× foi previsto por simulação antes de medir, e o cluster confirmou.
- **Falso alarme:** zero em cerca de 16 horas-cluster de tráfego saudável, com e sem ruído.
- **Não há IA na decisão.** Tudo é regra fixa sobre métricas do Prometheus.

## O laboratório

- Um host Proxmox com dois clusters k0s (um nó cada), Istio 1.24.2 em multi-primary e Cilium ClusterMesh.
- Um app HTTP em Python com duas features:
  - `dashboard`: rápido, p95 de 1 a 5 ms;
  - `heavy-reports`: lento, cerca de 3 s.
- Duas versões, v1 (stable) e v2 (canary), com 50/50 no VirtualService. O VirtualService tem `perTryTimeout: 5s` e 2 tentativas.
- Um gerador de tráfego sintético por cluster, que manda o header `X-Feature-Context` com a feature de cada requisição.
- As falhas são injetadas por variáveis de ambiente no app, **só na v2**. Assim sei exatamente o que foi quebrado, quando e em que fração.

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
  - **B:** p95 > 1,3× o baseline **e** p95 > baseline + 500 ms;
  - **C:** como B, mas sobre a média (`sum/count`), que não depende de bucket.
- As três têm um piso de 1000 ms: abaixo disso, latência não é avaliada.

## Resultado 1: o agregado por versão dá alarme falso quando só muda a proporção

Mantive a latência de cada feature constante e só mudei a proporção de `heavy-reports` no tráfego, de 0% para 30%. Nenhuma falha.

O p95 da v2 inteira foi de 1–5 ms para cerca de 2,9–3,4 s, porque a mistura passou a ter requisições lentas. As duas features continuaram exatamente iguais.

| Cenário (10 execuções) | Alarme por versão (p95) | Alarme por feature |
|---|---|---|
| Mudança de proporção 0% → 30% | 10/10 | 0/10 |

Isso acontece toda vez que o perfil de uso muda durante um canary.

## Resultado 2: "p95 dobrou" não vê regressão real abaixo do timeout

Na v2, `heavy-reports` passou de 3 s para 4,5 s em todas as requisições.

| Regra | Detectou (10 execuções) |
|---|---|
| A (2×) | 0/10 |
| B (1,3× e +500 ms) | 10/10 |
| C (média) | 10/10 |

Com baseline de 3 s, a regra A só dispararia acima de 6 s. Mas com `perTryTimeout` de 5 s, isso já vira erro. Na prática, A não detecta nenhuma regressão de latência nessa feature.

## Resultado 3: falha parcial, onde o p95 vence a média

Gray failure de verdade costuma ser parcial: uma fração das requisições fica lenta. Injetei +1,5 s em 20%, 10% e 5% das requisições de `heavy-reports` da v2, com 6 execuções por fração.

| Fração lenta | A | B | C | Alarme por versão (B) |
|---|---|---|---|---|
| 20% | 0/6 | **6/6** | 0/6 | 6/6 |
| 10% | 0/6 | **6/6** | 0/6 | 0/6 |
| 5% | 0/6 | 3/6 | 0/6 | 0/6 |

- **A média dilui a falha.** Com 20% das requisições +1,5 s, a média subiu no máximo 454 ms, abaixo do delta de 500 ms de C. O p95 caiu dentro do grupo lento e subiu para cerca de 4,6 s.
- **A versão inteira só viu a falha de 20%.**
- **5% é o limite.** O p95 fica na fronteira entre o grupo rápido e o lento, e nem sempre se mantém 3 janelas seguidas acima do limiar.
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

- O ruído foi real: o p95 de `heavy-reports` variou de 3384 a 3894 ms entre janelas.
- A maior diferença entre v2 e v1 numa mesma janela foi de 9%, abaixo dos 15% do limiar.
- A detecção saiu 3 a 5 minutos depois do início da falha.
- Reanalisei as 56 execuções anteriores com 1,15×: o resultado foi idêntico em todas. Sem ruído, quem decide o limiar é o delta de 500 ms.

A regra que ficou: **p95 > 1,15× o p95 da v1 da mesma feature e > +500 ms, por 3 janelas.**

## Resultado 5: falso alarme em tráfego saudável

| Controle | Duração | Alarmes (todas as regras) |
|---|---|---|
| Sem ruído | ~8,2 horas-cluster | 0 |
| Com ruído (σ=0,1) | 8 horas-cluster | 0 |

Zero alarmes não quer dizer taxa zero. Com esse volume, o limite superior de 95% é de cerca de 0,37 alarme falso por hora-cluster em cada condição.

## Pegadinhas do ambiente

- **Pod CIDRs iguais nos dois clusters.** Em multi-primary, o sidecar passou a balancear metade das requisições para IPs de pods do outro cluster, que eram inalcançáveis. Resultado: 32% de erro e p95 de 10 s. Mitigado com `clusterLocal` para o serviço. O correto é usar CIDRs distintos.
- **`reporter="destination"` esconde 504.** Use `source` quando quiser ver o que o cliente recebe.
- **Buckets do histograma** definem o que você consegue enxergar. Confira onde a latência da sua feature cai antes de confiar em p95.
- **Retry transforma cauda em latência ou em erro.** Com a falha e o ruído juntos, requisições acima de 5 s foram refeitas, e a taxa de erro chegou a 4,9%, perto do limite de 5% da regra de erro.

## Limites (leia antes de generalizar)

- Laboratório com um host, uma réplica por versão e tráfego sintético.
- Um nível de ruído (σ=0,1), independente e igual nas duas versões. Um pod que fica lento sozinho, por contenção de CPU ou rajadas, não foi testado. É a fonte mais provável de alarme falso real.
- Amostras pequenas: 10 de 10 detecções dão um limite inferior de 95% de cerca de 74% para a taxa real.
- **Features rápidas continuam sem detecção de latência.** Com `dashboard` lento em 20% das requisições (+0,5 s), o p95 foi para 447–909 ms. Ficou abaixo do piso de 1000 ms, e nenhuma regra disparou. O piso precisa ser por feature.
- Nada disso foi comparado ainda com Flagger ou outra ferramenta de análise de canary. Não estou afirmando que essa abordagem é melhor. Separar por endpoint ou por feature também não é uma ideia nova. O que este post traz são as medições.

## Próximos passos

1. Piso e delta por feature, para que `dashboard` também seja detectável.
2. Comparar com o Flagger no mesmo cenário de falha parcial. O Flagger faz rollback do canary inteiro; aqui a pergunta é se dá para isolar só a feature afetada.
3. Mitigação por feature: desviar só a feature degradada para a v1 e bloquear a promoção do canary. Primeiro em modo sombra, só registrando o que seria feito.
4. Testar deriva específica de um pod.

Sobre IA: ela não entra na detecção nem na decisão. Se entrar, vai ser só para escrever a explicação depois de o evento ter sido detectado por regra, e só se mostrar valor medido.
