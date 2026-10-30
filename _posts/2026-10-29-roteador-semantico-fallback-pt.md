---
title: "Roteador de modelos com fallback no homelab: o que configurei e o que testei"
lang: pt-BR
permalink: /pt/2026/10/29/roteador-semantico-fallback/
description: "Notas de laboratório: um roteador de modelos na frente de duas fontes de inferência, com ordem de prioridade, fallback local e o teste de queda da fonte principal. Inclui o que ainda não foi testado."
---

*[Read in English]({{ "/en/2026/10/29/roteador-semantico-fallback/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>29 de outubro de 2026 · <a href="#limites">limites</a></span></p>

Eu tinha duas fontes de inferência: um modelo de 35B numa placa AMD de 24 GB, e um modelo de 14B numa placa de 16 GB no mesmo hospedeiro de serviços. Queria que o cliente (o OpenCode) falasse com um endereço só, que o pedido fosse para o modelo grande quando ele estivesse disponível, e que o modelo de 14B atendesse quando ele caísse.

Este post descreve a configuração, o teste de queda que fiz e o que ainda não foi medido. Não há um benchmark de qualidade aqui; é um relato de montagem e de um teste de disponibilidade.

## Resumo

- **Um endereço para o cliente.** O roteador expõe uma API compatível com OpenAI e escolhe a rota pelo tipo de pedido.
- **Ordem de prioridade fixa.** A rota padrão é o modelo grande; se ele falhar, vai para o de 14B.
- **Queda testada:** com o modelo grande derrubado, o pedido foi atendido pelo fallback em cerca de 19 s, incluindo o carregamento do modelo. Foi um teste único, sem repetição.
- **Divergência encontrada:** a descrição do fallback na configuração diz que o modelo carrega sob demanda; a decisão registrada no vault é mantê-lo sempre carregado. Uma das duas está desatualizada.

## Ambiente

| Item | Valor |
|---|---|
| Fonte principal | Qwen3.6-35B-A3B, quantização Q4_K_M, placa AMD RX 7900 XTX de 24 GB, Vulkan, máquina de trabalho separada |
| Fallback | Qwen3-14B, placa AMD RX 9060 XT de 16 GB, GPU 0 do hospedeiro |
| Roteador | vllm-sr em container, API na porta 8899, estratégia `priority` |
| Hospedeiro | Ryzen 5 5600G, 62 GB de RAM, Proxmox VE 8.4.19 |
| Cliente | OpenCode v2.2.1 |

Os endereços de rede ficaram fora deste texto.

## Como o roteador escolhe

<pre class="mermaid">
flowchart LR
  C["OpenCode"] --> R["roteador :8899"]
  R -->|"prioridade 1"| X["modelo principal (24 GB)"]
  R -->|"se falhar"| F["fallback 14B (16 GB)"]
</pre>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: "neutral" });
</script>

A configuração tem rotas com prioridade. Uma delas bloqueia pedidos com padrões de ataque direto ao assistente, outra manda para modelos locais pedidos com dados sensíveis, outra envia pedidos de investigação ao modelo grande com raciocínio, e a última é a rota padrão, o modelo principal com o de 14B como alternativa.

Um limite importante: a detecção de injeção indireta, vinda de texto que o assistente lê, não existe nesta configuração. Só cobre o caso direto.

## O teste de queda

Parei o proxy que liga o roteador ao modelo principal e fiz um pedido curto pelo roteador. O pedido foi atendido pelo fallback. O tempo total foi de cerca de 19 s, sendo a maior parte o carregamento do modelo de 14B. Depois o proxy foi religado.

O que isso não mostra: a latência em regime, a variação entre repetições e o comportamento com pedidos longos. Foi uma execução.

## Decisão: fallback sempre carregado ou sob demanda

| Opção | Custo | Efeito |
|---|---|---|
| Sempre carregado | consumo contínuo estimado no relatório da sessão, sem medição própria | o primeiro pedido do fallback responde sem a espera do carregamento |
| Sob demanda | ociosidade com a memória livre | cerca de 19 s extras na primeira resposta do fallback |

A decisão registrada no vault é manter o fallback carregado. A configuração ainda diz o contrário, então a descrição precisa ser corrigida.

## Limites

- Um teste de queda, com uma execução. Não há repetições nem medição de qualidade.
- O consumo contínuo do fallback não foi medido aqui.
- Injeção indireta não é detectada pelo roteador.
- Não testei a volta automática depois de um reinício completo do hospedeiro.

## O que vem a seguir

- Repetir o teste de queda cinco vezes e medir a latência em cada uma.
- Corrigir a descrição do fallback na configuração.
- Medir a qualidade das respostas no benchmark, com o protocolo cego.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
