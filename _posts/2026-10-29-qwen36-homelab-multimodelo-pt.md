---
title: "Qwen3.6 no homelab: multimodelo com uma GPU"
lang: pt-BR
permalink: /pt/2026/10/29/qwen36-homelab-multimodelo/
description: "Como extrair máximo de uma GPU em Proxmox: modelo forte sempre carregado, fallback com warm pool, código pequeno separado e servidor de embedding dedicado."
---

*[Read in English]({{ "/en/2026/10/29/qwen36-homelab-multimodelo/" | relative_url }})*

---

## O hardware

- Proxmox host, GPU 0: placa de geração anterior, VRAM limitada.
- Proxmox host, GPU 1: placa secundária, para modelos menores.
- Duas máquinas: CT 300 (modelos), CT 301 (roteador + Qdrant).

## A estratégia: um modelo por GPU, sem dividir VRAM

Em vez de tentar carregar múltiplos modelos na mesma GPU (o que causa OOM ou swapping), coloquei **um servidor por GPU**:

### GPU 0 — Modelo forte (sempre carregado)

```
Porta: 8080
Modelo: Qwen3.6-35B-A3B-Q4_K_M
Modo: sleeping desativado (sempre em memória)
VRAM: ~20 GB ocupados continuamente
```

### GPU 1 — Código + Embedding

```
GPU 1a: FIM + Qwen2.5-Coder-3B (porta 8083)
GPU 1b: Embeddings + Qwen3-Embedding-0.6B (porta 8084)
```

A separação faz sentido: o modelo de código é leve (~6GB) e o embedding é ainda menor (~2GB). Ambos rodam em paralelo na GPU 1 sem competir com o 35B.

## O que fiz com o Qwen3.8-27B

O Qwen3.8-27B-Q6_K.gguf ocupava 30 GB e já era substituído pelo Qwen3.6-35B-A3B. Apaguei o arquivo e confirmei que nada o referenciava mais no código. A GPU 0 agora tem um modelo maior (35B) com a mesma quantização (Q4) — mais parâmetros, mesma pegada de VRAM.

## A decisão quente vs fria

Manter o qwen3-14b sempre carregado na GPU 0 custa ~40W contínuos, mas elimina ~19s de loading no fallback. Escolhi quente. Alternativa seria:

- **Modo sleeping:** libera VRAM quando ocioso, mas o processo filho mantém GPUs em 100% de uso.
- **Timer de descarregamento:** descarrega modelos sleeping via API a cada 2 min. A GPU volta ao normal.

## O que aprendi

1. **Não divida GPU para modelos grandes:** um por GPU é mais estável que tentar split.
2. **Q4 > Q6 para VRAM:** Qwen3.6-35B em Q4 usa ~20GB; o Qwen3.8-27B em Q6 usava 30GB. Menos bits = mais espaço para outros modelos.
3. **Sempre-carregado tem custo:** 40W é barato comparado a 19s de loading para um usuário.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
