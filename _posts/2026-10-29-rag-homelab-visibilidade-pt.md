---
title: "RAG no homelab com visibilidade: o que medi, e por que o score do embedding não serve de filtro"
lang: pt-BR
permalink: /pt/2026/10/29/rag-homelab-visibilidade/
description: "Notas de laboratório: uma busca semântica sobre as minhas notas de infraestrutura (Qdrant, indexador incremental, ferramenta MCP no OpenCode), com latência medida e um achado sobre scores que atrapalha quem pensa em usar limiar."
---

*[Read in English]({{ "/en/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

Eu queria que o assistente de código consultasse as minhas notas de infraestrutura (planos, relatórios, documentação do homelab) **e que eu pudesse ver cada etapa** da consulta, em vez de receber só a resposta final. Este post descreve a montagem, mostra o que medi e registra um achado incômodo: o score do embedding não separa um acerto de uma pergunta sem relação nenhuma com as notas.

É um laboratório pessoal, com um corpus pequeno. Os números valem para este ambiente e os limites estão no fim.

<div class="tiles">
<div class="tile"><div class="tile-value">~12 ms</div><div class="tile-label">mediana para gerar o embedding da pergunta (3 repetições por pergunta, 11 perguntas)</div></div>
<div class="tile"><div class="tile-value">~5 ms</div><div class="tile-label">mediana da busca no banco vetorial</div></div>
<div class="tile"><div class="tile-value">5 de 9</div><div class="tile-label">perguntas com o arquivo esperado em 1º lugar (6 de 9 entre os 3 primeiros)</div></div>
</div>

## Resumo

- **A montagem é pequena e cada etapa deixa rastro.** Um banco vetorial, um indexador incremental, um servidor de embeddings e uma ferramenta MCP que registra cada consulta.
- **A busca é barata.** Cerca de 17 ms somando embedding e busca; o custo real de uma consulta é o do modelo que lê o resultado.
- **O score absoluto não serve de limiar.** Perguntas fora do tema (receita de bolo, previsão do tempo) tiraram 0,60 no primeiro resultado. Acertos legítimos ficaram entre 0,57 e 0,87.
- **Indexei sem querer os meus próprios experimentos.** 890 dos 972 trechos (92%) vêm de dados de benchmark gravados no vault, e um único arquivo deles aparece entre os 3 primeiros em 10 de 11 perguntas.

## A arquitetura

<pre class="mermaid">
flowchart LR
  subgraph PC["PC de trabalho"]
    V["vault (Markdown)"]
    O["OpenCode"]
    M["ferramenta MCP buscar_vault"]
  end
  subgraph LAB["Servidores do laboratório"]
    H["hub Syncthing"]
    R["réplica somente-leitura"]
    I["indexador (a cada hora)"]
    Q["Qdrant"]
    E["servidor de embeddings"]
  end
  V -->|Syncthing| H
  H -->|receive-only| R
  R --> I
  I -->|"embeddings dos trechos"| E
  I -->|"upsert"| Q
  O --> M
  M -->|"embedding da pergunta"| E
  M -->|"busca por cosseno"| Q
  M -. "log de cada consulta" .-> L["consultas.log"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

Decisões que sustentam o desenho:

- **Indexar a partir de uma réplica, não do vault direto.** O vault fica no PC; o indexador roda num servidor que fica ligado. Uma réplica *receive-only* garante que nada do servidor volta e altera as notas.
- **Banco vetorial: Qdrant**, por ser o padrão de self-hosting e não exigir mais nada.
- **Ferramenta MCP no PC**, porque é aqui que o OpenCode roda.

## O indexador

| Parâmetro | Valor |
|---|---|
| Detecção de mudança | hash do arquivo (incremental) |
| Divisão em trechos | por títulos Markdown, 1000 caracteres, 150 de sobreposição |
| Embeddings | Qwen3-Embedding-0.6B, 1024 dimensões, distância cosseno |
| Exclusões | arquivos com padrão de segredo e arquivos que começam com `_` |
| Agenda | timer a cada hora |

Uma segunda execução sem mudanças pulou os 6 arquivos que existiam na época. Depois de reiniciar o servidor, o indexador reindexou só os 2 arquivos alterados.

## Visibilidade: o log de consultas

A ferramenta grava uma linha por consulta, com a pergunta, o `k` pedido e os arquivos devolvidos. Foi isso que me fez perceber o problema da seção seguinte: bastou ler o log e ver arquivos de dados aparecendo em perguntas que não tinham nada a ver com eles.

Um ajuste anterior também veio do log: a busca devolvia vários trechos do mesmo arquivo. Agora a ferramenta busca `4k` candidatos e devolve no máximo um trecho por arquivo.

## O que medi

Fiz 11 perguntas: 9 com um arquivo-alvo que eu escolhi antes de olhar o resultado e 2 sem relação nenhuma com o vault. Cada pergunta rodou 3 vezes para a latência. O script está no repositório de rascunhos, ao lado dos dados brutos.

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/score-top1-pt.svg" | relative_url }}" alt="Barras horizontais com o score do primeiro resultado para 11 perguntas. Acertos em verde variam de 0,57 a 0,87, erros em laranja de 0,53 a 0,68, e as duas perguntas fora do tema em cinza ficam em 0,60." loading="lazy">
<figcaption>Score do primeiro resultado por pergunta. As duas perguntas sem relação com o vault (cinza) tiraram 0,60, dentro da faixa dos acertos (verde). Qualquer limiar que corte as perguntas fora do tema também corta acertos legítimos.</figcaption>
</figure>

Três leituras do gráfico:

1. **Não há limiar absoluto.** Um corte em 0,60 descartaria o acerto de 0,57 (sleeping/GPU) e deixaria passar as duas perguntas fora do tema.
2. **Os scores mais altos coincidem com temas de um arquivo só.** "RDS" e "Grafana" chegam a 0,83 e 0,87, e cada um tem um arquivo dedicado; os temas que aparecem em vários arquivos ficam entre 0,53 e 0,68. Minha hipótese é que a causa seja vocabulário raro, mas não testei isso.
3. **Os "erros" são, em parte, do corpus.** Em "como reinicio o roteador", o primeiro lugar (0,668) ficou empatado entre o pacote de avaliação e um relatório que descreve o reinício do servidor; o arquivo que eu tinha marcado como alvo nem ficou entre os 4 primeiros. A minha marcação foi um palpite, e o índice discordou de forma defensável.

## O achado: indexei o meu próprio benchmark

O índice tem 972 trechos de cerca de 50 arquivos Markdown. Contei por caminho: **890 trechos (92%) vêm do diretório de dados do benchmark**, que gravei no vault, e só 82 vêm das notas de verdade. Um único arquivo, o pacote de avaliação do piloto, responde por 501 trechos (52% do índice) e aparece entre os 3 primeiros em **10 de 11** perguntas, inclusive nas duas fora do tema.

Esse arquivo é enorme e mistura prompts de vários assuntos (Terraform, Kubernetes, shell). Ele tem tantos trechos, e tão variados, que quase sempre algum fica perto da pergunta. Somado ao efeito de hubs (documentos que viram vizinhos de muita coisa no espaço de embeddings), ele contamina o ranking.

O que eu faria, ainda não aplicado:

- **Excluir do índice os diretórios de dados e saídas brutas**, por caminho, e não só por prefixo `_`.
- **Usar a posição relativa, não o score absoluto**, e mostrar o score ao modelo só como informação, nunca como filtro.
- **Medir recall com um conjunto fixo de perguntas** depois de cada mudança no corpus. O script desta medição serve.

## Limites

- 11 perguntas, 9 delas com alvo escolhido por mim: é um teste de fumaça, não uma medição de recall.
- Um único modelo de embedding, sem comparar com outro nem com busca por palavra-chave.
- Latência medida na rede local, com o servidor de embeddings já aquecido.
- O corpus mudou durante o experimento (as saídas do benchmark foram indexadas pelo timer horário).
- Pendente: testar a volta do servidor de modelos depois de reinício; só o servidor do banco foi testado.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
