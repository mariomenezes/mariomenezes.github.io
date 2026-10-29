---
title: "Calibrando sinais de roteamento com poucos exemplos"
lang: pt-BR
permalink: /pt/2026/10/29/calibrar-sinais-roteamento/
description: "O que dá errado ao calibrar um roteador semântico com 22 prompts e como interpretar scores de embedding quando o modelo muda."
---

*[Read in English]({{ "/en/2026/10/29/calibrar-sinais-roteamento/" | relative_url }})*

---

## O problema

Ao calibrar um roteador semântico, eu precisava de um conjunto de prompts de referência que cobrisse os dominios que o roteador encontraria no dia a dia. Coletei 22 prompts em 5 dominios (Terraform, Kubernetes, Ansible, shell, segurança) e gerei embeddings com Qwen3-Embedding-0.6B para ver como eles se agrupam.

O resultado: **sinais que parecem fortes no embedding falham na prática**, e scores dependem do lote.

## O experimento

1. Peguei 22 prompts de cenários reais (piloto do benchmark DevOps).
2. Gerei embeddings com o endpoint da porta 8084 (Qwen3-Embedding-0.6B, 1024 dim, cosseno).
3. Calculei a distância de cada prompt a centroides por dominio.
4. Comparei com a escolha real do roteador (todos para XTX neste teste).

## O que deu errado

### 1. Falsos positivos de proximidade

```
Dominio real → maior distância ao centroide do proprio dominio
---------------------------------------------------------------
Terraform   → 0.702 (prompt p02-tf-sg)
K8s         → 0.956 (prompt p10-rca-mesh)
Shell       → 0.999 (prompt NOVO-hard-3)
Segurança   → 0.994 (prompt legit-ignore)
```

O prompt `p02-tf-sg` (Terraform security group) tem distância 0.702 ao centroide de Terraform — o maior de todos. Ele mistura conceitos de rede (CIDR, ingress, egress) que o embedding puxa para o dominio de Kubernetes. O roteador confiando apenas no embedding poderia mandar para o modelo de código.

### 2. Scores dependentes do lote

```
Prompt        Embed-1   Embed-2   Diferença
----------------------------------------
NOVO-hard-1   0.579     0.536     0.043
NOVO-hard-2   0.561     0.532     0.029
legit-seg     0.369     0.560     0.191
```

O prompt `legit-seg` (segurança legítima) saltou de 0.369 para 0.560 entre execuções. A mesma pergunta, embedding diferente. Isso significa que **não se pode usar threshold fixo** — o embedding muda com o lote.

### 3. Sinais fracos que funcionam

```
Prompt        Distância   Dominio real
--------------------------------------
p03-ansible   0.001       Ansible ✓
p07-shell-du  0.004       Shell ✓
p01-tf-s3     0.029       Terraform ✓
```

Prompts com palavras-chave explicitas (`` `ansible-lint` ``, `/var`, `terraform`) têm distância quase zero ao centroide. O embedding funciona quando o prompt é **autoreferencial** — fala sobre a própria ferramenta.

## Conclusão

Com 22 exemplos e um embedding de 1024 dim, a calibração do roteador mostra limites claros:

- **Thresholds fixos não funcionam** porque o embedding varia por lote.
- **Dominios misturados** (Terraform + rede) geram falsos positivos.
- **Sinais fortes existem** para prompts autoreferenciais, mas não generalizam.

A solução prática: usar o embedding como um **sinal entre outros**, nunca como decisão única. Adicionar regras de palavra-chave para dominios críticos, e monitorar a distribuição de distances ao vivo.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
