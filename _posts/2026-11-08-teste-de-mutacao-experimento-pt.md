---
title: "Testes que testam os testes: mutação num experimento de infraestrutura"
lang: pt-BR
permalink: /pt/2026/11/08/teste-de-mutacao-experimento/
description: "Toda lógica estatística nova do experimento de gray failure foi validada com mutantes: mudanças pequenas e propositais que os testes precisam pegar. 210 mutantes em 22 commits, 206 mortos. O que os sobreviventes revelaram, e o dia em que o próprio teste de mutação mentiu por causa de um .pyc velho."
resumo: "Meu teste de mutação estava mentindo: um arquivo de bytecode antigo fazia um mutante parecer morto. Antes disso, os sobreviventes tinham apontado dez testes que faltavam."
image: /assets/img/teste-de-mutacao-experimento/cover-pt.png
---

*[Read in English]({{ "/en/2026/11/08/teste-de-mutacao-experimento/" | relative_url }})*

<p class="status"><span class="pill">Notas de método</span> <span>8 de novembro de 2026</span></p>

Um teste que passa não prova que o código está certo. Prova que o teste não encontrou nada. Para saber se os testes do experimento de gray failure pegariam um erro de verdade, mudei o código de propósito, uma linha por vez (um `<` virando `<=`, uma constante trocada, uma linha apagada), e conferi se algum teste falhava. Foram 210 mutantes em 22 commits. Os testes pegaram 206; os 4 que sobreviveram eram equivalentes, isto é, não mudavam o comportamento.

Os números bonitos esconderiam o que importa: antes de chegar a eles, os mutantes sobreviventes apontaram uns dez testes que faltavam. E uma vez o próprio teste de mutação mentiu.

<div class="tiles">
<div class="tile"><div class="tile-value">210</div><div class="tile-label">mutantes registrados nas mensagens de 22 commits</div></div>
<div class="tile"><div class="tile-value">206</div><div class="tile-label">mortos pelos testes; os 4 vivos são equivalentes</div></div>
<div class="tile"><div class="tile-value">1</div><div class="tile-label">rodada contaminada por bytecode velho, refeita inteira</div></div>
</div>

## Resumo

- **Onde usei:** em toda lógica que decide um resultado. Regras de detecção, contagem de janelas, critério de acerto, intervalos, seleção de regra, portão do simulador, descarte e restauração do runner, analisadores das hipóteses.
- **Como:** um script de 40 linhas aplica cada mutante, mostra o diff como prova de que ele entrou, roda os testes e restaura o arquivo. Sem ferramenta externa.
- **O que os sobreviventes revelaram:** testes que não existiam. Por exemplo, nenhum teste conferia se a análise agregada usava o p99 e não o p95, se uma detecção exatamente no início da falha contava como alarme falso, ou se os contadores de alarme falso do controle somavam alguma coisa.
- **O teste de mutação mentiu uma vez:** um `.pyc` velho de um mutante do mesmo tamanho, gravado no mesmo segundo, fez o Python rodar o bytecode errado. Apareceu como um teste que falhava só no conjunto completo. Corrigi o script (apagar o cache a cada mutante) e refiz todas as rodadas.
- **Testes que reproduzem bugs reais:** quando o orquestrador do Flagger descartou execuções em segundos, primeiro mudei o cluster falso para reproduzir o defeito, vi o teste falhar e só então corrigi.

## Como funciona

Um mutante é um par: um trecho do código e a versão alterada. O script exige que o trecho apareça exatamente uma vez, aplica a troca, imprime as linhas que mudaram e roda os testes escolhidos. Se algum teste falha, o mutante está **morto**: os testes perceberam. Se nenhum falha, está **vivo**: ou falta um teste, ou a mudança não altera o comportamento (mutante equivalente) [1].

```json
[["    hit = label is not None and t_on < label <= t_off + 60",
  "    hit = label is not None and t_on <= label <= t_off + 60"],
 ["AGG_QUANTILE = 0.99", "AGG_QUANTILE = 0.95"]]
```

Os mutantes são escritos à mão, um por decisão que importa: cada comparação de limite, cada constante congelada no pré-registro, cada linha que conta ou filtra alguma coisa.

<figure class="fig">
<img src="{{ "/assets/img/teste-de-mutacao-experimento/mutantes-pt.svg" | relative_url }}" alt="Barras por commit, na ordem: de 2 a 35 mutantes cada, quase todos mortos (azul); sobreviventes equivalentes (laranja) em três commits: um no do manifesto, dois no do orquestrador do Flagger e um no do registro de checagens." loading="lazy">
<figcaption>Mutantes por commit, como registrados nas mensagens. Alguns conjuntos foram rodados de novo depois de mudanças e aparecem mais de uma vez. Os quatro vivos (laranja) foram analisados um a um e são equivalentes.</figcaption>
</figure>

## O que os sobreviventes revelaram

Os números da figura são os finais. No caminho, vários mutantes sobreviveram na primeira rodada. Cada um virou um teste novo antes do commit:

| Mutante que sobreviveu | O que faltava | Teste acrescentado |
|---|---|---|
| A análise por versão usar p95 em vez de p99 | nada conferia o quantil | uma janela em que só o p99 vê a falha |
| Detecção exatamente no rótulo do início da falha contar como acerto | o limite inferior não tinha caso de borda | uma detecção no rótulo t_on é alarme falso |
| Os contadores de alarme falso do controle sempre em zero | os dados de teste não tinham alarme no controle | controle com 5 falhas não seguidas (só o Flagger dispara) e com 3 seguidas |
| A emulação do Flagger com razão 1,30× igual à de 1,15× | as campanhas de teste não separavam as duas | campanhas com falha de 10%, em que 1,15× detecta e 1,30× quase nunca |
| A falha do dashboard simulado ligar antes da hora | os testes só olhavam o heavy-reports | `dashboard` com falha a partir da janela 5 |
| Restauração do runner sem gravar no diário de rollouts | o caso só era coberto junto com outro | restauração sozinha, conferindo o diário |
| Leitura do σ da v2 vindo da v1 | v1 e v2 sempre tinham o mesmo σ nos testes | σ diferente em cada versão |

Leitura: quase todos os buracos eram do mesmo tipo. O dado de teste era "bonito demais" e não distinguia o código certo de uma variação próxima.

## O dia em que o teste de mutação mentiu

Depois de uma rodada de mutação, um teste passou a falhar no conjunto completo e a passar quando rodado sozinho. O arquivo estava certo. O que estava errado era o bytecode.

O Python guarda o código compilado em `__pycache__` e decide se ele está atualizado comparando a data de modificação do fonte, em segundos, e o tamanho [2]. Um mutante que troca `v2` por `v1` tem o mesmo tamanho do original. Se ele é gravado e restaurado no mesmo segundo, o `.pyc` gerado com o mutante continua parecendo válido, e o Python executa o código mutante com o fonte correto no disco.

O efeito vale nos dois sentidos: um mutante pode parecer morto por causa do bytecode do mutante anterior, ou vivo porque rodou o bytecode do original. A correção foi apagar o cache antes de cada mutante e rodar os testes sem gravar bytecode (`python3 -B`, `PYTHONDONTWRITEBYTECODE=1`). Refiz todas as 19 rodadas daquela sessão. Os resultados se mantiveram, mas eu não tinha como saber disso sem refazer.

## Testes que reproduzem o defeito antes da correção

O runner do teste com o Flagger roda contra um cluster falso que usa o código real do endpoint de administração do app, com um relógio falso. No segundo piloto em cluster, todas as tentativas foram descartadas em segundos. A causa era que, logo depois de uma revisão nova, o Canary ainda mostra a fase da revisão anterior. O cluster falso não modelava isso. Primeiro mudei o cluster falso para devolver a fase velha, vi 17 testes falharem, e só então corrigi o orquestrador. O teste que hoje protege esse caso nasceu do defeito real.

## Limites

- **Os mutantes são meus.** Escolhi onde mutar; um operador que eu não pensei pode esconder um buraco. Uma ferramenta como mutmut geraria mutantes de forma sistemática. Não usei.
- **Equivalência é julgamento meu.** Expliquei cada um dos 4 no commit (por exemplo, uma checagem de tamanho redundante com o hash do prefixo), mas não provei formalmente.
- **As contagens vêm das mensagens de commit** e incluem rodadas repetidas. Elas medem esforço e resultado, não a cobertura do código.

## Como reproduzir

Em [`labs/gray-failure-canary-istio/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/gray-failure-canary-istio):

1. O script: `scripts/mutar.py`. Os conjuntos de mutantes usados: `scripts/mutantes/*.json`.
2. Um exemplo: `cd code/triage && python3 ../../scripts/mutar.py market_emul.py "test_market_emul" ../../scripts/mutantes/mme.json`. Critério: `14/14 mortos`.
3. As contagens da figura: `data/mutacao.json`, extraído das mensagens de commit do repositório do experimento.

## Referências

1. Y. Jia, M. Harman, "An Analysis and Survey of the Development of Mutation Testing", IEEE Transactions on Software Engineering, 2011. <https://doi.org/10.1109/TSE.2010.62>. Sustenta: mutantes, mutantes equivalentes e o que o teste de mutação mede.
2. PEP 552, "Deterministic pycs". <https://peps.python.org/pep-0552/>. Sustenta: a validação do `.pyc` por data de modificação e tamanho do fonte.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
