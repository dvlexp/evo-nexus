---
name: prod-good-morning
description: "Morning orientation that recaps recent work, checks agenda, emails, meetings and tasks, then helps decide what to work on. Trigger when user says 'good morning', 'morning', 'start my day', 'what do I have today', or anything that signals beginning of a work session. Use it proactively — if a user opens with a greeting at the start of a session, run this skill before doing anything else."
---

# Good Morning

This skill orients a new session by reading recent logs, recapping what happened, and helping the user decide what to work on.

## Step 1 — Read the workspace

Read these files before saying anything:

1. **CLAUDE.md** — the master context file. This tells you who the user is, what projects are active, and what skills are available.
2. **Last 3 session logs** — find them in `workspace/daily-logs/`, sorted by date, most recent first. These are Claude's previous session notes.
3. **All active project overviews** — for each project listed in CLAUDE.md, read its overview file. These contain the goal, why, and open problems for each project.

If any of these files don't exist yet (the user might be very new), that's fine — just work with what's there.

## Step 2 — Check agenda, emails, tasks and signals

Before building the recap, gather live data silently (don't narrate each step):

1. **Agenda do dia** — use `/gog-calendar` to list today's events. Note meetings, times, people, and free blocks.
2. **Ligações do dia** — dentro dos eventos e tarefas do dia, identifique explicitamente as **ligações** (chamadas telefônicas reais, não reuniões com link). Procure por eventos/tarefas com palavras-chave como "ligar", "call", "telefonar", "contato telefônico", ou números de telefone. Separe das reuniões normais.
3. **Emails importantes** — use o Gmail MCP diretamente (`search_threads` depois `get_thread` para os relevantes) para verificar emails **não lidos** que precisam de ação. Do NOT invoke `/gog-email-triage` as a sub-skill — it sends its own Telegram notification and would cause a duplicate.
   - **Ignore completamente** (não liste, não crie rascunho): emails de vendedores/prospecção, cobranças automatizadas, spam, emails operacionais de sistema (Gemini, Google Workspace, invites de calendário, notificações de plataforma, newsletters, alertas automáticos de qualquer serviço).
   - **Foque apenas** em emails de pessoas reais que estão aguardando uma resposta de Daniel.
4. **Rascunhos de resposta** — para cada email real identificado no passo anterior, crie **um rascunho por email** no Gmail via `create_draft`. O rascunho deve ser bem elaborado, em pt-BR, com linguagem profissional e fluida — **sem usar listas com traço ("-")**, escreva em parágrafos corridos ou bullet points com "•" se necessário. Não envie — apenas crie o rascunho para Daniel revisar e ajustar antes de enviar. Após criar o rascunho, aplique a label **"revisado-aurora"** à thread correspondente via `label_thread`. Se a label não existir, crie-a via `create_label` com cor azul (`#4986e7`). Isso indica que a Aurora já gerou um rascunho para aquele email.
5. **Tarefas de hoje** — run `todoist today` to list today's and overdue tasks from Todoist.
6. **YouTube** — verifique o canal no YouTube: número atual de inscritos e **todos os comentários pendentes de resposta** (sem limite de data — todos que ainda não foram respondidos por Daniel). Use a skill `/int-youtube` ou a API do YouTube disponível no workspace.
7. **Emails financeiros** — verifique tickets com `assignee_agent = "flux-finance"` e `status = "review"` via `GET /api/tickets?assignee_agent=flux-finance&status=review`. Estes são movimentações financeiras detectadas pelo monitor de emails (Nubank/Asaas) que aguardam sua aprovação para lançamento nos registros.

## Step 3 — Brief recap

Give the user a short morning briefing in **pt-BR**. Keep it tight — this is an orientation, not a report:

- What was worked on recently (2–4 bullets from the session logs)
- Anything left open or mid-flight
- Today's agenda (meetings, times, people)
- **Ligações do dia** — lista separada das ligações telefônicas que precisam ser feitas (se houver)
- Emails que precisam de resposta + quantos rascunhos foram criados no Gmail
- YouTube: inscritos atuais + total de comentários pendentes de resposta (liste os primeiros 5 com autor e texto resumido)
- **💰 Financeiro** — se houver tickets de movimentação financeira pendentes de aprovação (flux-finance, status review), liste-os com: valor, tipo (extrato/cobrança), origem (Nubank/Asaas), classificação PJ ou PF, e os botões Aprovar/Recusar no HTML
- Today's priority tasks from Todoist

Then immediately give your **recommendation** — one clear sentence on what seems most important to work on based on recency, open problems, agenda, and project momentum. Make a real call; don't hedge.

If there are no previous logs (brand new user), skip the recap and go straight to Step 4.

## Step 4 — Ask what they want to do

After the recap, ask:

> "Want to jump into a project, or start something new?"

### If they pick a project:

Show each active project with its open problems as options. Pull from the "Open Problems" section of each project overview. Keep it scannable — one line per problem.

Ask them to pick a project and problem. Once they choose, read whatever additional context is needed and get to work.

### If they want something new:

Tell them to say "new project" and the new-project skill will walk them through it.

## Step 5 — Save briefing (OBRIGATÓRIO — sempre executar, mesmo sem MCPs)

**Este step é obrigatório e deve ser o último a rodar, independente de qualquer falha anterior.** Mesmo que Gmail, Calendar ou YouTube não estejam disponíveis, o HTML DEVE ser salvo com os dados que foram coletados.

1. Read the template at `.claude/templates/html/morning-briefing.html`
2. Fill all `{{PLACEHOLDER}}` values with whatever data was gathered in Steps 2–3. For sections where MCPs were unavailable, use: `⚠️ N/D` for values and `muted` for status classes.
3. Save the completed HTML to `workspace/daily-logs/[C] YYYY-MM-DD-morning.html` (use today's actual date).

Create the `workspace/daily-logs/` directory if it does not exist.

**Never skip this step.** The HTML file is the persistent artifact that the user accesses later — the text output in the terminal is secondary.

## Tone

Keep the morning briefing conversational and brief. The user is starting their day — they don't need a wall of text. Punchy bullets, one clear recommendation, then move into action.
