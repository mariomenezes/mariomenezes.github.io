---
title: "Multimodelo em duas GPUs de 16 GB: o que cabe, o que não cabe e o que deixou a GPU ocupada"
lang: pt-BR
permalink: /pt/2026/10/29/multimodelo-duas-gpus/
description: "Notas de laboratório: como distribuí modelos de linguagem e de embedding entre duas GPUs de 16 GB num hospedeiro Proxmox, o que não coube, e por que o modo de repouso do llama.cpp não liberou a GPU."
---

*[Read in English]({{ "/en/2026/10/29/multimodelo-duas-gpus/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>29 de outubro de 2026 · <a href="#o-que-deu-errado">o que deu errado</a></span></p>

Queria ter, no mesmo hospedeiro, um modelo de fallback sempre disponível, um modelo pequeno para completar código e um modelo de embeddings para o RAG. O hospedeiro tem duas placas AMD de 16 GB. A pergunta era o que cabe em cada uma e como manter a segunda ociosa quando não está em uso.

## Resumo

- **Modelos acima de 14B não cabem numa placa de 16 GB** com a quantização usada. Um modelo de 27B em Q6 ocupava 30 GB no disco e foi removido.
- **Cada placa tem um papel fixo.** A GPU 0 roda o modelo de fallback do roteador. A GPU 1 roda o modelo de completação de código e o de embeddings.
- **O modo de repouso do llama.cpp não liberou a GPU.** A VRAM era liberada, mas o processo filho mantinha a placa em 100% de uso.
- **O timer só atua na GPU 0.** A cada 2 minutos, ele descarrega os modelos em repouso do roteador. Os servidores de embedding e de completação, na GPU 1, ficam fora dele. Em 5 minutos de amostragem, a GPU 1 ficou em 100% de uso sem pedidos registrados nos logs.

## Ambiente

| Item | Valor |
|---|---|
| Hospedeiro | Ryzen 5 5600G, 62 GB de RAM, Proxmox VE 8.4.19 |
| GPU 0 | AMD, 16 GB, Vulkan, modelo de fallback do roteador |
| GPU 1 | AMD, 16 GB, Vulkan, completação de código e embeddings |
| Servidor | llama.cpp, build `b216-f12cc6d` |

Endereços e chaves ficaram fora deste texto.

## Distribuição

<pre class="mermaid">
flowchart TB
  H["hospedeiro: 2 GPUs de 16 GB"]
  H --> G0["GPU 0: fallback Qwen3-14B, sempre carregado"]
  H --> G1["GPU 1: completação Qwen2.5-Coder-3B (porta 8083)"]
  H --> G1b["GPU 1: embeddings Qwen3-Embedding-0.6B (porta 8084)"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

Os dois servidores da GPU 1 exigem chave de API. Os modelos grandes ficaram na placa de 24 GB, em outra máquina.

## O que não coube

O modelo de 27B em Q6 ocupava 30 GB no disco. O modelo de 35B em Q4_K_M tem 21,2 GB, valor que a própria API do servidor informa. Por isso o hospedeiro ficou com modelos de até 14B, e o raciocínio pesado fica na placa de 24 GB.

Removi o arquivo de 27B depois de confirmar que nenhum script ou configuração ainda o referenciava.

## O problema da GPU ocupada

O modo de repouso do llama.cpp libera a VRAM quando o modelo fica ocioso. Na prática, o processo filho continuou com a GPU em 100% de uso, e a placa esquentava sem trabalho útil. Testar `--poll 0` também não reduziu esse uso.

Um timer, a cada 2 minutos, pede ao roteador que descarregue os modelos em repouso. Isso resolveu o caso observado na GPU 0 (o fallback). A GPU 0, na amostragem de hoje, ficou em 2%.

A GPU 1 é outra história. Ela hospeda dois servidores separados, de embedding e de completação, que não passam pelo roteador. O timer não os enxerga. Na amostragem de hoje a GPU 1 ficou em 100% durante os 5 minutos, com 4,7 GB de VRAM em uso, e os logs dos dois servidores não mostram requisições nos últimos 10 minutos. Não investiguei a causa dentro do llama.cpp, nem confirmei se o uso vem dos dois servidores ou de um deles.

<figure class="fig">
<img src="{{ "/assets/img/multimodelo-duas-gpus/gpu-pt.svg" | relative_url }}" alt="Dois painéis. À esquerda, uso das duas GPUs em 5 minutos: a GPU 1 em 100% o tempo todo e a GPU 0 em 2%. À direita, memória em uso: 10,4 GB na GPU 0 e 4,7 GB na GPU 1." loading="lazy">
<figcaption>Amostragem de 60 leituras, a cada 5 segundos, durante 5 minutos, sem pedidos registrados nos logs dos servidores da GPU 1. Uma única janela de tempo; não é uma série longa.</figcaption>
</figure>

## Custo do fallback sempre carregado

Manter o modelo de 14B carregado foi uma escolha. O relatório da sessão estima cerca de 40 W contínuos, sem medição própria, em troca de evitar cerca de 19 s de carregamento na primeira resposta do fallback.

## O que deu errado

| Sintoma | Causa | Correção |
|---|---|---|
| Modelo de 27B não cabe | 30 GB numa placa de 16 GB | removido e substituído por modelo de até 14B |
| GPU 0 ocupada em repouso | processo filho do modo de repouso | timer que descarrega os modelos do roteador (resolvido na GPU 0) |
| GPU 1 em 100% sem pedidos | servidores de embedding e completação fora do roteador, portanto fora do timer | não resolvido; causa não investigada |
| `--poll 0` sem efeito | não era a causa | descartado |

## Limites

- Uma única configuração de hardware.
- A amostragem de GPU cobre 5 minutos, em um único momento.
- A causa do uso de 100% na GPU 1 segue em aberto.
- Consumo e temperatura não foram medidos.
- Não testei o reinício completo do hospedeiro com todos os serviços.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
