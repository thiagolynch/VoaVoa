from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aeroportos import AEROPORTOS, UFS_BRASIL
from database import destinos, get_engine, metadata


def migrar_colunas_alertas(engine):
    """Alertas criados antes desta versão não têm as colunas novas, e a
    coluna de origem precisa deixar de ter FK/tamanho fixo para caber mais
    de um aeroporto (ex.: "GIG,SDU")."""
    colunas = {c["name"] for c in inspect(engine).get_columns("Alertas")}
    comandos = {
        "Confirmado": 'ALTER TABLE "Alertas" ADD COLUMN "Confirmado" INTEGER NOT NULL DEFAULT 1',
        "Criado_Em": 'ALTER TABLE "Alertas" ADD COLUMN "Criado_Em" VARCHAR',
        "Data_Inicio_Janela": 'ALTER TABLE "Alertas" ADD COLUMN "Data_Inicio_Janela" VARCHAR',
        "Data_Fim_Janela": 'ALTER TABLE "Alertas" ADD COLUMN "Data_Fim_Janela" VARCHAR',
        "Duracao_Min_Noites": 'ALTER TABLE "Alertas" ADD COLUMN "Duracao_Min_Noites" INTEGER',
        "ID_Rota_Coleta": 'ALTER TABLE "Alertas" ADD COLUMN "ID_Rota_Coleta" INTEGER',
    }
    with engine.begin() as connection:
        for nome_coluna, comando in comandos.items():
            if nome_coluna not in colunas:
                connection.execute(text(comando))

        if engine.dialect.name == "postgresql":
            # Preco_Alvo não é mais obrigatório; IATA_Origem precisa caber
            # várias origens e não tem mais FK fixa para Destinos.
            connection.execute(text('ALTER TABLE "Alertas" ALTER COLUMN "Preco_Alvo" DROP NOT NULL'))
            connection.execute(text('ALTER TABLE "Alertas" ALTER COLUMN "IATA_Origem" TYPE VARCHAR(64)'))
            # O nome gerado pelo PostgreSQL preserva maiúsculas (por exemplo,
            # Alertas_IATA_Origem_fkey). Localizar pela coluna evita depender
            # da capitalização ou de nomes gerados em versões anteriores.
            for fk in inspect(connection).get_foreign_keys("Alertas"):
                if fk["constrained_columns"] == ["IATA_Origem"]:
                    nome = connection.dialect.identifier_preparer.quote(fk["name"])
                    connection.execute(text(f'ALTER TABLE "Alertas" DROP CONSTRAINT {nome}'))


def setup_database(engine=None):
    engine = engine or get_engine()
    inspetor_antes = inspect(engine)
    tinha_alertas = inspetor_antes.has_table("Alertas")

    metadata.create_all(engine)
    if tinha_alertas:
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
