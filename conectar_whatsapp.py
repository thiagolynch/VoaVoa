"""Cria/conecta a instância Evolution API e salva o QR Code em HTML."""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


PASTA_PROJETO = Path(__file__).resolve().parent
load_dotenv(PASTA_PROJETO / ".env")

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "http://127.0.0.1:8080").rstrip("/")
EVOLUTION_INSTANCE_NAME = os.getenv("EVOLUTION_INSTANCE_NAME", "voavoa")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
QR_HTML_FILE = PASTA_PROJETO / "qrcode.html"


def requisitar_json(url: str, *, payload: dict | None = None) -> dict:
    headers = {"apikey": EVOLUTION_API_KEY, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if payload is not None else "GET"
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def extrair_qr(resposta: dict) -> str | None:
    qrcode = resposta.get("qrcode")
    if isinstance(qrcode, dict) and isinstance(qrcode.get("base64"), str):
        return qrcode["base64"]
    if isinstance(resposta.get("base64"), str):
        return resposta["base64"]
    return None


def gerar_html(qr_base64: str) -> Path:
    # A API costuma retornar uma data URI completa; quando retorna só base64,
    # acrescentamos o prefixo exigido pelo atributo src da imagem.
    if qr_base64.startswith("data:image/png;base64,"):
        src = qr_base64
    elif qr_base64.startswith("data:"):
        raise ValueError("Formato de imagem QR Code não reconhecido")
    else:
        src = f"data:image/png;base64,{qr_base64}"

    criado_em = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
    QR_HTML_FILE.write_text(
        '<!doctype html>\n<html lang="pt-BR">\n<head><meta charset="utf-8">'
        '<title>VOAVOA — Conectar WhatsApp</title></head>\n<body>'
        '<h1>Conectar WhatsApp do VOAVOA</h1>'
        '<p>No WhatsApp, abra Aparelhos conectados e escaneie o código.</p>'
        f'<p>QR Code gerado em {criado_em}. Se não conectar, execute o script novamente '
        'e atualize esta página antes de escanear.</p>'
        f'<img src="{src}" alt="QR Code para conectar o WhatsApp">'
        '</body>\n</html>\n',
        encoding="utf-8",
    )
    return QR_HTML_FILE


def criar_instancia() -> Path:
    if not EVOLUTION_API_KEY:
        raise ValueError("EVOLUTION_API_KEY não configurada no .env")

    try:
        resposta = requisitar_json(
            f"{EVOLUTION_API_URL}/instance/create",
            payload={
                "instanceName": EVOLUTION_INSTANCE_NAME,
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
            },
        )
    except urllib.error.HTTPError as erro:
        if erro.code not in (400, 403, 409):
            raise
        # A rota de criação pode recusar uma instância já existente.
        detalhe = erro.read().decode("utf-8", errors="replace").lower()
        if erro.code == 400 and "exist" not in detalhe and "já criad" not in detalhe:
            raise ValueError(f"Falha ao criar a instância (HTTP {erro.code}): {detalhe[:200]}") from erro
        resposta = {}

    qr_base64 = extrair_qr(resposta)
    if not qr_base64:
        resposta = requisitar_json(
            f"{EVOLUTION_API_URL}/instance/connect/{EVOLUTION_INSTANCE_NAME}"
        )
        qr_base64 = extrair_qr(resposta)
    if not qr_base64:
        raise ValueError("A API não retornou qrcode.base64; confira se a instância já está conectada")

    return gerar_html(qr_base64)


if __name__ == "__main__":
    try:
        arquivo = criar_instancia()
    except urllib.error.HTTPError as erro:
        print(f"Erro HTTP {erro.code} na Evolution API: {erro.reason}", file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, ValueError, OSError, json.JSONDecodeError) as erro:
        print(f"Não foi possível gerar o QR Code: {erro}", file=sys.stderr)
        sys.exit(1)
    print(f"QR Code salvo em {arquivo}. Abra o arquivo no navegador para escanear.")
