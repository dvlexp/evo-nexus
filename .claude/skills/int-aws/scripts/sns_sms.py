#!/usr/bin/env python3
"""SNS SMS helper — envio, verificação e status via Amazon SNS."""

import argparse
import boto3
import csv
import os
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-east-1")


def get_client():
    return boto3.client(
        "sns",
        region_name=REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def format_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("55"):
        return f"+{digits}"
    if len(digits) in (10, 11):
        return f"+55{digits}"
    return f"+{digits}"


def send_sms(phone: str, message: str) -> dict:
    client = get_client()
    resp = client.publish(
        PhoneNumber=format_phone(phone),
        Message=message,
        MessageAttributes={
            "AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"},
            "AWS.SNS.SMS.SenderID": {"DataType": "String", "StringValue": "EvoNexus"},
        },
    )
    return resp


def cmd_send(args):
    resp = send_sms(args.phone, args.message)
    print(f"✅ Enviado! MessageId: {resp['MessageId']}")


def cmd_bulk(args):
    with open(args.file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Enviando para {len(rows)} números...")
    sent, failed = 0, 0
    for row in rows:
        phone = row.get("phone") or row.get("telefone") or row.get("celular", "")
        message = row.get("message") or row.get("mensagem", "")
        if not phone or not message:
            print(f"  ⚠️  Linha ignorada (phone ou message vazio): {row}")
            continue
        try:
            send_sms(phone, message)
            print(f"  ✅ {phone}")
            sent += 1
        except Exception as e:
            print(f"  ❌ {phone}: {e}")
            failed += 1
        time.sleep(0.3)

    print(f"\nResumo: {sent} enviados, {failed} falhas")


def cmd_status(args):
    client = get_client()
    attrs = client.get_sms_attributes()["attributes"]
    print("📊 Status SNS SMS:")
    for k, v in attrs.items():
        print(f"  {k}: {v}")

    try:
        sandbox = client.get_sms_sandbox_account_status()
        in_sandbox = sandbox.get("IsInSandbox", True)
        print(f"\n  Sandbox: {'⚠️  SIM (apenas números verificados)' if in_sandbox else '✅ NÃO (produção)'}")
    except Exception:
        pass


def cmd_list_verified(args):
    client = get_client()
    resp = client.list_sms_sandbox_phone_numbers()
    numbers = resp.get("PhoneNumbers", [])
    if not numbers:
        print("Nenhum número verificado no sandbox.")
        return
    print("Números no sandbox:")
    for n in numbers:
        status = "✅ Verificado" if n["Status"] == "Verified" else "⏳ Pendente"
        print(f"  {n['PhoneNumber']} — {status}")


def cmd_verify(args):
    client = get_client()
    client.verify_sms_sandbox_phone_number(
        PhoneNumber=format_phone(args.phone),
        OneTimePassword=args.code,
    )
    print(f"✅ Número {args.phone} verificado com sucesso!")


def main():
    parser = argparse.ArgumentParser(description="SNS SMS helper")
    sub = parser.add_subparsers(dest="cmd")

    p_send = sub.add_parser("send", help="Enviar SMS avulso")
    p_send.add_argument("--phone", required=True)
    p_send.add_argument("--message", required=True)

    p_bulk = sub.add_parser("bulk", help="Envio em massa via CSV (phone,message)")
    p_bulk.add_argument("--file", required=True)

    sub.add_parser("status", help="Status da conta SNS")
    sub.add_parser("list-verified", help="Listar números verificados no sandbox")

    p_verify = sub.add_parser("verify", help="Verificar número no sandbox")
    p_verify.add_argument("--phone", required=True)
    p_verify.add_argument("--code", required=True)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "send": cmd_send,
        "bulk": cmd_bulk,
        "status": cmd_status,
        "list-verified": cmd_list_verified,
        "verify": cmd_verify,
    }
    cmds[args.cmd](args)


if __name__ == "__main__":
    main()
