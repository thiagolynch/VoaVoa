# -*- coding: utf-8 -*-
"""
configurar_webhook_bot.py
Aponta a Evolution API pra chamar o whatsapp_bot.py quando chegar mensagem.
Rode uma vez (ou de novo se a instância for recriada):

    python configurar_webhook_bot.py
"""
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8080").rstrip("/")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "voavoa")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
WEBHOOK_URL = os.getenv("WHATSAPP_BOT_WEBHOOK_URL", "http://whatsapp-bot:5000/webhook")


def main():
    if not EVOLUTION_API_KEY:
        print("EVOLUTION_API_KEY não configurada no .env", file=sys.stderr)
        sys.exit(1)

    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    corpo = {
        "webhook": {
            "enabled": True,
            "url": WEBHOOK_URL,
            "webhookByEvents": False,
            "webhookBase64": False,
            "events": ["MESSAGES_UPSERT"],
        }
    }
    resposta = requests.post(
        f"{EVOLUTION_API_URL}/webhook/set/{EVOLUTION_INSTANCE_NAME}",
        json=corpo, headers=headers, timeout=20,
    )
    print(f"POST /webhook/set -> {resposta.status_code}: {resposta.text[:500]}")
    resposta.raise_for_status()

    conferencia = requests.get(
        f"{EVOLUTION_API_URL}/webhook/find/{EVOLUTION_INSTANCE_NAME}",
        headers=headers, timeout=20,
    )
    print(f"GET /webhook/find -> {conferencia.status_code}: {conferencia.text[:500]}")


if __name__ == "__main__":
    main()
