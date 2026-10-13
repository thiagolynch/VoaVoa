from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aeroportos import AEROPORTOS, UFS_BRASIL
from database import destinos, get_engine, metadata


def migrar_colunas_alertas(engine):
    """Alertas criados antes desta versão não têm as colunas novas."""
    colunas = {c["name"] for c in inspect(engine).get_columns("Alertas")}
    comandos = {
        "Confirmado": 'ALTER TABLE "Alertas" ADD COLUMN "Confirmado" INTEGER NOT NULL DEFAULT 1',
        "Criado_Em": 'ALTER TABLE "Alertas" ADD COLUMN "Criado_Em" VARCHAR',
        "Data_Inicio_Janela": 'ALTER TABLE "Alertas" ADD COLUMN "Data_Inicio_Janela" VARCHAR',
        "Data_Fim_Janela": 'ALTER TABLE "Alertas" ADD COLUMN "Data_Fim_Janela" VARCHAR',
        "Duracao_Min_Noites": 'ALTER TABLE "Alertas" ADD COLUMN "Duracao_Min_Noites" INTEGER',
    }
    with engine.begin() as connection:
        for nome_coluna, comando in comandos.items():
            if nome_coluna not in colunas:
                connection.execute(text(comando))


def setup_database(engine=None):
    engine = engine or get_engine()
    metadata.create_all(engine)
    if inspect(engine).has_table("Alertas"):
        migrar_colunas_alertas(engine)

    registros_destinos = [
        {
            "IATA": iata,
            "Nome_Cidade": cidade,
            "Pais": "Brasil" if regiao in UFS_BRASIL else regiao,
        }
        for iata, cidade, regiao in AEROPORTOS
    ]
    if engine.dialect.name == "sqlite":
        comando = sqlite_insert(destinos).values(registros_destinos)
    else:
        comando = postgresql_insert(destinos).values(registros_destinos)
    comando = comando.on_conflict_do_nothing(index_elements=[destinos.c.IATA])

    with engine.begin() as connection:
        connection.execute(comando)

    print(f"Banco de dados configurado com sucesso ({engine.dialect.name}).")


if __name__ == "__main__":
    setup_database()