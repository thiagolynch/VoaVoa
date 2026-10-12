from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from aeroportos import AEROPORTOS, UFS_BRASIL
from database import destinos, get_engine, metadata


def setup_database(engine=None):
    engine = engine or get_engine()
    metadata.create_all(engine)

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