#!/usr/bin/env python3
"""ADW: VPS Health — Monitora todas as VPS gerenciadas e alerta via Telegram se algo anormal"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import run_claude, banner, summary

VPS_INVENTORY = """
| Nome              | IP              | vCPU | RAM   | Stack                              | Projetos hospedados                               | Credenciais env         |
|---|---|---|---|---|---|---|
| RXP Principal     | 195.200.7.36   | 8    | 32GB  | Docker Swarm + Traefik             | Aurora CRM, site RXP, n8n, EvoNexus, Cal.com      | VPS_RXP_*               |
| XMACNA            | 31.97.26.170   | 4    | 16GB  | Docker Swarm + Traefik v3.4        | TwentyCRM, Mautic, n8n, MySQL, PostgreSQL, Redis   | VPS_XMACNA_*            |
| Redigir           | 31.97.26.91    | 4    | 8GB   | Docker Swarm + Traefik v3.4        | Mautic, Cal.com, EvoNexus, redigir-propostas, PG   | VPS_REDIGIR_*           |
| Nogueira Resolve  | 72.61.37.50    | 2    | 4GB   | Docker (Hostinger)                 | n8n, Mautic, Evolution API, Cal.com                | VPS_NOGUEIRA_*          |
| Futuro Eventos    | 72.62.15.20    | 4    | 16GB  | Docker Swarm (Rosing KVM4)         | Evolution API, Mautic, Cal.com, n8n, Directus, PG  | VPS_FUTURO_*            |
| Members (Rosing)  | 2.24.200.240   | 4    | 16GB  | Ubuntu 24.04 (VPS zerada/setup pendente: Docker+Nexus) | Seven Fontes (Renato Campos) + RXP (a definir) | VPS_MEMBERS_*           |
| 7Fontes           | 31.97.254.154  | 4    | 8GB   | Docker Swarm, EvoNexus (renato)    | Plataforma de membros educacional                  | (acesso direto renato)  |
"""

PROMPT = f"""Você é o agente de health check de infraestrutura. Realize uma verificação completa de saúde em TODAS as VPS gerenciadas.

## Inventário de VPS

{VPS_INVENTORY}

Use as skills `custom-int-vps-rxp`, `custom-int-vps-xmacna`, `custom-int-vps-redigir`, `custom-int-vps-nogueira-resolve`, `custom-int-vps-futuro-eventos`, `custom-int-vps-members-project` e `custom-int-vps-7fontes` para conectar via SSH em cada VPS. Se uma VPS estiver inacessível por SSH (credencial pendente), reporte como ⚠ "sem acesso SSH" mas ainda confirme se responde via TCP (portas 443/80/22) para distinguir queda real de falta de credencial.

## Roteiro de verificação (para cada VPS)

Para cada VPS, conecte via SSH e verifique:

1. **Load average** — `uptime` → alerta se load > vCPU (normalizado)
2. **Memória** — `free -h` → alerta se uso > 85%
3. **Disco** — `df -h /` → alerta se uso > 80%
4. **Docker** — `docker service ls` (se Swarm) ou `docker ps` → serviços com 0 réplicas ativas ou containers em restart loop
5. **Logs críticos** — `journalctl -p err --since "1 hour ago" --no-pager -q | tail -10` → erros críticos do sistema
6. **Uptime** — alerta se VPS reiniciou nas últimas 24h (uptime < 24h)

## Critérios de alerta

- 🔴 CRÍTICO: load > (vCPU × 2), disco > 90%, serviço com 0 réplicas ativas, VPS inacessível
- 🟡 ATENÇÃO: load > vCPU, disco > 80%, memória > 85%, container reiniciando, uptime < 24h
- 🟢 OK: tudo dentro dos limites

## Output esperado

1. Tabela resumo com status por VPS (🔴/🟡/🟢) e principais métricas (load, mem%, disco%)
2. Para cada problema: VPS, recurso afetado, valor atual vs threshold, ação recomendada
3. Se tudo OK: uma linha por VPS confirmando
4. Sempre envie uma notificação via Telegram para Daniel com o resumo do health check — uma linha por VPS com status (🔴/🟡/🟢) e as principais métricas. Se houver 🔴 ou 2+ 🟡, destaque os alertas no início da mensagem.
"""

def main():
    banner("🖥 VPS Health Check", "RXP • XMACNA • Redigir • Nogueira • Futuro • Members • 7Fontes | @clawdia")
    results = []
    results.append(run_claude(
        PROMPT,
        log_name="vps-health",
        timeout=300,
        agent="clawdia-assistant",
    ))
    summary(results, "VPS Health")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ Cancelado.")
