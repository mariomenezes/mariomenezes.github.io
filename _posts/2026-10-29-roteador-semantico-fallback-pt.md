---
title: "Roteador de modelos com fallback no homelab: o que configurei e o que testei"
lang: pt-BR
permalink: /pt/2026/10/29/roteador-semantico-fallback/
description: "Notas de laboratório: um roteador de modelos na frente de duas fontes de inferência, com ordem de prioridade, fallback local e o teste de queda da fonte principal. Inclui o que ainda não foi testado."
resumo: "Um roteador na frente de duas fontes de inferência, com prioridade e fallback local. A fonte principal caiu de verdade: 10 de 10 pedidos foram para o fallback."
image: /assets/img/roteador-fallback/cover-pt.png
---

*[Read in English]({{ "/en/2026/10/29/roteador-semantico-fallback/" | relative_url }})*

<p class="status"><span class="pill">Laboratório</span> <span>29 de outubro de 2026 · <a href="#limites">limites</a></span></p>

Eu tinha duas fontes de inferência: um modelo de 35B numa placa AMD de 24 GB, e um modelo de 14B numa placa de 16 GB no mesmo hospedeiro de serviços. Queria que o cliente (o OpenCode) falasse com um endereço só, que o pedido fosse para o modelo grande quando ele estivesse disponível, e que o modelo de 14B atendesse quando ele caísse.

Este post descreve a configuração, o teste de queda que fiz e o que ainda não foi medido. Não há um benchmark de qualidade aqui; é um relato de montagem e de um teste de disponibilidade.

## Resumo

- **Um endereço para o cliente.** O roteador expõe uma API compatível com OpenAI e escolhe a rota pelo tipo de pedido.
- **Ordem de prioridade fixa.** A rota padrão é o modelo grande; se ele falhar, vai para o de 14B.
- **Queda real medida:** com a fonte principal fora do ar, 10 de 10 pedidos foram para o fallback (0,15 s de mediana). Quando ela voltou, 10 de 10 foram para a principal (0,11 s).
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

A configuração tem rotas com prioridade. Uma delas bloqueia pedidos com padrões de ataque direto ao assistente, outra manda para modelos locais pedidos com dados sensíveis, outra envia pedidos de investigação ao modelo grande com raciocínio, e a última é a rota padrão, o modelo principal com o de 14B como alternativa.

Um limite importante: a detecção de injeção indireta, vinda de texto que o assistente lê, não existe nesta configuração. Só cobre o caso direto.

## Queda real da fonte principal

Num dia de medições, a fonte principal saiu do ar sem eu ter feito nada. O roteador passou a responder pelo fallback. Medi 10 pedidos curtos (16 tokens no máximo, temperatura 0) enquanto ela estava fora, e 10 depois que voltou. Não investiguei a causa da queda.

| Estado | Rota (cabeçalho) | Modelo que respondeu | Mediana | Mín–máx |
|---|---|---|---|---|
| Fonte principal fora | `fallback` | qwen3-14b | 0,15 s | 0,12–0,15 s |
| Fonte principal no ar | `upstream` | Qwen3.6-35B-A3B | 0,11 s | 0,10–0,13 s |

Pedidos curtos com 2 tokens de saída medem sobretudo o tempo de resposta do roteador, não a geração. Não repeti com pedidos longos.

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/painel-roteador.png" | relative_url }}" alt="Painel do roteador com 2 modelos, 4 decisões, 4 sinais, 3 de 3 serviços saudáveis e status pronto." loading="lazy">
<figcaption>Painel do roteador no momento das medições: dois modelos registrados, quatro decisões, três de três serviços saudáveis.</figcaption>
</figure>

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/topologia-roteador.png" | relative_url }}" alt="Mapa de roteamento: a consulta do usuário passa por sinais de palavra-chave e de decisão, depois por cinco decisões, e chega aos modelos qwen3-14b e qwen3.6-35b, com a rota padrão para o modelo grande." loading="lazy">
<figcaption>Topologia do roteamento na configuração ativa. Da esquerda para a direita: sinais, decisões (bloqueio de injeção, dados sensíveis, raciocínio profundo e rota padrão) e modelos.</figcaption>
</figure>

<figure class="fig">
<img src="{{ "/assets/img/roteador-fallback/monitoramento-roteador.png" | relative_url }}" alt="Página de monitoramento do roteador com o painel do Grafana: 33 requisições de inferência concluídas, 87,9% de taxa de sucesso, nenhuma em andamento, e gráficos de resultado e de latência por hora." loading="lazy">
<figcaption>Monitoramento embutido no painel do roteador, no momento da captura: 33 requisições concluídas, 87,9% de sucesso, nenhuma em andamento. Mostra métricas de operação, não a qualidade das respostas.</figcaption>
</figure>

## Decisão: fallback sempre carregado ou sob demanda

| Opção | Custo | Efeito |
|---|---|---|
| Sempre carregado | consumo contínuo estimado no relatório da sessão, sem medição própria | o primeiro pedido do fallback responde sem a espera do carregamento |
| Sob demanda | ociosidade com a memória livre | cerca de 19 s extras na primeira resposta do fallback |

A decisão registrada no vault é manter o fallback carregado. A configuração ainda diz o contrário, então a descrição precisa ser corrigida.

## Limites

- Pedidos curtos apenas; não medi latência com pedidos longos nem qualidade das respostas.
- Os 19 s de carregamento do fallback vêm do relatório da sessão, de um teste anterior que não repeti.
- O consumo contínuo do fallback não foi medido aqui.
- Injeção indireta não é detectada pelo roteador.
- Não testei a volta automática depois de um reinício completo do hospedeiro.

## O que vem a seguir

- Repetir o teste de queda cinco vezes e medir a latência em cada uma.
- Corrigir a descrição do fallback na configuração.
- Medir a qualidade das respostas no benchmark, com o protocolo cego.

---

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
