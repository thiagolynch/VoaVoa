# -*- coding: utf-8 -*-
"""
coleta_diaria.py
Varredura diária de preços. Sem preço-alvo: cada rota é acompanhada desde o
dia do cadastro, e o WhatsApp só sai quando o preço cai de verdade.

Uma única consulta por Rota_Coleta atende todo mundo que pediu a mesma
combinação de origens + destino + datas — a economia de cota não vem de
buscar menos, vem de nunca buscar a mesma coisa duas vezes.

Motivos de aviso (no máximo um por monitoramento por dia):
  novo_minimo    -> menor preço desde o início do acompanhamento (nunca no 1º dia)
  abaixo_media   -> preço hoje <= média dos últimos 30 dias * (1 - LIMIAR_QUEDA_PCT)
  ficou_barato   -> o Google passou a marcar "nivel=low" e não estava assim ontem
  resumo_semanal -> toda segunda-feira, independente das regras acima

Uso:  python coleta_diaria.py             (varredura diária completa)
      python coleta_diaria.py --so-resumo (só manda o resumo semanal, sem consultar a SerpApi)
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from loguru import logger
from sqlalchemy import text

from alertas_repo import limpar_alertas_nao_confirmados, normalizar_data, obter_ou_criar_rota_coleta
from database import get_engine
from google_flights import buscar_voo
from setup_db import setup_database
from whatsapp import enviar_alerta_whatsapp, whatsapp_configurado

LIMIAR_QUEDA_PCT = float(os.getenv("LIMIAR_QUEDA_PCT", "0.10"))
MAX_CONSULTAS_DIA = int(os.getenv("MAX_CONSULTAS_DIA", "8"))


def configurar_logs():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True, level="DEBUG",
    )
    logger.add(
        "voavoa.log",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}",
        rotation="1 MB", retention="7 days", level="DEBUG", encoding="utf-8",
    )


def formatar_reais(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def buscar_melhor_preco_na_janela(origem: str, destino: str, data_inicio: str,
                                    data_fim: str, duracao_min_noites: int):
    passo = int(os.getenv("JANELA_AMOSTRAGEM_DIAS", "3"))
    inicio, fim = date.fromisoformat(data_inicio), date.fromisoformat(data_fim)
    candidatas = []
    atual = inicio
    while atual < fim:
        candidatas.append(atual)
        atual += timedelta(days=passo)
    candidatas.append(fim)

    melhor, melhor_ida, melhor_volta = None, None, None
    for ida in candidatas:
        volta = ida + timedelta(days=duracao_min_noites)
        resultado = buscar_voo(origem, destino, ida.isoformat(), volta.isoformat())
        if resultado and (melhor is None or resultado.preco < melhor.preco):
            melhor, melhor_ida, melhor_volta = resultado, ida, volta
    if melhor is None:
        return None
    return melhor, melhor_ida.isoformat(), melhor_volta.isoformat()


def rotas_pendentes_hoje(connection, hoje_iso: str, limite: int) -> list[dict]:
    """Rotas de data fixa com pelo menos um monitoramento ativo e
    confirmado, que ainda não foram coletadas hoje, priorizando as mais
    desatualizadas. Rotas cuja data de ida já passou são ignoradas."""
    linhas = connection.execute(text("""
        SELECT r."ID_Rota", r."Origens", r."IATA_Destino", r."Data_Ida", r."Data_Volta",
               MAX(c."Data_Referencia") AS ultima_coleta
        FROM "Rotas_Coleta" r
        JOIN "Alertas" a ON a."ID_Rota_Coleta" = r."ID_Rota"
        JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
        LEFT JOIN "Cotacoes" c ON c."ID_Rota" = r."ID_Rota" AND c."Fonte" = 'coleta_diaria'
        WHERE a."Confirmado" = 1 AND u."Opt_in" = 1 AND r."Data_Ida" >= :hoje
        GROUP BY r."ID_Rota", r."Origens", r."IATA_Destino", r."Data_Ida", r."Data_Volta"
        HAVING MAX(c."Data_Referencia") IS NULL OR MAX(c."Data_Referencia") < :hoje
        ORDER BY ultima_coleta IS NOT NULL, ultima_coleta ASC
        LIMIT :limite
    """), {"hoje": hoje_iso, "limite": limite}).mappings().all()
    return [dict(linha) for linha in linhas]


def monitoramentos_da_rota(connection, id_rota: int) -> list[dict]:
    linhas = connection.execute(text("""
        SELECT a."ID_Alerta", u."Nome" AS "Nome_Usuario", u."Telefone_WhatsApp",
               a."IATA_Origem", a."IATA_Destino",
               o."Nome_Cidade" AS "Cidade_Origem", d."Nome_Cidade" AS "Cidade_Destino"
        FROM "Alertas" a
        JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
        LEFT JOIN "Destinos" o ON o."IATA" = SUBSTR(a."IATA_Origem", 1, 3)
        JOIN "Destinos" d ON d."IATA" = a."IATA_Destino"
        WHERE a."ID_Rota_Coleta" = :id_rota AND a."Confirmado" = 1
    """), {"id_rota": id_rota}).mappings().all()
    return [dict(linha) for linha in linhas]


def gravar_cotacao(connection, id_rota: int, preco: float, aeroporto_saida, companhia,
                    escalas, duracao_min, nivel, faixa, agora_iso: str, data_ref: str, fonte: str):
    ja_existe = connection.execute(text("""
        SELECT 1 FROM "Cotacoes" WHERE "ID_Rota" = :r AND "Data_Referencia" = :d AND "Fonte" = :f
    """), {"r": id_rota, "d": data_ref, "f": fonte}).first()
    if ja_existe:
        return
    connection.execute(text("""
        INSERT INTO "Cotacoes"
            ("ID_Rota", "Coletado_Em", "Data_Referencia", "Preco", "Aeroporto_Saida",
             "Companhia", "Escalas", "Duracao_Min", "Nivel_Google",
             "Faixa_Tipica_Min", "Faixa_Tipica_Max", "Fonte")
        VALUES (:r, :coletado, :data_ref, :preco, :saida, :cia, :escalas, :duracao,
                :nivel, :faixa_min, :faixa_max, :fonte)
    """), {
        "r": id_rota, "coletado": agora_iso, "data_ref": data_ref, "preco": preco,
        "saida": aeroporto_saida, "cia": companhia, "escalas": escalas, "duracao": duracao_min,
        "nivel": nivel, "faixa_min": (faixa or [None, None])[0], "faixa_max": (faixa or [None, None])[1],
        "fonte": fonte,
    })


def gravar_resultado(connection, id_rota: int, resultado, agora_iso: str, hoje_iso: str):
    for dia, preco in resultado.historico:
        if dia < hoje_iso:
            gravar_cotacao(connection, id_rota, preco, None, None, None, None, None, None,
                            agora_iso, dia, "historico_google")
    gravar_cotacao(
        connection, id_rota, resultado.preco, resultado.aeroporto_saida, resultado.companhia,
        resultado.escalas, resultado.duracao_min, resultado.nivel, resultado.faixa_tipica,
        agora_iso, hoje_iso, "coleta_diaria",
    )


def serie_precos_rota(connection, id_rota: int, ate_hoje_exclusive: str) -> list[tuple[str, float, str | None]]:
    """[(data, preço, nível)] de uma rota, um ponto por dia (prioriza a
    coleta diária sobre o histórico do Google no mesmo dia), até ontem."""
    linhas = connection.execute(text("""
        SELECT "Data_Referencia", "Preco", "Nivel_Google", "Fonte" FROM "Cotacoes"
        WHERE "ID_Rota" = :r AND "Data_Referencia" < :hoje
        ORDER BY "Data_Referencia" ASC,
                 CASE "Fonte" WHEN 'coleta_diaria' THEN 0 ELSE 1 END ASC
    """), {"r": id_rota, "hoje": ate_hoje_exclusive}).all()
    por_dia = {}
    for data_ref, preco, nivel, _fonte in linhas:
        por_dia.setdefault(data_ref, (preco, nivel))
    return [(dia, preco, nivel) for dia, (preco, nivel) in sorted(por_dia.items())]


def motivo_notificacao(preco_hoje: float, nivel_hoje: str | None, serie_anterior) -> tuple[str, dict] | None:
    """Decide se há motivo para avisar hoje, comparando com o histórico
    (sem incluir hoje). `serie_anterior` é a saída de `serie_precos_rota`."""
    if not serie_anterior:
        return None  # dia 1: ainda não há com o que comparar

    precos_anteriores = [preco for _, preco, _ in serie_anterior]
    minimo_anterior = min(precos_anteriores)
    if preco_hoje < minimo_anterior:
        return "novo_minimo", {"minimo_anterior": minimo_anterior}

    limite_30d = (date.today() - timedelta(days=30)).isoformat()
    precos_30d = [preco for dia, preco, _ in serie_anterior if dia >= limite_30d]
    if precos_30d:
        media_30d = mean(precos_30d)
        if preco_hoje <= media_30d * (1 - LIMIAR_QUEDA_PCT):
            return "abaixo_media", {"media_30d": media_30d}

    nivel_ontem = serie_anterior[-1][2]
    if nivel_hoje == "low" and nivel_ontem != "low":
        return "ficou_barato", {}

    return None


def ja_notificado_hoje(connection, id_alerta: int, motivo: str, hoje_iso: str) -> bool:
    return connection.execute(text("""
        SELECT 1 FROM "Notificacoes"
        WHERE "ID_Alerta" = :id AND "Motivo" = :motivo AND SUBSTR("Enviado_Em", 1, 10) = :hoje
    """), {"id": id_alerta, "motivo": motivo, "hoje": hoje_iso}).first() is not None


def registrar_notificacao(connection, id_alerta: int, motivo: str, preco: float | None):
    connection.execute(text("""
        INSERT INTO "Notificacoes" ("ID_Alerta", "Enviado_Em", "Motivo", "Preco")
        VALUES (:id, :agora, :motivo, :preco)
    """), {
        "id": id_alerta, "agora": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "motivo": motivo, "preco": preco,
    })


TEXTO_MOTIVO = {
    "novo_minimo": "📉 Esse é o menor preço que já vimos para essa rota desde que começamos a acompanhar!",
    "abaixo_media": "📊 O preço está bem abaixo da média dos últimos 30 dias.",
    "ficou_barato": "🟢 O Google acabou de marcar essa rota como preço baixo.",
}


def avisar_monitoramentos(connection, monitoramentos: list[dict], resultado, destino_nome: str,
                           id_alerta_sem_nivel_anterior: set, hoje_iso: str):
    serie_rota = None  # calculada uma vez por rota, reaproveitada por todos os monitoramentos dela
    for mon in monitoramentos:
        if serie_rota is None:
            serie_rota = serie_precos_rota(connection, mon["_id_rota"], hoje_iso)
        decisao = motivo_notificacao(resultado.preco, resultado.nivel, serie_rota)
        if decisao is None:
            continue
        motivo, _detalhes = decisao
        if ja_notificado_hoje(connection, mon["ID_Alerta"], motivo, hoje_iso):
            continue

        mensagem = (
            f"✈️ *VOAVOA*\n\nOlá, *{mon['Nome_Usuario']}*! Novidade na rota que você acompanha:\n\n"
            f"🛫 *Origem:* {mon['IATA_Origem']}\n🛬 *Destino:* {destino_nome} ({mon['IATA_Destino']})\n"
            f"💰 *Preço agora:* {formatar_reais(resultado.preco)}"
            + (f" (saindo de {resultado.aeroporto_saida})" if resultado.aeroporto_saida else "") + "\n\n"
            f"{TEXTO_MOTIVO[motivo]}\n\n🔗 {resultado.google_flights_url}\n\n"
            "Preços mudam rápido — confira antes de comprar."
        )
        if enviar_alerta_whatsapp(mon["Telefone_WhatsApp"], mensagem):
            registrar_notificacao(connection, mon["ID_Alerta"], motivo, resultado.preco)
            logger.success(f"🟢 Aviso '{motivo}' enviado para {mon['Nome_Usuario']} (alerta #{mon['ID_Alerta']}).")


def coletar_rotas_fixas(engine, hoje_iso: str, limite: int) -> int:
    with engine.connect() as connection:
        rotas = rotas_pendentes_hoje(connection, hoje_iso, limite)
    if not rotas:
        logger.info("Nenhuma rota de data fixa pendente de coleta hoje.")
        return 0

    agora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    coletadas = 0
    for rota in rotas:
        logger.info(
            f"Rota #{rota['ID_Rota']} | {rota['Origens']} ➔ {rota['IATA_Destino']} | "
            f"{rota['Data_Ida']}{' / ' + rota['Data_Volta'] if rota['Data_Volta'] else ''}"
        )
        resultado = buscar_voo(rota["Origens"], rota["IATA_Destino"], rota["Data_Ida"], rota["Data_Volta"])
        if resultado is None:
            logger.error(f"Sem preço para a rota #{rota['ID_Rota']}.")
            continue
        coletadas += 1

        with engine.begin() as connection:
            gravar_resultado(connection, rota["ID_Rota"], resultado, agora_iso, hoje_iso)
            monitoramentos = monitoramentos_da_rota(connection, rota["ID_Rota"])
            for mon in monitoramentos:
                mon["_id_rota"] = rota["ID_Rota"]
            destino_nome = connection.execute(text(
                'SELECT "Nome_Cidade" FROM "Destinos" WHERE "IATA" = :d'
            ), {"d": rota["IATA_Destino"]}).scalar() or rota["IATA_Destino"]
            avisar_monitoramentos(connection, monitoramentos, resultado, destino_nome, set(), hoje_iso)

    logger.info(f"✅ {coletadas}/{len(rotas)} rota(s) de data fixa coletada(s) hoje.")
    return coletadas


def coletar_monitoramentos_em_janela(engine, hoje_iso: str) -> int:
    """Monitoramentos com período flexível: ainda resolvidos um a um (não
    compartilham cota entre usuários, porque a melhor data pode variar dia
    a dia). Gravam em Cotacoes contra a rota correspondente à data achada."""
    with engine.connect() as connection:
        monitoramentos = connection.execute(text("""
            SELECT a."ID_Alerta", u."Nome" AS "Nome_Usuario", u."Telefone_WhatsApp",
                   a."IATA_Origem", a."IATA_Destino", a."Data_Inicio_Janela", a."Data_Fim_Janela",
                   a."Duracao_Min_Noites", d."Nome_Cidade" AS "Cidade_Destino"
            FROM "Alertas" a
            JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
            JOIN "Destinos" d ON d."IATA" = a."IATA_Destino"
            WHERE a."Confirmado" = 1 AND u."Opt_in" = 1
              AND a."Data_Fim_Janela" IS NOT NULL AND a."Data_Fim_Janela" != a."Data_Inicio_Janela"
              AND a."Data_Fim_Janela" >= :hoje
        """), {"hoje": hoje_iso}).mappings().all()

    agora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    processados = 0
    for mon in monitoramentos:
        data_inicio = max(mon["Data_Inicio_Janela"], hoje_iso)
        achado = buscar_melhor_preco_na_janela(
            mon["IATA_Origem"], mon["IATA_Destino"], data_inicio,
            mon["Data_Fim_Janela"], mon["Duracao_Min_Noites"],
        )
        if achado is None:
            logger.error(f"Sem preço para o monitoramento em janela #{mon['ID_Alerta']}.")
            continue
        resultado, data_ida, data_volta = achado
        processados += 1

        with engine.begin() as connection:
            id_rota = obter_ou_criar_rota_coleta(engine, mon["IATA_Origem"], mon["IATA_Destino"], data_ida, data_volta)
            connection.execute(text(
                'UPDATE "Alertas" SET "ID_Rota_Coleta" = :r WHERE "ID_Alerta" = :id'
            ), {"r": id_rota, "id": mon["ID_Alerta"]})
            gravar_resultado(connection, id_rota, resultado, agora_iso, hoje_iso)
            mon_dict = dict(mon)
            mon_dict["_id_rota"] = id_rota
            avisar_monitoramentos(connection, [mon_dict], resultado, mon["Cidade_Destino"], set(), hoje_iso)

    logger.info(f"✅ {processados}/{len(monitoramentos)} monitoramento(s) em janela processado(s).")
    return processados


def enviar_resumos_semanais(engine, hoje: date):
    if hoje.weekday() != 0:  # 0 = segunda-feira
        return
    hoje_iso = hoje.isoformat()
    with engine.connect() as connection:
        monitoramentos = connection.execute(text("""
            SELECT a."ID_Alerta", a."ID_Rota_Coleta", u."Nome" AS "Nome_Usuario", u."Telefone_WhatsApp",
                   a."IATA_Origem", a."IATA_Destino", d."Nome_Cidade" AS "Cidade_Destino"
            FROM "Alertas" a
            JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
            JOIN "Destinos" d ON d."IATA" = a."IATA_Destino"
            WHERE a."Confirmado" = 1 AND u."Opt_in" = 1 AND a."ID_Rota_Coleta" IS NOT NULL
        """)).mappings().all()

    for mon in monitoramentos:
        with engine.begin() as connection:
            if ja_notificado_hoje(connection, mon["ID_Alerta"], "resumo_semanal", hoje_iso):
                continue
            serie = serie_precos_rota(connection, mon["ID_Rota_Coleta"], (hoje + timedelta(days=1)).isoformat())
            if len(serie) < 2:
                continue
            precos = [preco for _, preco, _ in serie]
            hoje_preco = precos[-1]
            semana_atras = next((p for d, p, _ in serie if d <= (hoje - timedelta(days=7)).isoformat()), precos[0])
            variacao_pct = (hoje_preco - semana_atras) / semana_atras * 100 if semana_atras else 0
            mensagem = (
                f"📅 *VOAVOA — resumo da semana*\n\nOlá, *{mon['Nome_Usuario']}*! Como está "
                f"{mon['IATA_Origem']} → {mon['Cidade_Destino']} ({mon['IATA_Destino']}):\n\n"
                f"💰 Hoje: {formatar_reais(hoje_preco)}\n📉 Menor desde o início: {formatar_reais(min(precos))}\n"
                f"📈 Maior desde o início: {formatar_reais(max(precos))}\n📊 Média desde o início: {formatar_reais(mean(precos))}\n"
                f"{'🔺' if variacao_pct > 0 else '🔻'} Variação na semana: {variacao_pct:+.1f}%"
            )
            if enviar_alerta_whatsapp(mon["Telefone_WhatsApp"], mensagem):
                registrar_notificacao(connection, mon["ID_Alerta"], "resumo_semanal", hoje_preco)
                logger.success(f"🟢 Resumo semanal enviado para {mon['Nome_Usuario']} (alerta #{mon['ID_Alerta']}).")


def executar(so_resumo: bool = False):
    logger.info("=" * 65)
    logger.info("🚀 VOAVOA — Coleta diária de preços (Google Flights via SerpApi)")
    logger.info("=" * 65)

    engine = get_engine()
    setup_database(engine)
    removidos = limpar_alertas_nao_confirmados(engine)
    if removidos:
        logger.info(f"🧹 {removidos} pedido(s) nunca confirmado(s) removido(s).")

    if not whatsapp_configurado():
        logger.warning("WhatsApp indisponível neste ambiente: preços serão gravados, mas sem envio de mensagens.")

    hoje = date.today()
    hoje_iso = hoje.isoformat()
    if not so_resumo:
        coletar_rotas_fixas(engine, hoje_iso, MAX_CONSULTAS_DIA)
        coletar_monitoramentos_em_janela(engine, hoje_iso)
    enviar_resumos_semanais(engine, hoje)

    logger.info("✅ Coleta diária concluída.")


if __name__ == "__main__":
    configurar_logs()
    executar(so_resumo="--so-resumo" in sys.argv)
