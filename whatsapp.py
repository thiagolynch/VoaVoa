# -*- coding: utf-8 -*-
"""
whatsapp.py
Envio de mensagens via Evolution API (compatível com v2 e v1).
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).resolve().parent / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8080").rstrip("/")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "voavoa")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")


def whatsapp_configurado() -> bool:
    """Falso quando falta a chave ou quando rodamos na nuvem (GitHub Actions)
    apontando para localhost — lá o Docker do seu PC não é alcançável."""
    if not EVOLUTION_API_KEY:
        return False
    host = urlparse(EVOLUTION_API_URL).hostname or ""
    if os.getenv("GITHUB_ACTIONS") == "true" and host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return False
    return True


def enviar_alerta_whatsapp(telefone: str, mensagem: str) -> bool:
    if not whatsapp_configurado():
        logger.warning("WhatsApp não configurado/alcançável — mensagem não enviada.")
        return False

    numero = "".join(c for c in telefone or "" if c.isdigit())
    if not numero or not mensagem:
        logger.error("Telefone (com DDI e DDD) e mensagem são obrigatórios.")
        return False

    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE_NAME}"
    headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
    corpos = [
        {"number": numero, "text": mensagem, "delay": 1200},                     # Evolution v2
        {"number": numero, "options": {"delay": 1200, "presence": "composing"},   # Evolution v1
         "textMessage": {"text": mensagem}},
    ]

    for corpo in corpos:
        try:
            resposta = requests.post(url, json=corpo, headers=headers, timeout=20)
        except requests.RequestException as erro:
            logger.error(f"❌ Sem conexão com a Evolution API ({EVOLUTION_API_URL}): {erro}")
            return False
        if resposta.status_code in (200, 201):
            logger.success(f"✅ Mensagem aceita pela Evolution API para {telefone}.")
            return True
        if resposta.status_code != 400:
            break  # 401/404/500: trocar o formato não resolve
    logger.error(f"❌ Evolution API recusou o envio (HTTP {resposta.status_code}): {resposta.text[:300]}")
    return False
