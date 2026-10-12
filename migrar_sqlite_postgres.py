import os

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from database import alertas, destinos, get_engine, historico_precos, usuarios
from setup_db import setup_database


TABELAS = (destinos, usuarios, alertas, historico_precos)
TAMANHO_LOTE = 500


def inserir_sem_sobrescrever(connection, table, rows):
    if not rows:
        return 0
    if connection.dialect.name == "sqlite":
        statement = sqlite_insert(table)
    else:
        statement = postgresql_insert(table)
    result = connection.execute(statement.values(rows).on_conflict_do_nothing())
    return result.rowcount


def migrar():
    database_url = os.getenv("DATABASE_URL")
    if not database_url or database_url.startswith("sqlite:"):
        raise RuntimeError("Configure DATABASE_URL com a URL PostgreSQL do Supabase no .env.")

    source_url = os.getenv("SQLITE_SOURCE_URL", "sqlite:///voavoa.db")
    source_engine = get_engine(source_url)
    target_engine = get_engine(database_url)

    setup_database(source_engine)
    setup_database(target_engine)

    with source_engine.connect() as source:
        for table in TABELAS:
            rows = source.execute(select(table)).mappings().all()
            copiados = 0
            for inicio in range(0, len(rows), TAMANHO_LOTE):
                lote = [dict(row) for row in rows[inicio:inicio + TAMANHO_LOTE]]
                with target_engine.begin() as target:
                    copiados += inserir_sem_sobrescrever(target, table, lote)
            print(f'{table.name}: {copiados} registro(s) copiado(s) de {len(rows)}.')

    if target_engine.dialect.name == "postgresql":
        with target_engine.begin() as target:
            for table_name, column_name in (
                ("Usuarios", "ID"),
                ("Alertas", "ID_Alerta"),
                ("Historico_Precos", "ID_Historico"),
            ):
                target.execute(text(f"""
                    SELECT setval(
                        pg_get_serial_sequence('"{table_name}"', '{column_name}'),
                        COALESCE(MAX("{column_name}"), 1),
                        MAX("{column_name}") IS NOT NULL
                    )
                    FROM "{table_name}"
                """))

    print("Migração concluída. O banco SQLite original não foi removido.")


if __name__ == "__main__":
    migrar()
