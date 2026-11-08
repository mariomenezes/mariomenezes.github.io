---
title: "Um simulador que acerta a decisão e erra o nível"
lang: pt-BR
permalink: /pt/2026/11/08/simulador-decisao-nivel/
description: "Antes de usar uma simulação para escolher regras de detecção, comparei as previsões dela com o que já tinha sido medido no cluster. As métricas que decidem caíram dentro do previsto; as de nível absoluto, não. Isso tirou uma regra da disputa, como estava escrito antes."
resumo: "O simulador previu certo todas as decisões e errou a latência média em cerca de 50 ms. Pelo que eu tinha escrito antes, isso bastou para descartar uma regra, e o cluster depois confirmou que ela era a mais fraca ali."
image: /assets/img/simulador-decisao-nivel/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/08/simulador-decisao-nivel/" | relative_url }})*

<p class="status"><span class="pill">Notas de método</span> <span>8 de novembro de 2026</span></p>

Usei uma simulação para escolher qual regra de detecção cada feature usaria na avaliação em cluster. Antes de confiar nela, comparei suas previsões com medições que eu já tinha, no mesmo nível de ruído. Nove métricas por cluster. As sete que decidem (razões entre versões, alarmes, detecções) caíram dentro do intervalo previsto. As duas de nível absoluto (p95 e média da latência) ficaram fora, nos dois clusters.

O que fazer nesse caso já estava escrito antes de rodar a comparação. A regra que depende do nível absoluto saiu da disputa no `heavy-reports`. Depois, no cluster, ela foi justamente a mais fraca naquele cenário (25 de 30, contra 30 de 30 da escolhida).

<div class="tiles">
<div class="tile"><div class="tile-value">14/14</div><div class="tile-label">métricas de decisão dentro do intervalo previsto (7 por cluster)</div></div>
<div class="tile"><div class="tile-value">0/4</div><div class="tile-label">métricas de nível dentro do intervalo (p95 e média, 2 por cluster)</div></div>
<div class="tile"><div class="tile-value">~50 ms</div><div class="tile-label">quanto o simulador superestima a latência média de 3 s</div></div>
</div>

## Resumo

- **O simulador:** cada requisição do `heavy-reports` leva 3 s × ruído lognormal + 50 ms, com retry acima de 5 s; o p95 é calculado com os buckets reais do histograma do Istio. O `dashboard` tem latência base de cerca de 1 ms. As regras são as do detector real.
- **O portão:** 200 campanhas simuladas com o mesmo desenho das medições antigas em σ = 0,1 (4 h de controle e 5 execuções por fração em cada cluster). Uma métrica passa se o valor medido cai no intervalo central de 95% das campanhas.
- **Resultado:** decisão dentro, nível fora. A média medida foi 3.016 e 3.012 ms contra 3.059 a 3.071 previstos; o p95, 3.468 e 3.552 ms contra 3.605 a 3.632.
- **Consequência gravada antes:** se só o nível falhasse, as regras relativas seguiriam selecionáveis e a regra D (que compara frações acima de um limite absoluto de latência) não poderia ser escolhida no `heavy-reports`.
- **Seleção resultante:** B no `heavy-reports` em σ = 0,1; nenhuma regra elegível em σ = 0,3 (previsão de falha do alarme falso, e o ruído alto saiu da rodada de cluster); D no `dashboard`.
- **Não sei por que o nível difere.** A média com ruído ficou *abaixo* da média sem ruído (3.049 ms), o que o modelo não explica. Não investiguei.

## O simulador, em uma figura de pipeline

<pre class="mermaid">
flowchart LR
  R["requisição simulada: 3 s × lognormal(σ) + 50 ms, retry > 5 s"] --> H["histograma com os buckets do Istio"]
  H --> W["janela de 60 s por versão e feature"]
  W --> D["regras reais do detector (B, BF, D)"]
  D --> S["seleção só com a semente de calibração"]
  S --> A["avaliação com outra semente"]
</pre>

O simulador serve para uma pergunta só: entre as regras candidatas, qual tem alarme falso abaixo de 0,1 por cluster-hora e detecta mais no pior cluster? A escolha usa só a semente de calibração; a semente de avaliação é reportada e nunca entra na decisão (um teste garante isso no código).

## O portão

<figure class="fig">
<img src="{{ "/assets/img/simulador-decisao-nivel/portao-pt.svg" | relative_url }}" alt="Nove métricas, dois clusters. As sete de decisão (razão v2/v1 mediana e q99, alarmes no controle, detecções da regra B com 1,15× e 1,30× em falhas de 20% e 10%) têm o valor medido dentro do intervalo previsto. As duas de nível ficam fora: p95 da v1 3.468 e 3.552 ms contra 3.605 a 3.632; média 3.016 e 3.012 contra 3.059 a 3.071." loading="lazy">
<figcaption>Posição do valor medido dentro do intervalo previsto (0 = mínimo, 1 = máximo). Tudo que decide fica dentro; o nível absoluto fica abaixo do intervalo nos dois clusters.</figcaption>
</figure>

As métricas de decisão comparam a v2 com a v1 no mesmo minuto, ou contam alarmes e detecções. Um erro de nível igual nas duas versões se cancela nelas. Por isso o simulador pode errar o nível e ainda acertar a decisão. Só que nem toda regra é imune: a regra D conta requisições acima de 3.750 ms, e a fração saudável acima desse limite depende do nível absoluto. Com o nível superestimado, a simulação erraria a taxa de alarme falso e a detecção dela.

## A seleção

<figure class="fig">
<img src="{{ "/assets/img/simulador-decisao-nivel/selecao-pt.svg" | relative_url }}" alt="Matriz de 4 linhas (heavy-reports e dashboard, σ 0,1 e 0,3) por 3 regras (B, BF, D) com alarme falso UB95 por cluster-hora e detecção em 10%. heavy-reports σ=0,3: B e BF 1,22 por hora (inelegíveis), D 0,07 por hora com 4% de detecção. dashboard: B detecta 0%, BF e D 99 a 100%. Contorno na regra escolhida: B no heavy-reports, D no dashboard." loading="lazy">
<figcaption>Calibração, 72 horas simuladas por célula. Vermelho: alarme falso acima do alvo. No <code>heavy-reports</code> com σ = 0,3, a única regra elegível era a D, e ela caiu pelo portão; o resultado gravado foi "nenhuma regra elegível, H3 deve falhar".</figcaption>
</figure>

| Feature, ruído | Elegíveis | Escolhida | Observação |
|---|---|---|---|
| heavy-reports, σ = 0,1 | B, BF (D saiu pelo portão) | B | B e BF são iguais nesta feature |
| heavy-reports, σ = 0,3 | nenhuma | B, com previsão de falha | B e BF com ~1,2 alarme falso por hora |
| dashboard, σ = 0,1 e 0,3 | B, BF, D | D | D vence BF por 57 a 55 em 200 execuções simuladas: empate prático; B não vê nada |

## O que o cluster disse depois

Na avaliação em cluster, com σ = 0,1, a regra B detectou 30 de 30 no `heavy-reports` e a D, rodando só como secundária, 25 de 30. No `dashboard`, a D detectou 30 de 30. O portão não "acertou" nada sozinho; ele aplicou uma regra escrita antes. Mas, neste caso, a regra excluída foi mesmo a que ficou para trás.

## Limites

- **O modelo do `dashboard` não tem validação independente.** A latência base foi tirada das próprias medições (abaixo de 1 ms num cluster, acima no outro), e o modelo não tem cauda saudável. O alarme falso das variantes do `dashboard` não foi exercitado na simulação; a evidência é o controle de 30 cluster-horas no cluster.
- **O erro de nível ficou sem causa.** Pode estar no `sleep` do app, na precisão do histograma do Envoy ou no meu modelo do overhead. Uma investigação provavelmente aproximaria o modelo, mas não mudaria a decisão desta rodada.
- **Um portão com intervalo de 95% falha por acaso em cerca de 1 de 20 métricas.** Aqui as falhas foram sistemáticas (as 4 de nível, nos dois clusters, todas do mesmo lado), não aleatórias.

## Como reproduzir

Em [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. Medido: `data/gate-measured-sigma0.1.json`, gerado por `code/triage/gate_measure.py` a partir de `data/noise-sigma0.1.tar.gz`.
2. Previsto e veredito: `cd code/triage && python3 decision_curve.py --mode gate --seed 1 --replicates 200 --jobs 8 --measured ../../data/gate-measured-sigma0.1.json --out /tmp/gf`. Critério: `decision_ok: true`, `level_ok: false`, as 4 métricas de nível em `failed`.
3. Seleção: `python3 decision_curve.py --mode phase2 --seed 1 --eval-seed 2 --out /tmp/gf`. Critério: mesma `final_selection` de `data/phase2-cal1-eval2.json`.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
