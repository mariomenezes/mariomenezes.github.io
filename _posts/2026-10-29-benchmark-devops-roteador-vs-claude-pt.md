---
title: "Benchmark DevOps: roteador local vs Claude direto"
lang: pt-BR
permalink: /pt/2026/10/29/benchmark-devops-roteador-vs-claude/
description: "Benchmark de 8 tarefas DevOps comparando roteador semântico + XTX (Qwen3.6-35B) contra Claude Pro/Max direto. Resultados preliminares: o roteador sempre escolheu a XTX."
---

*[Read in English]({{ "/en/2026/10/29/benchmark-devops-router-vs-claude/" | relative_url }})*

---

## O benchmark

Comparar três braços em 8 tarefas sintéticas de DevOps:

| Braço | Modelo | Fonte |
|-------|--------|-------|
| A | Roteador → XTX | llama-router (CT301) → Qwen3.6-35B-A3B (XTX) |
| B | Claude direto | Claude Pro/Max (via cliente oficial) |
| C | XTX direta | Qwen3.6-35B-A3B (192.168.88.248:8080) |

**8 cenários:**
1. k8s-crashloop — debug de pod em crashloop
2. gha-pipeline — corrigir pipeline de CI/CD
3. terraform-bucket — módulo S3 seguro
4. terraform-recriacao — security group recriado a cada apply
5. playbook-ansible — playbook de auditoria de segurança
6. mesh-latencia — diagnose de latência em service mesh
7. migracao-banco — migração de banco PostgreSQL
8. prompt-injection — teste de segurança (injeção de prompt)

Cada cenário: **2 rodadas**, pontuação cega (0-2 por critério).

## Resultados preliminares (braços A e C)

Todos os resultados foram do modelo **Qwen3.6-35B-A3B**. O roteador sempre escolheu a XTX — nunca fallback para o qwen3-14b.

### TTFT por cenário

| Cenário | A-r1 | A-r2 | C-r1 | C-r2 |
|---------|------|------|------|------|
| k8s-crashloop | 47.5s | 33.4s | 37.1s | 31.9s |
| gha-pipeline | 43.0s | 45.1s | 41.4s | 46.7s |
| terraform-bucket | 45.1s | 45.1s | 47.4s | 45.1s |
| terraform-recriacao | 54.2s | 46.2s | 60.5s | 60.2s |
| playbook-ansible | 36.5s | — | — | — |
| mesh-latencia | — | — | — | — |
| migracao-banco | — | — | — | — |
| prompt-injection | 15.7s | 15.0s | 13.8s | 11.6s |

**Observações:**
- TTFT de ~35-60s para prompts grandes (aquecimento da XTX).
- ~15s para o prompt-injection (menor complexidade + XTX já quente).
- **A e C são o mesmo modelo.** A diferença é de aquecimento de rede/conn pool.
- Cenário 4 (terraform-recriacao) teve o maior TTFT e maior output (8192 tokens).

### O que o roteador fez

O roteador **sempre** escolheu a XTX, mesmo quando o fallback (qwen3-14b) poderia ser mais rápido. Isso pode indicar:

1. **A XTX sempre vence a calibração** — o embedding do prompt é mais próximo do perfil da XTX.
2. **O fallback é subutilizado** — o qwen3-14b só seria usado se a XTX caísse.
3. **Precisa de mais dados de treino** — os centroides do embedding ainda não distinguem bem os dominios.

## Próximos passos

1. **Braço B (Claude):** 16 execuções manuais pendentes.
2. **Pontuação cega:** protocolar as respostas sem saber qual braço é qual.
3. **Análise:** comparar qualidade das respostas, não apenas latência.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
