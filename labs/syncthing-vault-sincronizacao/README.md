# Syncthing: material para reproduzir

Acompanha o post "Syncthing entre sub-redes" (pt-BR e en).

- `scripts/medir_propagacao.py`: cria um arquivo numa pasta de rascunhos (excluída do índice) e mede quando ele aparece no hub e na réplica.
- `data/sync_medida.json`: 10 execuções, com tempos em segundos.

Variáveis: `HOST_SSH`, `CT_HUB`, `CT_REPLICA`, `CAMINHO_HUB`, `CAMINHO_REPLICA`, `PASTA_LOCAL`. Os relógios do PC e dos containers devem estar sincronizados.
