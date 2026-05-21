---
name: int-aws
description: "Interact with AWS services — SNS (SMS), SES (email), S3, CloudWatch. Use when you need to send SMS, manage buckets, check costs, or query AWS resources. Calls AWS API directly via CLI or boto3."
metadata:
  openclaw:
    requires:
      env:
        - AWS_ACCESS_KEY_ID
        - AWS_SECRET_ACCESS_KEY
      bins:
        - aws
        - python3
    primaryEnv: AWS_ACCESS_KEY_ID
    files:
      - "scripts/*"
---

# AWS Integration

Interact with AWS services: SNS, SES, S3, CloudWatch e mais.

## Setup (já configurado)

Credenciais configuradas em `.env` (gitignored). IAM user: `evonexus`.

```env
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>
AWS_REGION=us-east-1
```

Permissões: SNSFullAccess + SESFullAccess.

---

## SNS — Envio de SMS

### Enviar SMS avulso
```bash
python3 .claude/skills/int-aws/scripts/sns_sms.py send --phone "+5511999999999" --message "Sua mensagem aqui"
```

### Listar números verificados (sandbox)
```bash
python3 .claude/skills/int-aws/scripts/sns_sms.py list-verified
```

### Verificar número no sandbox
```bash
python3 .claude/skills/int-aws/scripts/sns_sms.py verify --phone "+5511999999999" --code 123456
```

### Status da conta SNS (limite, tipo, sandbox)
```bash
python3 .claude/skills/int-aws/scripts/sns_sms.py status
```

### Envio em massa (arquivo CSV: phone,message)
```bash
python3 .claude/skills/int-aws/scripts/sns_sms.py bulk --file /caminho/para/lista.csv
```

---

## SNS — Sandbox vs Produção

**Situação atual: SANDBOX**
- Só envia para números verificados
- Limite de gasto: $1/mês

**Para sair do sandbox (produção):**
1. Acesse: console.aws.amazon.com → SNS → Text messaging (SMS) → Get out of SMS sandbox
2. Preencha o formulário justificando o uso (use case: transactional)
3. Aprovação em 24-48h

Após aprovação, aumentar o limite:
```bash
# Via Service Quotas (requer permissão service-quotas:*)
aws service-quotas request-service-quota-increase \
  --service-code sns --quota-code L-D6DB7028 --desired-value 50
```

---

## SES — Email Transacional

### Enviar email
```bash
python3 .claude/skills/int-aws/scripts/ses_email.py send \
  --to destinatario@email.com \
  --subject "Assunto" \
  --body "Corpo do email"
```

### Status da conta SES
```bash
python3 .claude/skills/int-aws/scripts/ses_email.py status
```

---

## Custos estimados

| Serviço | Preço | 3000 unidades |
|---------|-------|----------------|
| SNS SMS (BR) | $0,00645/SMS | ~$19 (~R$110) |
| SES Email | $0,0001/email | ~$0,30 |
| S3 (storage) | $0,023/GB/mês | variável |
