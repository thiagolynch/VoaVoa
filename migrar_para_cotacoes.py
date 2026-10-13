# -*- coding: utf-8 -*-
"""
migrar_para_cotacoes.py
Converte os monitoramentos e o histórico de preço que já existiam (modelo
antigo, com preço-alvo e um Historico_Precos por alerta) para o novo
modelo: Rotas_Coleta compartilhadas + Cotacoes. Pode rodar mais de uma vez
sem duplicar nada — é seguro incluir no deploy.

Não apaga Preco_Alvo nem Historico_Precos; só deixam de ser usados.

Uso:  python migrar_para_cotacoes.py
"""
import sys
from datetime import date

from loguru import logger
from sqlalchemy import text

from alertas_repo import normalizar_data, obter_ou_criar_rota_coleta
from database import get_engine
from setup_db import setup_database


def migrar():
    engine = get_engine()
    setup_database(engine)

    with engine.connect() as connection:
        alertas = connection.execute(text("""
            SELECT "ID_Alerta", "IATA_Origem", "IATA_Destino", "Mes_Viagem_Ou_Data",
                   "Data_Inicio_Janela", "Data_Fim_Janela", "ID_Rota_Coleta"
            FROM "Alertas"
            WHERE "ID_Rota_Coleta" IS NULL
              AND ("Data_Fim_Janela" IS NULL OR "Data_Fim_Janela" = "Data_Inicio_Janela")
        """)).mappings().all()

    ligados = 0
    for alerta in alertas:
        data_viagem = normalizar_data(alerta["Mes_Viagem_Ou_Data"])
        if data_viagem < date.today().isoformat():
            continue  # viagem já passou: não vale criar rota de coleta pra ela
        id_rota = obter_ou_criar_rota_coleta(
            engine, alerta["IATA_Origem"], alerta["IATA_Destino"], data_viagem, None
        )
        with engine.begin() as connection:
            connection.execute(text(
                'UPDATE "Alertas" SET "ID_Rota_Coleta" = :r WHERE "ID_Alerta" = :id'
            ), {"r": id_rota, "id": alerta["ID_Alerta"]})
        ligados += 1
        logger.info(f"Alerta #{alerta['ID_Alerta']} ligado à rota #{id_rota}.")

    with engine.connect() as connection:
        historico = connection.execute(text("""
            SELECT h."ID_Historico", h."Data_Verificacao", h."Preco_Encontrado", a."ID_Rota_Coleta"
            FROM "Historico_Precos" h
            JOIN "Alertas" a ON a."ID_Alerta" = h."ID_Alerta"
            WHERE a."ID_Rota_Coleta" IS NOT NULL
        """)).mappings().all()

    copiados = 0
    for linha in historico:
        data_ref = linha["Data_Verificacao"][:10]
        with engine.begin() as connection:
            ja_existe = connection.execute(text("""
                SELECT 1 FROM "Cotacoes"
                WHERE "ID_Rota" = :r AND "Data_Referencia" = :d AND "Fonte" = 'coleta_diaria'
            """), {"r": linha["ID_Rota_Coleta"], "d": data_ref}).first()
            if ja_existe:
                continue
            connection.execute(text("""
                INSERT INTO "Cotacoes" ("ID_Rota", "Coletado_Em", "Data_Referencia", "Preco", "Fonte")
                VALUES (:r, :coletado, :data_ref, :preco, 'coleta_diaria')
            """), {
                "r": linha["ID_Rota_Coleta"], "coletado": linha["Data_Verificacao"],
                "data_ref": data_ref, "preco": linha["Preco_Encontrado"],
            })
            copiados += 1

    logger.success(
        f"Migração concluída: {ligados} alerta(s) ligado(s) a uma rota de coleta, "
        f"{copiados} cotação(ões) copiada(s) do histórico antigo."
    )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    migrar()
