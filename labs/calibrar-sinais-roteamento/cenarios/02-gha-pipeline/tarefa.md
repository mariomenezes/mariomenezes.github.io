# Cenário 2: Pipeline no GitHub Actions

## Instrução para o modelo

Você é um engenheiro de DevOps. A equipe recebeu este workflow do GitHub Actions e precisa corrigir problemas de segurança e performance. Analise o artefato abaixo e indique o que está errado.

**Regras:**
- Cite cada problema com linha/segmento e explicação.
- Apresente uma versão corrigida.
- Indique ferramentas que validam as correções.

## Artefato 1: workflow.yml original

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: myorg/myapp

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout
      - name: Setup Node
        uses: actions/setup-node@v3
        with:
          node-version: '20'
      - name: Install deps
        run: npm ci
      - name: Build
        run: npm run build
      - name: Test
        run: npm test

  deploy:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - uses: actions/checkout
      - name: Login to registry
        run: echo ${{ secrets.REGISTRY_TOKEN }} | docker login ${{ env.REGISTRY }} -u ${{ github.actor }} --password-stdin
      - name: Build and push
        run: |
          docker build -t ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }} .
          docker push ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }}
      - name: Deploy
        run: |
          echo "DEPLOY_KEY=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" >> $GITHUB_ENV
          kubectl set image deployment/api api=${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ github.sha }} --namespace=prod
```
