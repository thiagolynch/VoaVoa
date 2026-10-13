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
    UniqueConstraint,
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

# "Alertas" = monitoramentos de rota. Apesar do nome (histórico), não exige
# mais preço-alvo: Preco_Alvo fica nula e serve só para quem ainda quer usar
# a ideia antiga. IATA_Origem guarda uma ou mais origens separadas por
# vírgula, sempre em ordem alfabética (ex.: "GIG,SDU") — por isso não tem
# mais FK para Destinos nem tamanho fixo de 3 caracteres.
alertas = Table(
    "Alertas",
    metadata,
    Column("ID_Alerta", Integer, primary_key=True, autoincrement=True),
    Column("ID_Usuario", Integer, ForeignKey("Usuarios.ID"), nullable=False),
    Column("IATA_Origem", String(64), nullable=False),
    Column("IATA_Destino", String(3), ForeignKey("Destinos.IATA"), nullable=False),
    Column("Mes_Viagem_Ou_Data", String, nullable=False),
    Column("Preco_Alvo", Float),
    Column("Preco_Atual", Float),
    Column("Ultima_Verificacao", String),
    Column("Confirmado", Integer, nullable=False, server_default="1"),
    Column("Criado_Em", String),
    Column("Data_Inicio_Janela", String),
    Column("Data_Fim_Janela", String),
    Column("Duracao_Min_Noites", Integer),
    Column("ID_Rota_Coleta", Integer, ForeignKey("Rotas_Coleta.ID_Rota", ondelete="SET NULL")),
)

# Mantida por compatibilidade com o histórico antigo (um alerta = uma rota).
# Dados novos vão para Cotacoes, ligados a Rotas_Coleta.
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

conversas_bot = Table(
    "Conversas_Bot",
    metadata,
    Column("Telefone", String, primary_key=True),
    Column("Estado", String, nullable=False),
    Column("Dados", String),
    Column("Atualizado_Em", String, nullable=False),
)

# Uma rota de coleta é compartilhada por todos os monitoramentos que pedem a
# mesma combinação de origens + destino + datas: a varredura diária consulta
# a SerpApi uma vez por rota, não uma vez por pessoa.
rotas_coleta = Table(
    "Rotas_Coleta",
    metadata,
    Column("ID_Rota", Integer, primary_key=True, autoincrement=True),
    Column("Origens", String(64), nullable=False),
    Column("IATA_Destino", String(3), ForeignKey("Destinos.IATA"), nullable=False),
    Column("Data_Ida", String, nullable=False),
    Column("Data_Volta", String),
    Column("Criado_Em", String, nullable=False),
    UniqueConstraint("Origens", "IATA_Destino", "Data_Ida", "Data_Volta", name="uq_rota_coleta"),
)

# Cada linha é um preço observado para uma rota, num dia. "Fonte" distingue
# o ponto coletado pela nossa varredura diária do histórico que o próprio
# Google devolve numa consulta (preenche os ~60 dias anteriores de uma vez).
cotacoes = Table(
    "Cotacoes",
    metadata,
    Column("ID_Cotacao", Integer, primary_key=True, autoincrement=True),
    Column("ID_Rota", Integer, ForeignKey("Rotas_Coleta.ID_Rota", ondelete="CASCADE"), nullable=False),
    Column("Coletado_Em", String, nullable=False),
    Column("Data_Referencia", String, nullable=False),  # AAAA-MM-DD, para agrupar por dia
    Column("Preco", Float, nullable=False),
    Column("Aeroporto_Saida", String(3)),
    Column("Companhia", String),
    Column("Escalas", Integer),
    Column("Duracao_Min", Integer),
    Column("Nivel_Google", String),
    Column("Faixa_Tipica_Min", Float),
    Column("Faixa_Tipica_Max", Float),
    Column("Fonte", String, nullable=False),
    UniqueConstraint("ID_Rota", "Data_Referencia", "Fonte", name="uq_cotacao_dia"),
)
Index("idx_cotacoes_rota_data", cotacoes.c.ID_Rota, cotacoes.c.Data_Referencia)

# Registro de cada WhatsApp enviado, para não repetir o mesmo aviso no
# mesmo dia e para auditar o que foi mandado.
notificacoes = Table(
    "Notificacoes",
    metadata,
    Column("ID_Notificacao", Integer, primary_key=True, autoincrement=True),
    Column("ID_Alerta", Integer, ForeignKey("Alertas.ID_Alerta", ondelete="CASCADE"), nullable=False),
    Column("Enviado_Em", String, nullable=False),
    Column("Motivo", String, nullable=False),  # novo_minimo | abaixo_media | ficou_barato | resumo_semanal
    Column("Preco", Float),
)
Index("idx_notificacoes_alerta_motivo_data", notificacoes.c.ID_Alerta, notificacoes.c.Motivo)


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
