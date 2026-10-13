# -*- coding: utf-8 -*-
"""
whatsapp_bot.py
Servidor que recebe os webhooks de mensagem da Evolution API e cadastra
alertas sozinho, a partir de uma conversa guiada por WhatsApp. Veja
`configurar_webhook_bot.py` para apontar a Evolution API pra cá.

Também confirma alertas pendentes criados pelo formulário público
(cadastro.py): quem responde "CONFIRMAR" ativa o próprio alerta.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone

from flask import Flask, request, jsonify
from loguru import logger
from sqlalchemy import delete, select

from alertas_repo import (
    LimiteDeAlertasAtingido,
    confirmar_alertas_pendentes,
    criar_alertas_em_lote,
    janela_valida,
    normalizar_data,
    obter_ou_criar_usuario,
    rota_valida,
)
from database import conversas_bot, get_engine, usuarios
from setup_db import setup_database
from whatsapp import enviar_alerta_whatsapp, whatsapp_configurado

CONVERSA_TTL_MINUTOS = 30
CAMPOS_PERGUNTAS = {
    "nome": "Pra chamar você como, qual seu nome?",
    "preco_alvo": "Qual o preço-alvo (em R$) pra essa rota? Ex: 2000",
    "data_viagem": (
        "Pra qual data ou mês da viagem? Ex: 2027-01 ou 15/01/2027.\n"
        "Se a data for flexível, manda um período, ex: 01/01/2027 a 10/01/2027"
    ),
    "duracao_min_noites": "Quantas noites no mínimo você quer ficar? Ex: 5",
}
TEXTO_AJUDA = (
    "✈️ *VOAVOA*\n\nPra criar um alerta, me manda a origem e o destino "
    "(código do aeroporto), por exemplo:\n*GRU SCL*\n\n"
    "Pra vários destinos de uma vez, separe por vírgula:\n*GRU SCL,EZE,LIM*\n\n"
    "Ou clique em \"Quero alerta no WhatsApp\" na vitrine de preços."
)

engine = get_engine()
setup_database(engine)

app = Flask(__name__)


# ─── Extração do payload da Evolution API ──────────────────────────────────

def extrair_mensagens(payload: dict):
    data = payload.get("data")
    if isinstance(data, dict) and "key" in data:
        yield data
    elif isinstance(data, dict) and isinstance(data.get("messages"), list):
        yield from data["messages"]
    elif isinstance(data, list):
        yield from data


def extrair_texto(mensagem: dict) -> str | None:
    msg = mensagem.get("message") or {}
    if isinstance(msg.get("conversation"), str):
        return msg["conversation"]
    estendida = msg.get("extendedTextMessage")
    if isinstance(estendida, dict) and isinstance(estendida.get("text"), str):
        return estendida["text"]
    return None


# ─── Parsers de texto livre ─────────────────────────────────────────────────

def parse_preco(texto: str) -> float | None:
    limpo = re.sub(r"[^\d,.]", "", texto or "")
    if not limpo:
        return None
    if "," in limpo and "." in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif "," in limpo:
        limpo = limpo.replace(",", ".")
    try:
        valor = float(limpo)
        return valor if valor > 0 else None
    except ValueError:
        return None


def parse_data_viagem(texto: str) -> str | None:
    texto = (texto or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", texto):
        return normalizar_data(texto)
    m = re.fullmatch(r"(\d{2})/(\d{4})", texto)
    if m:
        mes, ano = m.groups()
        return normalizar_data(f"{ano}-{mes}")
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", texto)
    if m:
        dia, mes, ano = m.groups()
        candidato = f"{ano}-{mes}-{dia}"
        try:
            datetime.strptime(candidato, "%Y-%m-%d")
        except ValueError:
            return None
        return candidato
    return None


def parse_janela(texto: str) -> tuple[str, str] | None:
    """Reconhece um período ("01/01/2027 a 10/01/2027" ou
    "2027-01-01 até 2027-01-10"). None se não for um período válido."""
    texto = texto.strip()
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:a|até|ate)\s*(\d{4}-\d{2}-\d{2})", texto, re.IGNORECASE)
    if not m:
        m2 = re.search(
            r"(\d{2}/\d{2}/\d{4})\s*(?:a|até|ate)\s*(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE
        )
        if not m2:
            return None
        def converter(data_br):
            dia, mes, ano = data_br.split("/")
            return f"{ano}-{mes}-{dia}"
        inicio, fim = converter(m2.group(1)), converter(m2.group(2))
    else:
        inicio, fim = m.group(1), m.group(2)

    try:
        datetime.strptime(inicio, "%Y-%m-%d")
        datetime.strptime(fim, "%Y-%m-%d")
    except ValueError:
        return None
    return inicio, fim


def extrair_pedido(texto: str) -> dict | None:
    """Reconhece tanto o texto pré-preenchido do botão do site quanto um
    pedido livre curto ("GRU SCL 2000" ou "GRU SCL,EZE,LIM 2000")."""
    m = re.search(r"\(([A-Za-z]{3})\).*?\(([A-Za-z]{3})\)", texto)
    resto = None
    if m:
        origem, destinos = m.group(1).upper(), [m.group(2).upper()]
    else:
        m2 = re.match(
            r"^\s*([A-Za-z]{3})\s+([A-Za-z]{3}(?:\s*,\s*[A-Za-z]{3})*)(?:\s+(.+))?$", texto.strip()
        )
        if not m2:
            return None
        origem = m2.group(1).upper()
        destinos = [d.strip().upper() for d in m2.group(2).split(",")]
        resto = m2.group(3)

    destinos_validos = [d for d in destinos if rota_valida(origem, d)]
    if not destinos_validos:
        return None

    preco_match = re.search(r"R\$\s*([\d.,]+)", texto)
    preco = parse_preco(preco_match.group(1)) if preco_match else None
    if preco is None and resto:
        preco = parse_preco(resto)

    return {"origem": origem, "destinos": destinos_validos, "preco_alvo": preco}


# ─── Estado da conversa (tabela Conversas_Bot) ──────────────────────────────

def carregar_conversa(telefone: str) -> dict | None:
    with engine.connect() as connection:
        linha = connection.execute(
            select(conversas_bot).where(conversas_bot.c.Telefone == telefone)
        ).mappings().first()
    if not linha:
        return None
    atualizado = datetime.fromisoformat(linha["Atualizado_Em"])
    if datetime.now(timezone.utc) - atualizado > timedelta(minutes=CONVERSA_TTL_MINUTOS):
        apagar_conversa(telefone)
        return None
    return {"estado": linha["Estado"], "dados": json.loads(linha["Dados"] or "{}")}


def salvar_conversa(telefone: str, estado: str, dados: dict):
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with engine.begin() as connection:
        connection.execute(delete(conversas_bot).where(conversas_bot.c.Telefone == telefone))
        connection.execute(conversas_bot.insert().values(
            Telefone=telefone, Estado=estado, Dados=json.dumps(dados), Atualizado_Em=agora,
        ))


def apagar_conversa(telefone: str):
    with engine.begin() as connection:
        connection.execute(delete(conversas_bot).where(conversas_bot.c.Telefone == telefone))


def usuario_existe(telefone: str) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            select(usuarios.c.ID).where(usuarios.c.Telefone_WhatsApp == telefone)
        ).scalar() is not None


def proximo_campo_faltante(dados: dict, telefone: str) -> str | None:
    if not usuario_existe(telefone) and not dados.get("nome"):
        return "nome"
    if not dados.get("preco_alvo"):
        return "preco_alvo"
    if "data_viagem" not in dados and "data_inicio" not in dados:
        return "data_viagem"
    if dados.get("data_fim") and not dados.get("duracao_min_noites"):
        return "duracao_min_noites"
    return None


def finalizar_alerta(telefone: str, dados: dict, push_name: str | None) -> str:
    nome = dados.get("nome") or push_name or "Cliente VOAVOA"
    data_viagem = dados.get("data_viagem") or dados["data_inicio"]
    try:
        id_usuario = obter_ou_criar_usuario(engine, nome, telefone)
        ids = criar_alertas_em_lote(
            engine, id_usuario, dados["origem"], dados["destinos"],
            data_viagem, float(dados["preco_alvo"]), confirmado=True,
            data_inicio=dados.get("data_inicio"), data_fim=dados.get("data_fim"),
            duracao_min_noites=dados.get("duracao_min_noites"),
        )
    except (LimiteDeAlertasAtingido, ValueError) as erro:
        return f"😕 {erro}"
    apagar_conversa(telefone)
    preco_fmt = f"R$ {dados['preco_alvo']:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    destinos_fmt = ", ".join(dados["destinos"])
    periodo = (
        f"entre {dados['data_inicio']} e {dados['data_fim']}, {dados['duracao_min_noites']}+ noites"
        if dados.get("data_fim") else data_viagem
    )
    return (
        f"✅ {len(ids)} alerta(s) criado(s)! {dados['origem']} → {destinos_fmt} até {preco_fmt}.\n"
        f"Período: {periodo}\n\nVou te avisar por aqui assim que o preço cair até esse valor."
    )


def continuar_fluxo(telefone: str, dados: dict, push_name: str | None) -> str:
    campo = proximo_campo_faltante(dados, telefone)
    if campo is None:
        return finalizar_alerta(telefone, dados, push_name)
    salvar_conversa(telefone, campo, dados)
    return CAMPOS_PERGUNTAS[campo]


def continuar_conversa(telefone: str, conversa: dict, texto: str) -> str:
    campo, dados = conversa["estado"], conversa["dados"]
    if campo == "nome":
        if len(texto.strip()) < 2:
            return "Não entendi — qual seu nome?"
        dados["nome"] = texto.strip()
    elif campo == "preco_alvo":
        preco = parse_preco(texto)
        if preco is None:
            return "Não entendi o preço. Manda só o número, ex: 2000"
        dados["preco_alvo"] = preco
    elif campo == "data_viagem":
        data_viagem = parse_data_viagem(texto)
        if data_viagem is not None:
            dados["data_viagem"] = data_viagem
        else:
            janela = parse_janela(texto)
            if janela is None:
                return (
                    "Não entendi a data. Use AAAA-MM, DD/MM/AAAA, MM/AAAA, "
                    "ou um período tipo '01/01/2027 a 10/01/2027'."
                )
            inicio, fim = janela
            if not janela_valida(date.fromisoformat(inicio), date.fromisoformat(fim)):
                return "Esse período não é válido ou é grande demais. Tenta um período menor."
            dados["data_inicio"], dados["data_fim"] = inicio, fim
    elif campo == "duracao_min_noites":
        m = re.search(r"\d+", texto)
        if not m or int(m.group()) < 1:
            return "Não entendi. Manda só o número de noites, ex: 5"
        dados["duracao_min_noites"] = int(m.group())
    return continuar_fluxo(telefone, dados, push_name=None)


def processar_mensagem(telefone: str, texto: str, push_name: str | None) -> str | None:
    texto = (texto or "").strip()
    if not texto:
        return None

    if re.search(r"\b(confirmar|confirmo|sim)\b", texto, re.IGNORECASE):
        confirmados = confirmar_alertas_pendentes(engine, telefone)
        if confirmados:
            return "✅ Alerta confirmado! Vou te avisar por aqui quando o preço cair até a sua meta."

    conversa = carregar_conversa(telefone)
    if conversa:
        return continuar_conversa(telefone, conversa, texto)

    pedido = extrair_pedido(texto)
    if not pedido:
        return TEXTO_AJUDA

    return continuar_fluxo(telefone, pedido, push_name)


# ─── Rota HTTP ───────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def saude():
    return jsonify({"status": "ok"})


@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    for mensagem in extrair_mensagens(payload):
        chave = mensagem.get("key") or {}
        remote_jid = chave.get("remoteJid") or ""
        if chave.get("fromMe") or not remote_jid or remote_jid.endswith("@g.us"):
            continue

        telefone = "+" + remote_jid.split("@")[0]
        texto = extrair_texto(mensagem)
        push_name = mensagem.get("pushName")

        try:
            resposta = processar_mensagem(telefone, texto, push_name)
        except Exception:
            logger.exception(f"Erro processando mensagem de {telefone}")
            resposta = "Ops, deu um problema aqui. Tenta de novo em alguns minutos?"

        if resposta and whatsapp_configurado():
            enviar_alerta_whatsapp(telefone, resposta)
        elif resposta:
            logger.warning(f"WhatsApp não configurado — resposta não enviada para {telefone}: {resposta}")

    return jsonify({"ok": True})


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    app.run(host="0.0.0.0", port=5000)
