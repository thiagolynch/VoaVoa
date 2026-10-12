# -*- coding: utf-8 -*-
"""
popular_teste.py
Script temporário para inserir dados de teste no banco voavoa.db.
"""
import sys
import io
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from database import alertas, get_engine, usuarios

# Garante saída UTF-8 no terminal Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def popular():
    engine = get_engine()
    insert = sqlite_insert if engine.dialect.name == "sqlite" else postgresql_insert
    with engine.begin() as connection:
        connection.execute(
            insert(usuarios)
            .values(Nome="Thiago Teste", Telefone_WhatsApp="+5511999998888", Opt_in=1)
            .on_conflict_do_nothing(index_elements=[usuarios.c.Telefone_WhatsApp])
        )
        id_usuario = connection.execute(
            select(usuarios.c.ID).where(usuarios.c.Telefone_WhatsApp == "+5511999998888")
        ).scalar_one()
        print(f"Usuário de teste com ID={id_usuario} pronto.")

        alertas_teste = [
            ("GIG", "FLN", "2025-01", 650.00, "Voo doméstico GIG → FLN"),
            ("GRU", "MCO", "2025-07", 2800.00, "Voo internacional GRU → MCO"),
        ]
        for origem, destino, data, preco_alvo, descricao in alertas_teste:
            consulta = select(alertas.c.ID_Alerta).where(
                alertas.c.ID_Usuario == id_usuario,
                alertas.c.IATA_Origem == origem,
                alertas.c.IATA_Destino == destino,
                alertas.c.Mes_Viagem_Ou_Data == data,
            )
            if connection.execute(consulta).first() is None:
                connection.execute(alertas.insert().values(
                    ID_Usuario=id_usuario,
                    IATA_Origem=origem,
                    IATA_Destino=destino,
                    Mes_Viagem_Ou_Data=data,
                    Preco_Alvo=preco_alvo,
                ))
                print(f"Alerta de teste inserido: {descricao}.")
            else:
                print(f"Alerta de teste já existe: {descricao}.")

    print("\n🎉 Banco de dados populado com sucesso!")


if __name__ == "__main__":
    popular()
