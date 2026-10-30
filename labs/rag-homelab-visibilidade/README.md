# RAG no homelab: material para reproduzir

Acompanha o post "RAG no homelab: 92% do meu índice era ruído, e o log de consultas mostrou" (pt-BR e en).

## Conteúdo

```
scripts/
  rag-indexer.py       indexador incremental (hash, trechos de 1000/150, guarda de segredos)
  mcp_server.py        ferramenta MCP buscar_vault (stdio), com log de consultas
  medir_consultas.py   ranking (com simulação por filtro de dados/) + latência (30 repetições)
  medir_baseline.py    primeira medição (11 perguntas, 3 repetições)
  contar_origem.py     conta trechos do índice por origem
  make_figures.py      gera as figuras do post (matplotlib)
data/
  queries.json                 11 perguntas e arquivo-alvo de cada uma
  resultado_antes.json         medição com o índice de 972 trechos (inclui a simulação por filtro)
  resultado_depois.json        medição com o índice reconstruído sem dados/ (82 trechos)
  resultado_baseline.json      primeira medição (3 repetições por pergunta, índice de 972)
  composicao.json              trechos por origem, antes da correção
  indexer_historico.csv        resumos do indexador (do log), horário em UTC
config/
  qdrant.sh, llama-embed.service, rag-indexer.service/.timer, rag.env.example, opencode-mcp.json
```

## Como rodar

1. Suba o Qdrant e o servidor de embeddings (`config/`), e crie `rag.env` a partir de `config/rag.env.example`.
2. Exporte `RAG_ENV=rag.env` e rode `python3 scripts/rag-indexer.py`.
3. Edite `data/queries.json` para o **seu** corpus e rode `SAIDA=data/resultado_antes.json python3 scripts/medir_consultas.py`. Depois, defina `EXCLUDE_DIRS` no `rag.env`, reindexe e rode de novo com `SAIDA=data/resultado_depois.json`.
4. Figuras: `python3 scripts/make_figures.py data <saida> [png]`, em um ambiente com matplotlib.

Os passos completos, com o critério de sucesso de cada um, estão no post.

## Avisos

- Nenhuma chave, endereço ou caminho local está neste material. Tudo o que é segredo vem de variável de ambiente ou do arquivo apontado por `RAG_ENV`.
- Os arquivos em `data/` são os mesmos que geraram as figuras do post.
- Os caminhos de arquivo em `data/` foram trocados por aliases (`notas/nota-NN.md`, `dados/arquivo-NN.md`, `dados/pacote-avaliacao.md`). As perguntas de `queries.json` são do meu corpus e precisam ser trocadas pelas suas, com os arquivos-alvo do seu vault.
