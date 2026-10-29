---
title: "LLMs as DevOps assistant in the homelab"
lang: en
permalink: /en/2026/10/29/llm-devops-homelab/
description: "3 months of lessons using LLMs for Terraform, Kubernetes, Ansible, GHA and service mesh: when it works, when it fails, and what works best."
---

*[Leia em português]({{ "/pt/2026/10/29/llm-assistente-devops-homelab/" | relative_url }})*

---

## The context

Over the past 3 months, I've used LLMs daily for DevOps tasks in the homelab. Here are the lessons learned.

## What worked

### 1. IaC code generation

Terraform and Ansible are the domains where LLMs excel most. The syntax is well documented, patterns are repetitive, and the model generates useful code on the first try.

- **Terraform modules:** generates S3 buckets, security groups, VPCs with security on the first attempt.
- **Ansible playbooks:** security audit, host configuration, everything without interaction.

### 2. Kubernetes debug

LLMs help interpret pod logs and suggest manifests. But real debugging requires cluster access — the model can't `kubectl exec`.

### 3. GitHub Actions

The LLM knows GHA patterns. Generates build/test/deploy workflows with correct environment variables and secrets configuration.

## What didn't work as well

### 1. Service mesh debug

Istio/Linkerd involve CRD configuration, mTLS policies, tracing — the model knows the theory but can't see the mesh's actual state. Partial results.

### 2. Database migration

The LLM generates SQL and migration strategies, but validation requires database access. Without a connection, it's just theory.

### 3. Prompt injection

Scenario 8 of the benchmark showed the model can identify suspicious instructions in documents — but real detection requires security context the model doesn't have by default.

## The main lesson

**LLMs are assistants, not autonomous.** They generate code and suggest diagnostics, but validation always requires:

1. System access (cluster, database, infrastructure).
2. Security context (what's legitimate vs injection).
3. Testing in staging before production.

## Tools used

- **Qwen3.6-35B-A3B** (XTX): heavy model for complex reasoning.
- **Qwen3-14B** (fallback): fast for simple tasks.
- **Claude Pro/Max**: for tasks requiring deep reasoning.
- **llama-router**: to decide which model to use.
- **OpenCode**: work interface with RAG and MCP tools.

**Mario Menezes** — infrastructure, Kubernetes and service mesh. Comments, questions or corrections: [LinkedIn](https://www.linkedin.com/in/mario-a-menezes-costa/).
