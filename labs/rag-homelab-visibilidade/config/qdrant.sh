#!/bin/sh
# Qdrant 1.20.0 em container, armazenamento em volume nomeado e chave de API por variavel de ambiente.
docker run -d --name qdrant --restart unless-stopped \
  -p 6333:6333 \
  -v qdrant-data:/qdrant/storage \
  -e QDRANT__SERVICE__API_KEY="<CHAVE_API_QDRANT>" \
  qdrant/qdrant:latest   # resolveu para 1.20.0 neste laboratorio; fixe a versao
