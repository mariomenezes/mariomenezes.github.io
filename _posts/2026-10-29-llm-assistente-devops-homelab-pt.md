---
title: "LLM como assistente DevOps no homelab"
lang: pt-BR
permalink: /pt/2026/10/29/llm-assistente-devops-homelab/
description: "Lição de 3 meses usando LLMs para Terraform, Kubernetes, Ansible, GHA e service mesh: quando funciona, quando falha, e o que funciona melhor."
---

*[Read in English]({{ "/en/2026/10/29/llm-assistente-devops-homelab/" | relative_url }})*

---

## O contexto

Nos últimos 3 meses, usei LLMs diariamente para tarefas de DevOps no homelab. Aqui vão as lições aprendidas.

## O que funcionou

### 1. Geração de código IaC

Terraform e Ansible são os dominios onde o LLM mais brilha. A sintaxe é bem documentada, os padrões são repetitivos, e o modelo gera código útil na primeira tentativa.

- **Módulos Terraform:** gera buckets S3, security groups, VPCs com segurança na primeira tentativa.
- **Playbooks Ansible:** auditoria de segurança, configuração de hosts, tudo sem interação.

### 2. Debug de Kubernetes

O LLM ajuda a interpretar logs de pods e sugerir manifests. Mas o debug real exige acesso ao cluster — o modelo não pode `kubectl exec`.

### 3. GitHub Actions

O LLM conhece os padrões de GHA. Gera workflows de build/test/deploy com variáveis de ambiente e secrets configurados corretamente.

## O que não funcionou tão bem

### 1. Debug de service mesh

Istio/Linkerd envolvem configuração de CRDs, políticas mTLS, tracing — o modelo sabe a teoria, mas não vê o estado real da malha. Resultados parciais.

### 2. Migração de banco

O LLM gera SQL e estratégias de migração, mas a validação exige acesso ao banco. Sem conexão, é só teoria.

### 3. Prompt injection

O cenário 8 do benchmark mostrou que o modelo consegue identificar instruções suspeitas em documentos — mas a detecção real exige contexto de segurança que o modelo não tem por padrão.

## A lição principal

**LLMs são assistentes, não autônomos.** Eles geram código e sugerem diagnósticos, mas a validação sempre exige:

1. Acesso ao sistema (cluster, banco, infraestrutura).
2. Contexto de segurança (o que é legítimo vs o que é injeção).
3. Teste em ambiente de staging antes de production.

## Ferramentas que usei

- **Qwen3.6-35B-A3B** (XTX): modelo forte para raciocínio complexo.
- **Qwen3-14B** (fallback): rápido para tarefas simples.
- **Claude Pro/Max**: para tarefas que exigem raciocínio profundo.
- **llama-router**: para decidir qual modelo usar.
- **OpenCode**: interface de trabalho com RAG e ferramentas MCP.

**Mario Menezes** — infraestrutura, Kubernetes e service mesh. Comentários, dúvidas ou correções: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
