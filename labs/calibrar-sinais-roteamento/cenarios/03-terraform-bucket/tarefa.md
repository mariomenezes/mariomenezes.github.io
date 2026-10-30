# Cenário 3: Módulo Terraform - Bucket S3 privado

## Instrução para o modelo

Você é um engenheiro de infraestrutura escrevendo um módulo Terraform reutilizável. Crie um módulo que:

1. Crie um bucket S3 privado com versionamento habilitado
2. Configure SSE-KMS com chave gerenciada pelo cliente (CMK)
3. Bloqueie todo acesso público
4. Adicione política que nega transporte sem TLS
5. Pinate todas as provider e provider-dependent versions
6. Não inclua nenhum segredo hardcoded

**Regras:**
- Use variáveis para tudo que é externo.
- Inclua `main.tf`, `variables.tf`, `outputs.tf` e um `examples/main.tf`.
- Inclua validação de entrada nas variáveis.

## Ferramenta de verificação objetiva

Após a resposta, execute mentalmente:
- `terraform validate`: o módulo deve validar sem erros.
- Verificar se há strings que parecem segredos (ex.: padrões de chave, token, credencial).
- Verificar se todas as resources têm versão pinned no provider.
