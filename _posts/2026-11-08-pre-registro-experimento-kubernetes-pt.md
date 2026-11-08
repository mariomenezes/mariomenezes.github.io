---
title: "Escrever os critérios antes dos dados: pré-registro num laboratório de Kubernetes"
lang: pt-BR
permalink: /pt/2026/11/08/pre-registro-experimento-kubernetes/
description: "Seis versões de um pré-registro, cada uma no Git antes da rodada a que se refere, em duas rodadas de cluster com 212 execuções válidas. O que isso mudou no desenho, duas previsões desfavoráveis ao meu detector que se confirmaram, e o que um pré-registro não protege."
resumo: "Gravei no Git o que contaria como sucesso antes de cada rodada. Isso mudou o critério de aceite, tirou uma regra da disputa e manteve no relatório dois resultados que não favorecem o meu detector."
image: /assets/img/pre-registro-experimento-kubernetes/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/08/pre-registro-experimento-kubernetes/" | relative_url }})*

<p class="status"><span class="pill">Notas de método</span> <span>8 de novembro de 2026</span></p>

Antes de cada rodada do experimento de gray failure em canary, gravei no Git um arquivo com as hipóteses, os números que contariam como sucesso, o plano de execução e a análise. Foram seis versões em dez dias e duas rodadas de cluster, com 212 execuções válidas. O arquivo mudou três decisões do desenho antes de qualquer dado. Também manteve no relatório dois resultados que não favorecem o detector que eu estava construindo.

É um laboratório pessoal, não um estudo clínico. Pré-registro aqui é só uma disciplina: decidir o que vale antes de ver o resultado, e não editar a decisão depois.

<div class="tiles">
<div class="tile"><div class="tile-value">6</div><div class="tile-label">versões do pré-registro, cada uma antes dos dados a que se refere</div></div>
<div class="tile"><div class="tile-value">212</div><div class="tile-label">execuções válidas em cluster (122 na avaliação, 90 contra o Flagger), 0 descartes</div></div>
<div class="tile"><div class="tile-value">3</div><div class="tile-label">decisões de desenho mudadas pelo pré-registro antes de qualquer dado</div></div>
<div class="tile"><div class="tile-value">2</div><div class="tile-label">previsões desfavoráveis ao meu detector que se confirmaram e ficaram no relatório</div></div>
</div>

## Resumo

- **O que entra no arquivo:** hipóteses com critério numérico, a regra de decisão de cada feature, o plano de execução congelado por hash (o runner recusa rodar sem esse hash), a análise já escrita e testada, as regras de descarte e o que fazer se um portão falhar.
- **Três decisões mudaram antes dos dados:** o critério de aceite da detecção (o original reprovaria um detector bom em 52% das vezes); uma regra saiu da disputa porque o simulador errou o nível de latência; e o ruído alto ficou fora da rodada de cluster, com o motivo escrito antes.
- **Duas previsões desfavoráveis se confirmaram:** no `heavy-reports`, a análise por versão detecta tão bem quanto a por feature; e, contra o Flagger real, as duas execuções que só um lado acertou foram do Flagger.
- **Um erro meu apareceu depois:** escrevi "300 execuções" no resultado da avaliação; eram 122. A correção está no próprio arquivo, numa nota datada, sem apagar a frase original.
- **O que um pré-registro não protege:** as versões anteriores usaram dados que eu já tinha visto, a montagem do laboratório e a configuração do Flagger foram escolhas minhas, e o repositório do experimento é privado, então as datas dos commits não são verificáveis por quem lê.

## Por que fazer isso num laboratório

O primeiro post da série afirmava "16 de 16 execuções" com regras que eu tinha ajustado olhando os mesmos dados. Isso não é fraude; é o caminho normal de quem explora. Mas o número fica otimista por construção. A pergunta que eu queria responder depois era outra: com as regras fixadas, em dados novos, o detector funciona? Para essa pergunta ter resposta honesta, a regra e o critério precisam existir antes do dado [1].

## Como ficou o processo

<figure class="fig">
<img src="{{ "/assets/img/pre-registro-experimento-kubernetes/linha-do-tempo-pt.svg" | relative_url }}" alt="Linha do tempo de 29 de outubro a 8 de novembro: commits do pré-registro (v1 e v2 em 29/10, v3 em 4/11, v4 e v5 em 5/11, v6 em 7/11) e commits de dados de cluster (avaliação v5 em 7/11 à noite, Flagger em 8/11), sempre depois da versão a que se referem." loading="lazy">
<figcaption>Commits que alteraram o pré-registro (círculos) e que gravaram dados de cluster (quadrados). Cada rodada de dados vem depois da versão que a define; os resultados entram em seções novas, sem mudar o texto acima.</figcaption>
</figure>

1. **Escrever a versão.** Hipóteses (H1 a H8 ao longo das versões), cada uma com número: "limite inferior unicaudal de 95% ≥ 0,80 em 30 execuções", "falso alarme abaixo de 0,1 por cluster-hora", "McNemar com Holm, α = 0,05".
2. **Escrever e testar a análise antes dos dados.** `eval_v5.py` e `eval_flagger.py` foram commitados, com testes e teste de mutação, antes da primeira execução que iriam analisar. Assim a análise não pode ser ajustada ao resultado.
3. **Congelar o plano.** O plano de cada rodada é um JSON com cenários, repetições e duração. O hash dele, junto com as constantes de descarte do runner, vai para o pré-registro. O runner só roda com `--confirm <12 primeiros caracteres do hash>`.
4. **Rodar e registrar.** O resultado entra numa seção nova, com o hash do plano e o commit do analisador. Nada acima é reescrito. Correção de erro vira nota datada.

## O que mudou por causa disso

**O critério de aceite.** A v4 pedia limite inferior ≥ 0,90 com 29 execuções, o que só passa com 29 de 29. Fazendo a conta antes de rodar, com a taxa que a simulação previa (97,5%), a chance de aprovar era de 48%. A v5 trocou para 30 execuções e limite ≥ 0,80, com 96% de chance. A troca foi motivada pela conta de poder, não por um resultado, e foi registrada antes dos dados. Detalhes em [O critério de 29 de 29]({{ "/pt/2026/11/08/criterio-29-de-29/" | relative_url }}).

**Uma regra saiu da disputa.** As consequências do portão de validade do simulador foram escritas antes de rodar o portão: se só as métricas de nível falhassem, a regra que depende do nível absoluto (D) não poderia ser escolhida no `heavy-reports`. Foi o que aconteceu, e a regra foi tirada sem discussão. Detalhes em [Um simulador que acerta a decisão e erra o nível]({{ "/pt/2026/11/08/simulador-decisao-nivel/" | relative_url }}).

**O ruído alto ficou fora do cluster.** A simulação previa cerca de um alarme falso por hora com a regra B em σ = 0,3. Em vez de rodar e "descobrir" a falha, a v5 tirou σ = 0,3 da rodada de cluster com o motivo escrito, e a limitação aparece em todo resultado.

## Previsto contra observado

<figure class="fig">
<img src="{{ "/assets/img/pre-registro-experimento-kubernetes/previsto-observado-pt.svg" | relative_url }}" alt="Seis hipóteses com taxa observada, intervalo unicaudal de 95% e o critério gravado antes: H1 dash10 e heavy10 30/30 acima de 0,80; H6a Flagger 0/30 abaixo de 0,20; H6b Flagger 30/30 acima de 0,80; H8 concordância 30/30 e 29/30 acima de 0,80." loading="lazy">
<figcaption>Cada barra é o intervalo unicaudal de 95% da taxa observada; a linha vermelha é o critério gravado antes dos dados. Todas as hipóteses deste gráfico passaram, inclusive as que dizem que o Flagger vê o <code>heavy-reports</code> tão bem quanto o meu detector.</figcaption>
</figure>

| Previsão gravada antes | O que saiu | A favor de quem |
|---|---|---|
| No `dashboard`, a análise por versão não detecta | 0 de 30 (emulada) e 0 de 30 (Flagger real) | do detector por feature |
| No `heavy-reports`, a análise por versão detecta tanto quanto a por feature | 30 de 30 nas duas; sem diferença | de ninguém: o argumento do detector fica restrito ao `dashboard` |
| Contra o Flagger real, no `heavy-reports`, sem diferença | 2 execuções só do Flagger, 0 só minhas | do Flagger, na direção |
| Falso alarme abaixo de 0,1 por cluster-hora | 0 em 30 cluster-horas, limite 0,0999 | passa, no limite: um alarme reprovaria |

Leitura: sem o arquivo, a linha do `heavy-reports` seria a mais fácil de deixar de fora de um post sobre "detecção por feature". Com ele, ela está gravada como previsão, e o resultado tem de aparecer.

## O que não funcionou ou ficou fraco

- **A v1 a v3 não eram fora da amostra.** Os controles que calibraram o limiar eram os mesmos que eu já tinha visto. A própria v1 diz isso no topo. A primeira avaliação válida é a v5.
- **Escolhas do desenho são minhas.** O laboratório, as falhas injetadas e a configuração do Flagger (escolhi a análise relativa, a mais forte que um usuário típico faria) foram decididos por mim. O pré-registro só garante que não mudei isso depois.
- **Errei uma contagem.** "300 execuções" no resultado da v5; eram 122 (120 com falha e 2 controles longos). Nenhuma taxa muda, porque todas são por cenário, mas o total ficou errado no arquivo por cerca de 17 horas, até eu reprocessar os dados para estes posts.
- **Datas verificáveis só por mim.** O repositório do experimento é privado. Publico a linha do tempo exportada, com hashes e datas, e o arquivo completo, mas quem lê não consegue conferir os commits.

## Ambiente

O mesmo do [post do Flagger]({{ "/pt/2026/11/08/flagger-real-detector-por-feature/" | relative_url }}): um host Proxmox com dois clusters k0s v1.36.4, Istio 1.31.1, Prometheus v2.55.0 e Flagger 1.45.0. O pré-registro é um arquivo Markdown versionado com o código.

## Como reproduzir

Material em [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio).

1. Ler o arquivo: `code/triage/PRE-REGISTRO.md`. As seções "Resultado..." estão no fim e citam o hash do plano e o commit do analisador.
2. Conferir a ordem: `data/linha-do-tempo.json` lista cada commit do pré-registro e dos dados, com data. Critério: todo commit de dados vem depois da versão que o define.
3. Conferir que a análise já existia: rodar `python3 eval_v5.py` e `python3 eval_flagger.py` sobre os dados brutos dá os mesmos números do arquivo (ver o README do lab).
4. Para usar no seu experimento: um arquivo, um plano com hash, uma análise testada antes, resultados em seção nova e correções como notas datadas. O resto é opcional.

## Referências

1. B. A. Nosek, C. R. Ebersole, A. C. DeHaven, D. T. Mellor, "The preregistration revolution", PNAS, 2018. <https://doi.org/10.1073/pnas.1708274114>. Sustenta: a distinção entre pesquisa exploratória e confirmatória, e o pré-registro como forma de separá-las.
2. Pré-registro deste experimento. [`code/triage/PRE-REGISTRO.md`](https://github.com/mariomenezes/mariomenezes.github.io/blob/main/labs/gray-failure-canary-istio/code/triage/PRE-REGISTRO.md). Sustenta: as versões, os critérios e os resultados citados.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
