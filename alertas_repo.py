# -*- coding: utf-8 -*-
"""
alertas_repo.py
Regras de negócio compartilhadas entre as superfícies que criam usuários e
monitoramentos: dashboard.py (painel admin), cadastro.py (formulário
público) e whatsapp_bot.py (bot de WhatsApp).

Desde que o preço-alvo deixou de existir, um "alerta" é um monitoramento:
a pessoa escolhe de onde pode sair (uma ou mais origens), para onde quer ir
e quando, e passa a receber o histórico de preço a partir do dia do
cadastro — sem precisar dizer "até quanto pago".
"""
import os
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text

from aeroportos import AEROPORTOS
from database import alertas, rotas_coleta, usuarios

TELEFONE_RE = re.compile(r"\+\d{8,15}")
IATAS_VALIDOS = {iata for iata, _, _ in AEROPORTOS}


class LimiteDeAlertasAtingido(Exception):
    pass


def telefone_valido(telefone: str) -> bool:
    return bool(TELEFONE_RE.fullmatch((telefone or "").strip()))


def origens_normalizadas(origens) -> str:
    """Uma ou mais origens -> string canônica ordenada ("GIG,SDU"), para
    que o mesmo grupo de aeroportos sempre vire a mesma chave de rota."""
    if isinstance(origens, str):
        origens = origens.split(",")
    vistos, limpas = set(), []
    for item in origens:
        item = (item or "").strip().upper()
        if item and item not in vistos:
            vistos.add(item)
            limpas.append(item)
    return ",".join(sorted(limpas))


def origens_validas(origens) -> bool:
    lista = origens_normalizadas(origens).split(",") if origens else []
    return bool(lista) and all(iata in IATAS_VALIDOS for iata in lista)


def rota_valida(origem, destino: str) -> bool:
    origens = origens_normalizadas(origem).split(",") if origem else []
    destino = (destino or "").upper()
    return (
        bool(origens) and all(iata in IATAS_VALIDOS for iata in origens)
        and destino in IATAS_VALIDOS and destino not in origens
    )


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


def obter_ou_criar_rota_coleta(engine, origens: str, destino: str,
                                data_ida: str, data_volta: str | None) -> int:
    """Devolve o ID da Rota_Coleta para essa combinação exata de origens +
    destino + datas, criando-a se ainda não existir. Duas pessoas pedindo a
    mesma rota caem na mesma linha, e a varredura diária consulta uma vez só."""
    origens = origens_normalizadas(origens)
    destino = destino.upper()
    with engine.begin() as connection:
        id_existente = connection.execute(
            select(rotas_coleta.c.ID_Rota).where(
                rotas_coleta.c.Origens == origens,
                rotas_coleta.c.IATA_Destino == destino,
                rotas_coleta.c.Data_Ida == data_ida,
                rotas_coleta.c.Data_Volta == data_volta,
            )
        ).scalar()
        if id_existente is not None:
            return id_existente
        resultado = connection.execute(rotas_coleta.insert().values(
            Origens=origens,
            IATA_Destino=destino,
            Data_Ida=data_ida,
            Data_Volta=data_volta,
            Criado_Em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ))
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


def criar_alerta(engine, id_usuario: int, origem, destino: str,
                  data_viagem: str, confirmado: bool,
                  data_inicio: str | None = None, data_fim: str | None = None,
                  duracao_min_noites: int | None = None) -> int:
    """Cria um monitoramento. `origem` pode ser um IATA só ou uma lista/
    string com várias origens ("GIG,SDU"). Sem janela (data fixa), já liga
    o monitoramento à Rota_Coleta compartilhada; em modo janela, a rota é
    resolvida todo dia pela varredura (ver coleta_diaria.py)."""
    if limite_atingido(engine):
        raise LimiteDeAlertasAtingido(
            "Limite de alertas ativos atingido no momento. Tente novamente mais tarde."
        )
    origens = origens_normalizadas(origem)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    id_rota = None
    if not data_fim:  # data fixa, não-janela: a rota já é conhecida de cara
        id_rota = obter_ou_criar_rota_coleta(
            engine, origens, destino, data_viagem,
            (date.fromisoformat(data_viagem) + timedelta(days=duracao_min_noites)).isoformat()
            if duracao_min_noites else None,
        )
    with engine.begin() as connection:
        resultado = connection.execute(alertas.insert().values(
            ID_Usuario=id_usuario,
            IATA_Origem=origens,
            IATA_Destino=destino.upper(),
            Mes_Viagem_Ou_Data=data_viagem,
            Confirmado=1 if confirmado else 0,
            Criado_Em=agora,
            Data_Inicio_Janela=data_inicio,
            Data_Fim_Janela=data_fim,
            Duracao_Min_Noites=duracao_min_noites,
            ID_Rota_Coleta=id_rota,
        ))
        return resultado.inserted_primary_key[0]


def criar_alertas_em_lote(engine, id_usuario: int, origem, destinos: list[str],
                           data_viagem: str, confirmado: bool,
                           data_inicio: str | None = None, data_fim: str | None = None,
                           duracao_min_noites: int | None = None) -> list[int]:
    """Cria um monitoramento por destino da lista, tudo ou nada (se o lote
    estourar o limite de alertas ativos, nenhum é criado). Pedir o mesmo
    grupo de origens + destino + data de novo reaproveita o monitoramento
    em vez de duplicar."""
    destinos_validos = [d.upper() for d in destinos if rota_valida(origem, d)]
    if not destinos_validos:
        raise ValueError("Nenhum destino válido informado.")
    if limite_atingido(engine, quantidade=len(destinos_validos)):
        raise LimiteDeAlertasAtingido(
            "Limite de alertas ativos atingido no momento. Tente novamente mais tarde."
        )
    origens = origens_normalizadas(origem)
    ids = []
    for destino in destinos_validos:
        existente = monitoramento_existente(
            engine, id_usuario, origens, destino, data_viagem, data_inicio, data_fim
        )
        if existente is not None:
            ids.append(existente)
            continue
        ids.append(criar_alerta(
            engine, id_usuario, origens, destino, data_viagem, confirmado,
            data_inicio=data_inicio, data_fim=data_fim, duracao_min_noites=duracao_min_noites,
        ))
    return ids


def monitoramento_existente(engine, id_usuario: int, origens: str, destino: str,
                             data_viagem: str, data_inicio: str | None,
                             data_fim: str | None) -> int | None:
    """Evita duplicar quando a mesma pessoa manda o mesmo pedido de novo
    (ex.: reenviou o formulário por engano)."""
    with engine.connect() as connection:
        return connection.execute(select(alertas.c.ID_Alerta).where(
            alertas.c.ID_Usuario == id_usuario,
            alertas.c.IATA_Origem == origens_normalizadas(origens),
            alertas.c.IATA_Destino == destino.upper(),
            alertas.c.Mes_Viagem_Ou_Data == data_viagem,
            alertas.c.Data_Inicio_Janela == data_inicio,
            alertas.c.Data_Fim_Janela == data_fim,
        )).scalar()


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
