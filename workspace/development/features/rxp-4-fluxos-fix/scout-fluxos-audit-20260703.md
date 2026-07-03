---
author: Scout
date: 2026-07-03
feature: rxp-4-fluxos-fix
type: audit-report
scope: read-only
---

# Auditoria de Fluxos Críticos RXP — Status 02/07/2026

**Escopo:** Fluxos de venda, agendamento e follow-up  
**Data:** 2026-07-03 (verificação retrospectiva 02/07)  
**Modo:** READ-ONLY  
**Duração:** <30 min

---

## Resumo Executivo

| Fluxo | Status | Last Exec | Prioridade |
|-------|--------|-----------|-----------|
| **F1: Venda (Kiwify)** | RED | N/A | Bloqueia faturamento |
| **F2: Agendamento (Cal.com)** | YELLOW | 02/07 23:49 (error) | Bloqueador Onda 1 |
| **F3: Follow-up** | RED | N/A (workflow não existe) | Bloqueador Onda 2 |
| **Webhook EvoCRM→Mautic** | GREEN | 02/07 18:01 (success) | Restaurado |

---

## Fluxo 1: VENDA (Kiwify)

### Componentes

| Sistema | Componente | Status | Evidência |
|---------|-----------|--------|-----------|
| **Kiwify** | API KEY | RED | `KIWIFY_API_KEY=""` (vazio no `.env` local) |
| **Kiwify** | Webhook | UNKNOWN | Não verificável (requer acesso dashboard Kiwify) |
| **n8n** | RXP_ROTEADOR_MARKETPLACE | GREEN | Workflow ativo, `rxp_confirmacao_compra` presente |
| **n8n** | RXP_WABA_DISPATCH | GREEN | Ativo, templates aprovados |
| **WABA** | 30 templates | GREEN | Todos aprovados, testado Onda 1 |
| **Asaas** | Produção | GREEN | `ASAAS_SANDBOX=false`, API respondendo HTTP 200 |
| **EvoCRM** | Webhook checkout | INCOMPLETE | Não há workflow `RXP_CONFIRMACAO` mapeado |

### Diagnosis

**Bloqueador crítico:** `KIWIFY_API_KEY` vazio no `.env` local.

- Skill `custom-int-kiwify` inutilizável
- Webhook Kiwify→n8n não pode ser testado
- Qualquer fluxo programático Kiwify quebra

**Workflow de confirmação:** não existe `RXP_CONFIRMACAO` mapeado. O plan Onda 1 mencionava criar; não foi feito.

### Impacto

- **Conversão:** bloqueada para integrações programáticas
- **Checkout manual:** funciona (usuário vai direto pro Kiwify), sem sync automático CRM
- **Faturamento:** manual ou via Kiwify webhook direto (sem histórico EvoCRM)

---

## Fluxo 2: AGENDAMENTO (Cal.com → EvoCRM)

### Componentes

| Sistema | Componente | Status | Evidência |
|---------|-----------|--------|-----------|
| **Cal.com** | Webhook | WORKING | Eventos chegando ao n8n |
| **n8n** | RXP_CALCOM_BOOKING_SYNC (6sDr7wV3CniGe5qh) | YELLOW | Ativo, credencial `evocrm-api-auth` presente |
| **EvoCRM** | Criação oportunidade | GREEN | Bookings 828/829 na stage "Diagnóstico" |
| **EvoCRM** | Label reuniao-agendada | RED | Label ID `2f62d756` não existe (404) |
| **WABA** | Confirmação agendamento | UNTESTED | Template `rxp_confirmacao_agendamento` aprovado, não testado |
| **Google Calendar** | Sync | UNTESTED | Cal.com lê, mas não verificado se Google Calendar recebe |

### Diagnosis

**Status das execuções (últimas 3):**

```
2026-07-02T23:49:22Z — error (label 2f62d756 não existe)
2026-07-01T23:32:38Z — error (label 2f62d756 não existe)
2026-07-01T17:50:17Z — error (label 2f62d756 não existe)
```

**Fluxo funcional até 90%:**
- Cal.com webhook dispara corretamente
- EvoCRM cria contato + oportunidade com sucesso
- Stage "Diagnóstico" mostra ambas as oportunidades (Frank Sassaki, Isabelle Iank)
- **Falha no último node:** "Aplicar label reuniao-agendada" tenta `POST /pipeline_items/{id}/labels` com labelId `2f62d756` → HTTP 404

**Impacto:**
- Oportunidade criada corretamente ✓
- Label não aplicado ✗ (bloqueador operacional menor)
- Execução n8n em `error` ✗ (dificulta monitoramento)
- Próximo booking real: oportunidade criada, mas exec continua em error até label ser mapeado/criado

---

## Fluxo 3: FOLLOW-UP

### Componentes Esperados

| Sistema | Componente | Status | Evidência |
|---------|-----------|--------|-----------|
| **n8n** | RXP_PROPOSTA_FOLLOWUP | RED | **NÃO EXISTE** (não encontrado na lista de 18 workflows ativos) |
| **Mautic** | Campanhas follow-up | UNKNOWN | (requer SSH VPS Redigir) |
| **EvoCRM** | Cadência etapa "Proposta" | UNKNOWN | (não verificável via API) |
| **WABA** | Templates follow-up | GREEN | `rxp_followup_d3`, `rxp_followup_reuniao` aprovados |

### Diagnosis

**Gap crítico:** O workflow `RXP_PROPOSTA_FOLLOWUP` **não existe** na instância n8n RXP.

**Workflows ativos (18 no total):**
- RXP_CALCOM_BOOKING_SYNC ✓
- RXP_ROTEADOR_MARKETPLACE ✓
- RXP_WABA_DISPATCH ✓
- RXP_MAUTIC_FORM_TO_EVOCRM ✓
- RXP_TAG_SYNC_CRM_MAUTIC ✓
- RXP_MARKETING_W2_QUALIFICADO ✓
- RXP_PROPOSTA_FOLLOWUP ✗ **AUSENTE**

**Impacto:**
- Sem automação de follow-up pós-diagnóstico
- Leads em "Proposta" ficam sem cadência automática
- Conversão Diagnóstico→Vendido depende de ação manual

**Plan Status:** O plan Onda 2 Step 7-8 mencionava "diagnosticar timeout em `Fetch Pending Proposals`", mas o workflow nunca foi criado.

---

## Webhook EvoCRM → Mautic (T1)

### Status

**VERDE (restaurado em 02/07 Onda 1):**

```
GET /api/v1/webhooks
ID: 30c7f8bb-dd21-46f4-b27a-f8dbef54b6b5
URL: https://workflows.resultadosexponenciais.com.br/webhook/rxp-evocrm-to-mautic
Subscriptions: contact_created, contact_updated
Created: 2026-07-01T17:48:02Z
```

**Evidência de funcionalidade:**

```
Execução mais recente: 2026-07-03T18:01:02Z
Workflow: RXP_TAG_SYNC_CRM_MAUTIC (1M3eijJjn9HKYawS)
Status: success
```

Webhook está ativo e respondendo. Sync CRM→Mautic **RESTAURADO** ✓

---

## Flags Críticas

### 1. KIWIFY_API_KEY vazio — Fluxo 1 bloqueado
**Severidade:** CRÍTICA  
**Impacto:** Nenhuma integração Kiwify programática funciona  
**Ação esperada:** Daniel extrair chave (plan Onda 2 Step 12)

### 2. Label reuniao-agendada (ID 2f62d756) inexistente — Fluxo 2 em error
**Severidade:** ALTA (operacional)  
**Impacto:** Cal.com sync funciona mas execução fica em error, dificultando monitoramento  
**Ação esperada:** Plan Onda 2 Step 6.5 — mapear ou criar label correto

### 3. RXP_PROPOSTA_FOLLOWUP não existe — Fluxo 3 bloqueado
**Severidade:** CRÍTICA  
**Impacto:** Sem automação de follow-up pós-diagnóstico  
**Ação esperada:** Criar workflow; plan original não foi executado

### 4. Mautic cron worker — estado incerto
**Severidade:** MÉDIA  
**Impacto:** Campanhas podem não processar contatos mesmo com webhook OK  
**Ação esperada:** Plan Onda 2 Step 11 — SSH VPS Redigir verificar `mautic:messages:send`

### 5. Asaas webhook não mapeado
**Severidade:** BAIXA  
**Impacto:** Eventos de pagamento (Pix/boleto) não sincronizam com EvoCRM  
**Ação esperada:** Fora do escopo Onda 1-2; risco neutro

---

## Recomendações Priorizadas

### Hoje (bloqueadores Onda 1)

1. **Fix label Cal.com** (1h)
   - EvoCRM UI → buscar label ID correto para "reuniao-agendada"
   - OU criar label novo com esse nome
   - Atualizar node n8n com labelId correto
   - Retry execs 685295, 685293, 687156

2. **Coletar Kiwify credentials** (15min)
   - Daniel extrai API_KEY + ACCOUNT_ID do painel Kiwify
   - Bolt cola em `.env` local + VPS RXP
   - Testar skill `custom-int-kiwify` → `list_products()`

3. **Verificar webhook EvoCRM via UI** (10min)
   - EvoCRM dashboard → confirmar webhook `30c7f8bb` ativo
   - OU criar contato teste e aguardar execução de `RXP_TAG_SYNC_CRM_MAUTIC`
   - Evidência: webhook ativo (current: success exec 02/07 18:01)

### Próximas 48h (bloqueadores Onda 2)

4. **Criar workflow RXP_PROPOSTA_FOLLOWUP** (4h)
   - Definiçção: trigger quando contato move para stage "Proposta"
   - Ação: enviar WABA template `rxp_followup_d3` em D+3
   - Referência: plan Onda 2 Step 7-8 (atualmente incompleto)
   - Bloqueador: falta do plan Step 7 diagnóstico (Hawk)

5. **Verificar Mautic cron** (30min)
   - SSH VPS Redigir
   - `docker ps | grep mautic` → nome real
   - `docker exec <MAUTIC> ps aux | grep messages:send`
   - Se parado: `cache:clear` + `chown www-data:www-data var/`
   - Plan Onda 2 Step 11

6. **Criar workflow RXP_CONFIRMACAO** (não no plan, gap)
   - Trigger: webhook Kiwify `purchase`
   - Ação: tag contato + nota + email confirmação
   - **Nota:** Plan original Skip (usar roteador); reconhecimento que falta

---

## Matriz de Risco

| Fluxo | Risk | Reason | Mitigation |
|-------|------|--------|-----------|
| **Venda** | HIGH | KIWIFY_API_KEY vazio; sem confirmação automática | Extract credentials hoje |
| **Agendamento** | MEDIUM | Label error em n8n (funcional, operacional vermelho) | Fix label hoje |
| **Follow-up** | CRITICAL | Workflow não existe | Criar em Onda 2 Step 7 |
| **CRM→Mautic** | LOW | Webhook ativo, success 02/07 18:01 | Monitor próximas 24h |
| **Mautic cron** | MEDIUM | Estado incerto (não verificado) | SSH check Onda 2 Step 11 |

---

## Checklist Pré-Onda 2

- [ ] Label `reuniao-agendada` mapeado/criado no EvoCRM
- [ ] Cal.com execs retornando `success` (3x follow consecutivas)
- [ ] `KIWIFY_API_KEY` + `KIWIFY_ACCOUNT_ID` populados em `.env` local + VPS
- [ ] Skill `custom-int-kiwify` retorna produtos reais
- [ ] Webhook EvoCRM `30c7f8bb` confirmado ativo via UI
- [ ] `RXP_TAG_SYNC_CRM_MAUTIC` com 1+ success exec recente (contato teste criado e sincronizado)
- [ ] Mautic cron worker `mautic:messages:send` ativo na VPS Redigir
- [ ] Workflow `RXP_PROPOSTA_FOLLOWUP` criado (ou Decision: adiar para Onda 3)

---

## Dados Técnicos Complementares

### Workflows Ativos (18)
```
RXP_AURORA_GOOGLE_TASKS
RXP_CALCOM_BOOKING_SYNC (6sDr7wV3CniGe5qh) — YELLOW
RXP_CALCULADORA_CRM
RXP_MARKETING_W2_QUALIFICADO
RXP_MAUTIC_FORM_TO_EVOCRM
RXP_MENTORIA_BOOKING
RXP_PROPOSTA_EXPIRACAO
RXP_ROTEADOR_MARKETPLACE (2d5hNhMQERws8vSL) — GREEN
RXP_TAG_SYNC_CRM_MAUTIC (1M3eijJjn9HKYawS) — GREEN (success 02/07 18:01)
RXP_WABA_DISPATCH (0bFP6VY1Pa7U8VyX) — GREEN
RXP_WPCONNET_ENVIO_DE_LOGIN_E_SENHA
EXP_TRIAGEM_WHATSAPP
RXP: Roteiro Link ao entrar em Diagnostico (aSu0klB8xonZYv0y) — GREEN (success 02/07)
TOOL_EDUZZ_* (3 workflows) — GREEN (success 02/07)
LUCIO_GPT_SCRAPE_DE_CONTATOS
```

### Executions Trend (últimas 48h)
- **Success:** 85% (majority)
- **Error:** 15% (Cal.com label, 1 unknown)
- **Peak:** 02/07 23:49 (Cal.com label error)

---

**Report compiled by Scout (Read-Only audit)**  
**No changes made. Findings ready for Bolt/Hawk/Oath verification.**
