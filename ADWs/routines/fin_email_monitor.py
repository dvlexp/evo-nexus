#!/usr/bin/env python3
"""ADW: Financial Email Monitor — Monitora emails Nubank/Asaas e cria tickets de aprovação via Flux"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner import run_skill, banner, summary

def main():
    banner("💰 Financial Email Monitor", "Nubank • Asaas • Tickets de aprovação | @flux")
    results = []
    results.append(run_skill(
        "fin-email-monitor",
        log_name="fin-email-monitor",
        timeout=300,
        agent="flux-finance",
        notify_telegram=True,
    ))
    summary(results, "Financial Email Monitor")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ Cancelado.")
