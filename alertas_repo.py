# -*- coding: utf-8 -*-
"""
alertas_repo.py
Regras de negócio compartilhadas entre as superfícies que criam usuários e
alertas: dashboard.py (painel admin), cadastro.py (formulário público) e
whatsapp_bot.py (bot de WhatsApp).
"""
import os
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text

from aeroportos import AEROPORTOS
from database import alertas, usuarios

TELEFONE_RE = re.compile(r"\+\d{8,15}")
IATAS_VALIDOS = {iata for iata, _, _ in AEROPORTOS}


class LimiteDeAlertasAtingido(Exception):
    pass


def telefone_valido(telefone: str) -> bool:
    return bool(TELEFONE_RE.fullmatch((telefone or "").strip()))


def rota_valida(origem: str, destino: str) -> bool:
    origem, destino = (origem or "").upper(), (destino or "").upper()
    return origem != destino and origem in IATAS_VALIDOS and destino in IATAS_VALIDOS


def normalizar_data(valor: str) -> str:
    """Aceita AAAA-MM (usa o dia 15) ou AAAA-MM-DD."""
    return valor if len(valor) == 10 else f"{valor}-15"


def obter_ou_criar_usuario(engine, nome: str, telefone: str) -> int:
    nome, telefone = nome.strip(), telefone.strip()
    with engine.begin() as connection:
        id_existente = connection.execute(
            select(usuarios.c.ID).where(usuarios.c.Telefone_WhatsApp == telefone)
        ).scalar()
        if id_existente is not None:
            return id_existente
        resultado = connection.execute(
            usuarios.insert().values(Nome=nome, Telefone_WhatsApp=telefone, Opt_in=1)
        )
        return resultado.inserted_primary_key[0]


def contar_alertas_ativos(engine) -> int:
    with engine.connect() as connection:
        return len(connection.execute(select(alertas.c.ID_Alerta)).all())


def limite_atingido(engine, quantidade: int = 1) -> bool:
    maximo = int(os.getenv("MAX_ALERTAS_ATIVOS", "30"))
    return contar_alertas_ativos(engine) + quantidade > maximo


def janela_valida(data_inicio: date, data_fim: date) -> bool:
    maximo_dias = int(os.getenv("JANELA_MAX_DIAS", "30"))
    dias = (data_fim - data_inicio).days
    return 0 < dias <= maximo_dias


def criar_alerta(engine, id_usuario: int, origem: str, destino: str,
                  data_viagem: str, preco_alvo: float, confirmado: bool,
                  data_inicio: str | None = None, data_fim: str | None = None,
                  duracao_min_noites: int | None = None) -> int:
    if limite_atingido(engine):
        raise LimiteDeAlertasAtingido(
            "Limite de alertas ativos atingido no momento. Tente novamente mais tarde."
        )
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with engine.begin() as connection:
        resultado = connection.execute(alertas.insert().values(
            ID_Usuario=id_usuario,
            IATA_Origem=origem.upper(),
            IATA_Destino=destino.upper(),
            Mes_Viagem_Ou_Data=data_viagem,
            Preco_Alvo=preco_alvo,
            Confirmado=1 if confirmado else 0,
            Criado_Em=agora,
            Data_Inicio_Janela=data_inicio,
            Data_Fim_Janela=data_fim,
            Duracao_Min_Noites=duracao_min_noites,
        ))
        return resultado.inserted_primary_key[0]


def criar_alertas_em_lote(engine, id_usuario: int, origem: str, destinos: list[str],
                           data_viagem: str, preco_alvo: float, confirmado: bool,
                           data_inicio: str | None = None, data_fim: str | None = None,
                           duracao_min_noites: int | None = None) -> list[int]:
    """Cria um alerta por destino da lista, tudo ou nada (se o lote estourar
    o limite de alertas ativos, nenhum é criado)."""
    destinos_validos = [d.upper() for d in destinos if rota_valida(origem, d)]
    if not destinos_validos:
        raise ValueError("Nenhum destino válido informado.")
    if limite_atingido(engine, quantidade=len(destinos_validos)):
        raise LimiteDeAlertasAtingido(
            "Limite de alertas ativos atingido no momento. Tente novamente mais tarde."
        )
    return [
        criar_alerta(
            engine, id_usuario, origem, destino, data_viagem, preco_alvo, confirmado,
            data_inicio=data_inicio, data_fim=data_fim, duracao_min_noites=duracao_min_noites,
        )
        for destino in destinos_validos
    ]


def confirmar_alertas_pendentes(engine, telefone: str) -> list[int]:
    with engine.begin() as connection:
        ids = connection.execute(text("""
            SELECT a."ID_Alerta" FROM "Alertas" a
            JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
            WHERE u."Telefone_WhatsApp" = :telefone AND a."Confirmado" = 0
        """), {"telefone": telefone}).scalars().all()
        if ids:
            connection.execute(
                alertas.update().where(alertas.c.ID_Alerta.in_(ids)).values(Confirmado=1)
            )
        return list(ids)


def limpar_alertas_nao_confirmados(engine, horas: int = 48) -> int:
    """Apaga pedidos do formulário público que nunca foram confirmados por
    WhatsApp (Criado_Em antigo o bastante). Alertas sem Criado_Em (de antes
    desta versão) são tratados como já confirmados e não entram aqui."""
    limite = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(timespec="seconds")
    with engine.begin() as connection:
        resultado = connection.execute(text("""
            DELETE FROM "Alertas"
            WHERE "Confirmado" = 0 AND "Criado_Em" IS NOT NULL AND "Criado_Em" < :limite
        """), {"limite": limite})
        return resultado.rowcount or 0
