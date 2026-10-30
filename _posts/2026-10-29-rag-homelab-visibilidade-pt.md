---
title: "RAG no homelab: 92% do meu índice era ruído, e o log de consultas mostrou"
lang: pt-BR
permalink: /pt/2026/10/29/rag-homelab-visibilidade/
description: "Notas de laboratório: busca semântica sobre as minhas notas de infraestrutura (Qdrant, indexador incremental, ferramenta MCP no OpenCode), com latência medida, o ambiente completo e o passo a passo para reproduzir. O achado: dados de benchmark gravados no vault viraram 92% do índice, e excluí-los reconstruiu o ranking."
image: /assets/img/rag-homelab-visibilidade/cover-pt.png
---

*[Read in English]({{ "/en/2026/10/29/rag-homelab-visibilidade/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>Versão 2 · 29 de outubro de 2026 · <a href="#o-que-mudou">o que mudou</a></span></p>

Montei uma busca semântica sobre as minhas notas de infraestrutura para o assistente de código consultar, com um log de cada consulta para eu enxergar o que acontece. Na segunda hora de uso, o indexador foi de **64 para 971 trechos em uma única execução**, porque eu tinha gravado no vault os dados de um benchmark. **92% do índice (890 de 972 trechos) deixou de ser nota e virou dado bruto**, e um único arquivo respondia por 52%. Este post mostra como medi isso, o que mudou no ranking quando excluí esses diretórios do indexador (a correção está aplicada) e como repetir o experimento.

É um laboratório pessoal, não produção, com um corpus pequeno. Os números valem para este ambiente; os limites vêm logo depois do resumo.

<div class="tiles">
<div class="tile"><div class="tile-value">92%</div><div class="tile-label">dos 972 trechos do índice vinham de dados de benchmark, não de notas (890 de 972)</div></div>
<div class="tile"><div class="tile-value">4 → 8</div><div class="tile-label">perguntas (de 9) com o arquivo esperado entre os 3 primeiros, antes e depois de reconstruir o índice sem esses dados (972 → 82 trechos)</div></div>
<div class="tile"><div class="tile-value">~20 ms</div><div class="tile-label">mediana de uma consulta completa (embedding + busca): 20,6 ms com 972 trechos, 19,7 ms com 82; 30 repetições cada, 0 erros</div></div>
</div>

## Resumo

- **O indexador só excluía arquivos por prefixo (`.` e `_`), não por diretório.** Os dados do benchmark entraram na execução horária seguinte: 6 para 50 arquivos, 64 para 971 trechos, 48 s.
- **Apliquei a exclusão por diretório e reindexei: 972 → 82 trechos.** O arquivo esperado ficou em 1º lugar em 4 de 9 perguntas (antes 3) e entre os 3 primeiros em 8 de 9 (antes 4).
- **As perguntas fora do tema caíram de 0,60 para 0,44 e 0,48 de score no 1º resultado**, abaixo de todas as perguntas com arquivo-alvo (mínimo 0,53). A margem é de 0,05 e a amostra tem só 2 perguntas fora do tema, então não recomendo ainda um limiar.
- **A simulação que fiz antes de mexer no índice (filtrar `dados/` no cliente) deu o mesmo resultado que o índice reconstruído, em 11 de 11 perguntas**, com a mesma posição e o mesmo score.
- **A consulta é barata e não depende do tamanho do índice nesta escala:** mediana de 19,7 ms com 82 trechos e 20,6 ms com 972. O embedding da pergunta responde por cerca de 80% do tempo. Em ambos os casos o Qdrant não usa HNSW; faz busca exata.
- **A guarda de segredos funcionou:** pulou 2 arquivos sintéticos que continham tokens fictícios.

<div class="callout">
<p><strong>Antes de ler os números:</strong></p>
<ul>
<li>São 11 perguntas, 9 com um arquivo-alvo que <strong>eu</strong> escolhi antes de olhar o resultado. É um teste de fumaça, não uma medição de recall.</li>
<li>Depois da limpeza o índice tem só <strong>7 arquivos</strong>. Cair entre os 3 primeiros acontece por acaso em cerca de 43% das vezes (≈ 4 de 9); o 1º lugar, em cerca de 14% (≈ 1,3 de 9). O 1º lugar é a métrica que importa aqui.</li>
<li>Um único modelo de embedding, sem comparação com outro nem com busca por palavra-chave.</li>
</ul>
</div>

## O que mudou nesta versão {#o-que-mudou}

<div class="callout">
<p>A primeira versão deste post, publicada e retirada no mesmo dia, concluía que <strong>o score do embedding não serve para filtrar</strong>, porque perguntas fora do tema tiravam 0,60. Eu não tinha testado o ranking sem os dados do benchmark. Ao testar, a conclusão mudou:</p>
<ul>
<li>o problema principal era o <strong>corpus contaminado</strong>, não o score;</li>
<li>duas perguntas da primeira versão foram trocadas por perguntas neutras sobre o homelab, então os números do antes e do depois mudaram (por exemplo, o arquivo esperado entre os 3 primeiros passou de 6 para 4 antes da limpeza);</li>
<li>a primeira versão também expunha números de containers e um caminho interno que não deveriam ter sido publicados, e trazia só uma medição simples, sem o ambiente nem os passos para repetir. Tudo foi removido ou refeito.</li>
</ul>
</div>

## Ambiente

| Item | Valor |
|---|---|
| Hospedeiro | AMD Ryzen 5 5600G (12 threads), 62 GB de RAM, Proxmox VE 8.4.19, kernel 6.14.11 |
| GPUs do hospedeiro | duas placas AMD com PCI ID 1002:7590, 16 GB cada (o nome comercial não aparece no `pci.ids` do hospedeiro) |
| Servidor de embeddings | llama.cpp build `b216-f12cc6d`, HIP (ROCm 7.2.3) na GPU 1, Qwen3-Embedding-0.6B quantizado em Q8_0, contexto 4096, 4 slots, 2 threads |
| Banco vetorial | Qdrant 1.20.0 em container, volume nomeado, chave de API |
| Coleção | 1024 dimensões, distância cosseno, HNSW padrão (m=16, ef_construct=100), 2 segmentos |
| Réplica do vault | Syncthing 1.19.2, pasta em modo *receive-only* |
| Indexador | Python 3.11.2, execução a cada hora por timer do systemd |
| Cliente | OpenCode v2.2.1, ferramenta MCP local por stdio |
| Rede | mesma LAN para PC de trabalho, servidor de embeddings e Qdrant |
| Índice antes / depois | 50 arquivos e 972 trechos / 7 arquivos e 82 trechos |
| Estado na medição | servidor de embeddings aquecido por 11 consultas anteriores no mesmo script |

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/ambiente-pt.svg" | relative_url }}" alt="Diagrama do ambiente: o PC de trabalho, com o vault, o OpenCode e a ferramenta MCP, liga-se pela LAN a um hospedeiro Proxmox com três blocos: um container de serviços com Qdrant, Syncthing e o indexador; a GPU 0, com o modelo de fallback do roteador, fora do RAG; e a GPU 1, com o servidor de embeddings Qwen3-Embedding-0.6B e a completação de código." loading="lazy">
<figcaption>Ambiente do experimento. Em azul, o que participa do RAG; em cinza, o que roda no mesmo hospedeiro mas não participa.</figcaption>
</figure>

As GPUs 0 e 1 também atendem outros serviços (o roteador e a completação de código). Só a GPU 1 participa do RAG, por causa do servidor de embeddings.

## A arquitetura

O fluxo de dados é de mão única do PC para o servidor, e a consulta faz o caminho inverso só até o Qdrant.

<pre class="mermaid">
flowchart LR
  V["vault no PC"] -->|Syncthing| R["réplica receive-only"]
  R --> I["indexador"]
  I -->|"trechos"| E["servidor de embeddings"]
  I -->|"upsert"| Q["Qdrant"]
  O["OpenCode"] --> M["MCP buscar_vault"]
  M -->|"pergunta"| E
  M -->|"busca"| Q
  M -.->|"log"| L["consultas.log"]
</pre>

- **Indexar a partir de uma réplica**, não do vault direto: o vault fica no PC, o indexador num servidor sempre ligado. A pasta *receive-only* impede que algo do servidor volte e altere as notas.
- **Indexador incremental:** hash SHA-256 por arquivo, trechos de 1000 caracteres com 150 de sobreposição, divididos primeiro por título Markdown. Ele pula arquivos que começam com `.` ou `_`, diretórios listados em `EXCLUDE_DIRS` e arquivos que casam com um padrão de segredo (chaves AWS, tokens do GitHub, chaves privadas, `password`/`token` seguidos de valor).
- **Ferramenta MCP:** pega o embedding da pergunta, busca 4k candidatos no Qdrant e devolve no máximo um trecho por arquivo. Cada consulta vira uma linha em `consultas.log`, com a pergunta, o `k` e os arquivos devolvidos.

## Como reproduzir

Pré-requisitos: Docker, Python 3.11 ou mais novo, um `llama-server` do llama.cpp (Vulkan, ROCm, CUDA ou CPU) e o arquivo `Qwen3-Embedding-0.6B-Q8_0.gguf`. Tempo estimado: 30 a 45 minutos. Todo o material está em [`labs/rag-homelab-visibilidade/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/rag-homelab-visibilidade); os valores entre `<...>` são placeholders.

1. **Qdrant.** Rode `config/qdrant.sh` com uma chave de API sua. *Funcionou se* `curl -H "api-key: <CHAVE>" http://<HOST>:6333/` devolver um JSON com `"version":"1.20.0"`.
2. **Servidor de embeddings.** Use `config/llama-embed.service` (ou o comando equivalente):

   ```bash
   llama-server -m Qwen3-Embedding-0.6B-Q8_0.gguf -ngl 99 -c 4096 \
     --embeddings --host 0.0.0.0 --port 8084 --api-key <CHAVE> -t 2
   ```

   *Funcionou se* `POST /v1/embeddings` com `{"input":["teste"]}` devolver um vetor de 1024 números.
3. **Configuração.** Copie `config/rag.env.example` para `rag.env` e preencha. Nada disso vai para o repositório.
4. **Primeira indexação** (deixe `EXCLUDE_DIRS` vazio se quiser reproduzir o "antes"):

   ```bash
   RAG_ENV=rag.env RAG_LOG=rag-indexer.log python3 scripts/rag-indexer.py
   ```

   *Funcionou se* imprimir `resumo: arquivos=N alterados=N ... trechos_totais=M`.
5. **Segunda execução, sem mudar nada.** *Funcionou se* `alterados=0` e `duracao` perto de 0 s. Isso confirma o incremental.
6. **Medir o "antes":**

   ```bash
   RAG_ENV=rag.env SAIDA=data/resultado_antes.json python3 scripts/medir_consultas.py
   ```

   Edite `data/queries.json` antes, com perguntas e arquivos-alvo do **seu** corpus.
7. **Excluir diretórios.** Em `rag.env`, `EXCLUDE_DIRS=dados,rascunhos` (nomes de diretório, em qualquer nível) e rode o indexador de novo. *Funcionou se* o log mostrar `removido do indice (arquivo sumiu)` e `trechos_totais` cair.
8. **Medir o "depois"** com `SAIDA=data/resultado_depois.json`. A saída também traz a simulação por filtro (`dados/` removido no cliente), para você conferir se ela bate com o índice reconstruído.
9. **Timer (opcional).** `config/rag-indexer.service` e `config/rag-indexer.timer`, com `systemctl enable --now rag-indexer.timer`.
10. **Ferramenta MCP.** Registre `scripts/mcp_server.py` como MCP local (`config/opencode-mcp.json`), com `RAG_ENV` apontando para o `rag.env` no ambiente de onde o OpenCode é iniciado. *Funcionou se* uma pergunta pelo OpenCode criar uma linha em `consultas.log`.
11. **Figuras:** `python3 scripts/make_figures.py data <saida>` em um ambiente com matplotlib.

**Variações que eu não testei:** tamanho do trecho e da sobreposição, outro modelo de embedding, busca híbrida com palavra-chave e quantização diferente do modelo.

## Resultados

### 1. O que entrou no índice

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/indice-pt.svg" | relative_url }}" alt="À esquerda, gráfico em degraus do número de trechos no índice entre 21:28 e 01:49 UTC: 61 a 64 trechos até 22:36, 971 depois, 994 às 01:37 e 82 ao fim, após a exclusão. À direita, barra empilhada com a origem dos 972 trechos: 82 de notas reais, 389 de outros dados do benchmark e 501 de um único arquivo." loading="lazy">
<figcaption>Esquerda: trechos no índice a cada execução do indexador, a partir do log (horário UTC). Direita: origem dos 972 trechos antes da correção. Um único arquivo, o pacote de avaliação do piloto do benchmark, tem 501 trechos, mais que o dobro de todas as notas somadas. Às 01:37 o timer indexou 2 arquivos dos meus rascunhos (994); às 01:49 apliquei a exclusão.</figcaption>
</figure>

| Etapa | Valor |
|---|---|
| Arquivos Markdown elegíveis | 50 |
| Pulados pela guarda de segredos | 2 |
| Indexados | 48 |
| Trechos no índice | 972 |
| …de notas reais | 82 (8%) |
| …do pacote de avaliação | 501 (52%) |
| …de outros dados do benchmark | 389 (40%) |
| **Depois da exclusão** | **7 arquivos, 82 trechos** |

A execução das 22:36 UTC (19:36 no horário local) reindexou 42 arquivos em 48,1 s. Antes disso, o índice tinha 6 arquivos. O histórico completo, incluindo as vezes em que alternei a exclusão para medir, está em `data/indexer_historico.csv`.

### 2. O ranking antes e depois

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/scores-pt.svg" | relative_url }}" alt="Gráfico de halteres com o score do primeiro resultado para 11 perguntas, antes (círculo vazio, índice de 972 trechos) e depois (círculo cheio, índice de 82 trechos). A maioria não muda. Três mudam: cliente do braço Claude vai de 0,68 para 0,56; receita de bolo de 0,60 para 0,44; previsão do tempo de 0,60 para 0,48. Uma faixa sombreada marca o intervalo de 0,53 a 0,70 das perguntas com arquivo-alvo." loading="lazy">
<figcaption>Score do 1º resultado por pergunta, antes (círculo vazio) e depois (círculo cheio) de reconstruir o índice sem <code>dados/</code>. Onde os círculos coincidem, o 1º resultado não era de <code>dados/</code>. As duas perguntas fora do tema (cinza) saem da faixa das perguntas com alvo.</figcaption>
</figure>

| Métrica (9 perguntas com alvo) | Antes (972) | Depois (82) | Δ |
|---|---|---|---|
| Arquivo esperado em 1º | 3 | 4 | +1 |
| Arquivo esperado entre os 3 primeiros | 4 | 8 | +4 |
| Score do 1º resultado nas 2 perguntas fora do tema | 0,60 e 0,60 | 0,44 e 0,48 | −0,16 e −0,12 |
| Menor score entre as perguntas com alvo | 0,53 | 0,53 | 0 |

Posição do arquivo esperado onde algo mudou:

| Pergunta | Antes | Depois |
|---|---|---|
| modelo e dimensões dos embeddings | 41ª | 5ª |
| rotas do roteador e prioridade | 8ª | 3ª |
| como reinicio o roteador | 5ª | 3ª |
| como testar o fallback do roteador | 5ª | 3ª |
| cliente do braço Claude | 4ª | 1ª |

Quatro leituras:

1. **A limpeza ajudou onde havia poluição, e o resto é do corpus.** Os arquivos de `dados/` ocupavam o 1º lugar em 4 das 11 perguntas antes. Depois, o que fica na frente do alvo são outras notas sobre o mesmo assunto: para "como reinicio o roteador" e "como testar o fallback", o 1º resultado é o relatório do RAG (0,67 e 0,70).
2. **O pacote de avaliação era um "hub", e a limpeza não elimina o efeito, só o muda de lugar.** Antes, ele aparecia entre os 3 primeiros em 10 de 11 perguntas (e em 1º em 3). Depois, o plano do blog, uma nota longa e de tema amplo, aparece entre os 3 primeiros em 10 de 11. Com 7 arquivos, é difícil evitar.
3. **A separação das perguntas fora do tema existe, mas é estreita:** 0,48 contra 0,53. Com 2 perguntas não dá para fixar um limiar. O próximo passo é montar umas 30 perguntas fora do tema e ver onde está o teto.
4. **Parte dos "erros" é palpite meu.** Marquei os alvos antes de olhar e mantive a marcação, mesmo quando outra nota respondia a pergunta de forma defensável.

### 3. Latência

<figure class="fig">
<img src="{{ "/assets/img/rag-homelab-visibilidade/latencia-pt.svg" | relative_url }}" alt="Três faixas de pontos com 30 medições cada, no índice de 972 trechos: embedding da pergunta, de 15 a 22 ms, mediana 16,2; busca no Qdrant, de 2,7 a 4,8 ms, mediana 4,3; total, de 17,6 a 27 ms, mediana 20,6. Marcas verticais indicam a mediana e o p95." loading="lazy">
<figcaption>30 repetições (10 de cada uma de 3 perguntas), com o índice de 972 trechos. Traço preto: mediana. Tracejado vermelho: p95. O embedding da pergunta responde por cerca de 80% do tempo total.</figcaption>
</figure>

| Etapa | Mediana (972) | p95 (972) | Mediana (82) | p95 (82) |
|---|---|---|---|---|
| Embedding da pergunta | 16,2 ms | 20,9 ms | 15,7 ms | 20,6 ms |
| Busca no Qdrant | 4,3 ms | 4,7 ms | 4,0 ms | 4,3 ms |
| Total | 20,6 ms | 25,4 ms | 19,7 ms | 24,7 ms |
| Total, mín–máx | 17,6–27,0 ms | | 16,2–25,0 ms | |

A diferença entre os dois índices (cerca de 0,3 ms na busca) fica dentro da variação das medições. Nos dois casos o Qdrant não construiu o índice HNSW: o parâmetro `indexing_threshold` do otimizador é de 10.000 KB por segmento, e 972 vetores de 1024 floats ocupam cerca de 3.900 KB. A busca varre todos os vetores. Isso muda a partir de cerca de 2.500 vetores; com um corpus maior, a latência de busca medida aqui deixa de valer.

## O que deu errado

| Sintoma | Causa | Correção |
|---|---|---|
| Perguntas fora do tema com score 0,60; arquivo de dados entre os 3 primeiros em 10 de 11 consultas | Dados do benchmark gravados no vault; o indexador excluía só por prefixo | **Aplicada:** `EXCLUDE_DIRS=dados,rascunhos` no `rag.env`; o script antigo tem backup. 972 → 82 trechos |
| 994 trechos às 01:37 | Os rascunhos deste post entraram no índice | `rascunhos` entrou na lista de exclusão |
| Vários trechos do mesmo arquivo nos resultados | A busca devolvia os melhores trechos sem agrupar | Buscar 4k candidatos e devolver um por arquivo |
| 2 arquivos fora do índice | A guarda de segredos casou com um token fictício em cada um (`ghp_...` e `sk-dev-...`) | Comportamento esperado; os dois são cenários sintéticos |
| Conclusão errada na primeira versão deste post | Eu não tinha testado o ranking sem os dados do benchmark | Medição refeita e post reescrito |

## As sete perguntas de verificação

Baseadas no checklist de benchmarking de Brendan Gregg.

| Pergunta | Resposta |
|---|---|
| Por que não o dobro? | O embedding da pergunta é cerca de 80% do tempo. Não investiguei se o gargalo é HTTP, tokenização ou GPU |
| Foi ajustado? | Tudo no padrão (HNSW, llama.cpp, 4 slots). Nada otimizado |
| Estourou limites? | Não. 4 KB por vetor numa LAN, sem relevância para banda ou VRAM |
| Deu erro? | 0 erros em todas as execuções |
| Reproduz? | Medianas de embedding de 15,7 a 16,4 ms em seis execuções de 30 repetições. Os scores do ranking foram idênticos em todas as execuções repetidas |
| Importa? | Só para corpora pequenos; a partir de cerca de 2.500 vetores o Qdrant passa a construir HNSW e a latência muda. E com 7 arquivos, o acaso explica boa parte do "entre os 3 primeiros" |
| Aconteceu mesmo? | Sim: confirmei pela contagem de pontos no Qdrant, pelo log do indexador e pela simulação, que bateu com o índice reconstruído em 11 de 11 |

## Limites

- 11 perguntas, 9 com alvo escolhido por mim; amostra muito pequena para recall.
- Depois da limpeza são 7 arquivos; o acaso explica cerca de 43% dos "entre os 3 primeiros".
- O "antes" exigiu recriar o estado de 972 trechos: a exclusão ficou desligada por alguns minutos só para medir. O histórico está em `indexer_historico.csv`.
- Um modelo de embedding, sem comparação.
- Latência medida na LAN, com o servidor de embeddings aquecido.
- Pendente: ampliar as perguntas fora do tema (cerca de 30) e testar o retorno do servidor de modelos após reinício.

## Material para reproduzir

[`labs/rag-homelab-visibilidade/`](https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs/rag-homelab-visibilidade): scripts de indexação, MCP, medição e figuras; dados brutos das duas medições e o histórico do indexador; configurações com placeholders.

## Referências

1. Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", NeurIPS 2020, arXiv:2005.11401. <https://arxiv.org/abs/2005.11401>. Sustenta: o padrão RAG (recuperar trechos e entregá-los ao modelo) que este post implementa.
2. Zhang et al., "Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models", arXiv:2506.05176, 2025. <https://arxiv.org/abs/2506.05176>. Sustenta: o modelo de embeddings usado (Qwen3-Embedding-0.6B, 1.024 dimensões).
3. Qdrant, "Indexing" (documentação). <https://qdrant.tech/documentation/concepts/indexing/>. Sustenta: parâmetros do HNSW (m, ef_construct) e o limiar abaixo do qual a busca exata é preferida.
4. Qdrant, "Optimizer" (documentação). <https://qdrant.tech/documentation/ops-optimization/optimizer/>. Sustenta: o `indexing_threshold_kb` (padrão 10.000 KB) que decide quando o segmento ganha índice HNSW, base da conta de ~2.500 vetores.
5. Syncthing, "Folder Types" (documentação). <https://docs.syncthing.net/users/foldertypes.html>. Sustenta: o modo *receive-only* da réplica, que não devolve alterações locais.
6. Model Context Protocol, especificação 2025-06-18. <https://modelcontextprotocol.io/specification/2025-06-18>. Sustenta: o protocolo da ferramenta `buscar_vault` usada pelo OpenCode (transporte stdio).
7. Brendan Gregg, "Evaluating the Evaluation: A Benchmarking Checklist", 2018. <https://www.brendangregg.com/blog/2018-06-30/benchmarking-checklist.html>. Sustenta: as sete perguntas de verificação aplicadas às medições.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
