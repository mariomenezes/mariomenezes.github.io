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
- **Um timer resolveu:** a cada 2 minutos, ele descarrega via API os modelos em repouso. A GPU voltou a 0% de uso ocioso.

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

A solução que funcionou foi um timer que, a cada 2 minutos, pede ao servidor para descarregar os modelos que estão em repouso. Depois disso a GPU voltou a 0% de uso ocioso.

Esse é um efeito observado, não medido com instrumentação. Não investiguei a causa dentro do llama.cpp.

## Custo do fallback sempre carregado

Manter o modelo de 14B carregado foi uma escolha. O relatório da sessão estima cerca de 40 W contínuos, sem medição própria, em troca de evitar cerca de 19 s de carregamento na primeira resposta do fallback.

## O que deu errado

| Sintoma | Causa | Correção |
|---|---|---|
| Modelo de 27B não cabe | 30 GB numa placa de 16 GB | removido e substituído por modelo de até 14B |
| GPU em 100% sem trabalho | processo filho do modo de repouso | timer que descarrega os modelos em repouso |
| `--poll 0` sem efeito | não era a causa | descartado |

## Limites

- Uma única configuração de hardware.
- Consumo e temperatura não foram medidos.
- Não testei o reinício completo do hospedeiro com todos os serviços.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
