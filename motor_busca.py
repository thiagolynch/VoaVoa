# -*- coding: utf-8 -*-
"""
motor_busca.py
Verifica os alertas cadastrados (banco de dados), grava o histórico de preços
e envia WhatsApp quando o preço fica igual ou abaixo do preço-alvo.

Uso:  python motor_busca.py
"""
import sys
from datetime import date, datetime

from loguru import logger
from sqlalchemy import text

from database import get_engine
from google_flights import buscar_voo
from setup_db import setup_database
from whatsapp import enviar_alerta_whatsapp, whatsapp_configurado


def configurar_logs():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
        level="DEBUG",
    )
    logger.add(
        "voavoa.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="1 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )


def formatar_reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def normalizar_data(valor: str) -> str:
    """Aceita AAAA-MM (usa o dia 15) ou AAAA-MM-DD."""
    return valor if len(valor) == 10 else f"{valor}-15"


def deve_notificar(preco: float, alvo: float, preco_anterior: float | None) -> bool:
    """Avisa quando cruza a meta ou quando bate um novo mínimo abaixo da meta
    (evita mandar a mesma mensagem todo dia)."""
    if preco > alvo:
        return False
    return preco_anterior is None or preco_anterior > alvo or preco < preco_anterior


def gravar_historico(connection, id_alerta: int, preco: float, agora: str, historico_google):
    existentes = {
        linha[0][:10]
        for linha in connection.execute(text(
            'SELECT "Data_Verificacao" FROM "Historico_Precos" WHERE "ID_Alerta" = :id'
        ), {"id": id_alerta})
    }
    # Pontos do histórico do Google (preenche os 30 dias logo na 1ª consulta)
    novos = [
        {"id_alerta": id_alerta, "data": f"{dia}T12:00:00", "preco": valor}
        for dia, valor in historico_google
        if dia not in existentes and dia != agora[:10]
    ]
    novos.append({"id_alerta": id_alerta, "data": agora, "preco": preco})
    connection.execute(text("""
        INSERT INTO "Historico_Precos" ("ID_Alerta", "Data_Verificacao", "Preco_Encontrado")
        VALUES (:id_alerta, :data, :preco)
    """), novos)
    connection.execute(text("""
        UPDATE "Alertas" SET "Preco_Atual" = :preco, "Ultima_Verificacao" = :agora
        WHERE "ID_Alerta" = :id_alerta
    """), {"preco": preco, "agora": agora, "id_alerta": id_alerta})


def verificar_alertas():
    logger.info("=" * 65)
    logger.info("🚀 VOAVOA — Verificação de alertas (Google Flights via SerpApi)")
    logger.info("=" * 65)

    engine = get_engine()
    setup_database(engine)
    with engine.connect() as connection:
        alertas = connection.execute(text("""
            SELECT a."ID_Alerta", u."Nome" AS "Nome_Usuario", u."Telefone_WhatsApp",
                   a."IATA_Origem", a."IATA_Destino", a."Mes_Viagem_Ou_Data",
                   a."Preco_Alvo", a."Preco_Atual",
                   o."Nome_Cidade" AS "Cidade_Origem", d."Nome_Cidade" AS "Cidade_Destino"
            FROM "Alertas" a
            JOIN "Usuarios" u ON a."ID_Usuario" = u."ID"
            JOIN "Destinos" o ON a."IATA_Origem" = o."IATA"
            JOIN "Destinos" d ON a."IATA_Destino" = d."IATA"
            WHERE u."Opt_in" = 1
            ORDER BY a."ID_Alerta"
        """)).mappings().all()

    if not alertas:
        logger.warning("Nenhum alerta ativo no banco de dados.")
        return

    if not whatsapp_configurado():
        logger.warning("WhatsApp indisponível neste ambiente: preços serão gravados, mas sem envio de mensagens.")

    logger.info(f"🔍 {len(alertas)} alerta(s) encontrado(s).")
    for alerta in alertas:
        id_alerta = alerta["ID_Alerta"]
        origem, destino = alerta["IATA_Origem"], alerta["IATA_Destino"]
        data_viagem = normalizar_data(alerta["Mes_Viagem_Ou_Data"])
        alvo = alerta["Preco_Alvo"]

        if data_viagem < date.today().isoformat():
            logger.warning(f"Alerta #{id_alerta}: data {data_viagem} já passou — ignorado.")
            continue

        logger.info(f"Alerta #{id_alerta} | {origem} ➔ {destino} | {data_viagem} | alvo {formatar_reais(alvo)}")
        resultado = buscar_voo(origem, destino, data_viagem)
        if resultado is None:
            logger.error(f"Sem preço para o alerta #{id_alerta}.")
            continue

        agora = datetime.now().isoformat(timespec="seconds")
        with engine.begin() as connection:
            gravar_historico(connection, id_alerta, resultado.preco, agora, resultado.historico)

        if not deve_notificar(resultado.preco, alvo, alerta["Preco_Atual"]):
            logger.info(f"🟡 {formatar_reais(resultado.preco)} (alvo {formatar_reais(alvo)}) — sem notificação.")
            continue

        nivel = {"low": "🟢 baixo", "typical": "🟡 típico", "high": "🔴 alto"}.get(resultado.nivel or "")
        mensagem = (
            f"✈️ *VOAVOA — Alerta de preço!*\n\n"
            f"Olá, *{alerta['Nome_Usuario']}*! Encontramos uma oferta:\n\n"
            f"🛫 *Origem:* {alerta['Cidade_Origem']} ({origem})\n"
            f"🛬 *Destino:* {alerta['Cidade_Destino']} ({destino})\n"
            f"📅 *Data:* {datetime.fromisoformat(data_viagem).strftime('%d/%m/%Y')}\n"
            f"🎯 *Seu alvo:* {formatar_reais(alvo)}\n"
            f"💰 *Preço agora:* {formatar_reais(resultado.preco)}\n"
            + (f"📊 *Nível do preço (Google):* {nivel}\n" if nivel else "")
            + f"\n🔗 {resultado.google_flights_url}\n\n"
            f"Preços mudam rápido — confira antes de comprar."
        )
        if enviar_alerta_whatsapp(alerta["Telefone_WhatsApp"], mensagem):
            logger.success(f"🟢 Alerta #{id_alerta} enviado para {alerta['Nome_Usuario']}.")

    logger.info("✅ Verificação de alertas concluída.")


if __name__ == "__main__":
    configurar_logs()
    verificar_alertas()
