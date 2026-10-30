# Cenário 4: Plano Terraform com recriação indevida

## Instrução para o modelo

Você é um engenheiro de infraestrutura revisando um plano do Terraform. O plano mostra que um recurso será destruído e recriado sem motivo óbvio. Analise a causa raiz e sugira uma correção que **não perca o estado existente**.

**Regras:**
- Não sugira `terraform apply` sem antes explicar a causa.
- A correção deve preservar recursos existentes.
- Indique `terraform state` command se necessário para validar a hipótese.

## Artefato: saída de terraform plan

```
Terraform will perform the following actions:

  # aws_security_group.web must be replaced
-/+ resource "aws_security_group" "web" {
      ~ arn                    = "arn:aws:ec2:us-east-1:123456789012:security-group/sg-0abc1234def56789" -> (known after apply)
      ~ id                     = "sg-0abc1234def56789" -> (known after apply)
      name                   = "web-sg"
      description            = "Web server security group"
      vpc_id                 = "vpc-0abc1234def56789"
      ingress {
          from_port   = 443
          to_port     = 443
          protocol    = "tcp"
          cidr_blocks = ["10.0.0.0/8"]
      }
      ingress {
          from_port   = 80
          to_port     = 80
          protocol    = "tcp"
          cidr_blocks = ["10.0.0.0/8"]
      }
      egress {
          from_port   = 0
          to_port     = 0
          protocol    = "-1"
          cidr_blocks = ["0.0.0.0/0"]
      }
      # (8 unchanged attributes hidden)
  }

Plan: 1 to add, 0 to change, 1 to destroy.
```

## Artefato 2: código relevante

```hcl
resource "aws_security_group" "web" {
  name        = "web-sg"
  description = "Web server security group"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}
```

## Artefato 3: estado relevante (terraform state pull)

```json
{
  "resources": [
    {
      "mode": "managed",
      "type": "aws_security_group",
      "name": "web",
      "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
      "instances": [
        {
          "schema_version": 1,
          "attributes": {
            "id": "sg-0abc1234def56789",
            "arn": "arn:aws:ec2:us-east-1:123456789012:security-group/sg-0abc1234def56789",
            "name": "web-sg",
            "description": "Web server security group",
            "vpc_id": "vpc-0abc1234def56789",
            "ingress": [
              {
                "from_port": 443,
                "to_port": 443,
                "protocol": "tcp",
                "cidr_blocks": ["10.0.0.0/8"],
                "description": "HTTPS"
              },
              {
                "from_port": 80,
                "to_port": 80,
                "protocol": "tcp",
                "cidr_blocks": ["10.0.0.0/8"],
                "description": "HTTP"
              }
            ],
            "egress": [
              {
                "from_port": 0,
                "to_port": 0,
                "protocol": "-1",
                "cidr_blocks": ["0.0.0.0/0"]
              }
            ]
          }
        }
      ]
    }
  ]
}
```
