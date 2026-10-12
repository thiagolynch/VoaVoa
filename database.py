import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
)


load_dotenv(Path(__file__).resolve().parent / ".env")

metadata = MetaData()

usuarios = Table(
    "Usuarios",
    metadata,
    Column("ID", Integer, primary_key=True, autoincrement=True),
    Column("Nome", String, nullable=False),
    Column("Telefone_WhatsApp", String, nullable=False, unique=True),
    Column("Opt_in", Integer, nullable=False, server_default="1"),
)

destinos = Table(
    "Destinos",
    metadata,
    Column("IATA", String(3), primary_key=True),
    Column("Nome_Cidade", String, nullable=False),
    Column("Pais", String, nullable=False),
)

alertas = Table(
    "Alertas",
    metadata,
    Column("ID_Alerta", Integer, primary_key=True, autoincrement=True),
    Column("ID_Usuario", Integer, ForeignKey("Usuarios.ID"), nullable=False),
    Column("IATA_Origem", String(3), ForeignKey("Destinos.IATA"), nullable=False),
    Column("IATA_Destino", String(3), ForeignKey("Destinos.IATA"), nullable=False),
    Column("Mes_Viagem_Ou_Data", String, nullable=False),
    Column("Preco_Alvo", Float, nullable=False),
    Column("Preco_Atual", Float),
    Column("Ultima_Verificacao", String),
)

historico_precos = Table(
    "Historico_Precos",
    metadata,
    Column("ID_Historico", Integer, primary_key=True, autoincrement=True),
    Column("ID_Alerta", Integer, ForeignKey("Alertas.ID_Alerta", ondelete="CASCADE"), nullable=False),
    Column("Data_Verificacao", String, nullable=False),
    Column("Preco_Encontrado", Float, nullable=False),
)
Index(
    "idx_historico_precos_alerta_data",
    historico_precos.c.ID_Alerta,
    historico_precos.c.Data_Verificacao,
)


def normalizar_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


@lru_cache(maxsize=4)
def get_engine(database_url: str | None = None):
    url = normalizar_database_url(database_url or os.getenv("DATABASE_URL", "sqlite:///voavoa.db"))
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False, "timeout": 30}

    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def habilitar_chaves_estrangeiras(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
