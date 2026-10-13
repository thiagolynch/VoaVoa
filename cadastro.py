# -*- coding: utf-8 -*-
"""
cadastro.py
Formulário público de autoatendimento: qualquer visitante cria o próprio
monitoramento de preço. Diferente de dashboard.py (privado), este app não
tem autenticação nem mostra dados de outros usuários — só recebe o pedido.

Não existe mais "preço-alvo": o monitoramento acompanha a rota desde o dia
do cadastro e avisa no WhatsApp quando o preço cai de verdade (novo mínimo,
bem abaixo da média, ou o Google marcar como "preço baixo").

O monitoramento nasce não confirmado (Confirmado=0): o bot de WhatsApp
(whatsapp_bot.py) manda uma mensagem de confirmação pro número informado, e
só fica ativo quando a própria pessoa responde "CONFIRMAR" pelo WhatsApp
dela. Isso evita que alguém cadastre o número de outra pessoa.
"""
import os
from datetime import date, timedelta

import streamlit as st

from aeroportos import AEROPORTOS, GRUPOS_ORIGEM_MULTI
from alertas_repo import (
    LimiteDeAlertasAtingido,
    criar_alertas_em_lote,
    janela_valida,
    obter_ou_criar_usuario,
    telefone_valido,
)
from database import get_engine
from setup_db import setup_database
from whatsapp import enviar_alerta_whatsapp, whatsapp_configurado


@st.cache_resource
def obter_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        try:
            database_url = st.secrets["DATABASE_URL"]
        except Exception:
            database_url = None
    return get_engine(database_url)


@st.cache_resource
def inicializar_banco():
    setup_database(obter_engine())


def formatar_aeroporto(iata):
    _, cidade, regiao = next(aeroporto for aeroporto in AEROPORTOS if aeroporto[0] == iata)
    return f"{cidade} - {regiao} ({iata})"


def indice_param(aeroportos, nome_param, padrao):
    valor = (st.query_params.get(nome_param) or "").upper()
    return aeroportos.index(valor) if valor in aeroportos else aeroportos.index(padrao)


# Opções de origem: cada aeroporto individual + atalhos de grupo para
# cidades com mais de um aeroporto (ex.: "Rio de Janeiro (GIG+SDU)"),
# que selecionam os dois de uma vez.
_opcoes_origem_individuais = [(iata, formatar_aeroporto(iata), (iata,)) for iata, _, _ in AEROPORTOS]
OPCOES_ORIGEM = GRUPOS_ORIGEM_MULTI + _opcoes_origem_individuais
ROTULO_ORIGEM = {chave: rotulo for chave, rotulo, _ in OPCOES_ORIGEM}
IATAS_ORIGEM = {chave: iatas for chave, rotulo, iatas in OPCOES_ORIGEM}


def origens_selecionadas(chaves_escolhidas: list[str]) -> list[str]:
    vistos, resultado = set(), []
    for chave in chaves_escolhidas:
        for iata in IATAS_ORIGEM.get(chave, ()):
            if iata not in vistos:
                vistos.add(iata)
                resultado.append(iata)
    return resultado


st.set_page_config(page_title="VOAVOA · Cadastrar acompanhamento", page_icon="✈️", layout="centered")
st.markdown("""
<style>
.block-container { max-width: 640px; padding-top: 2.5rem; padding-bottom: 3rem; }
div[data-testid="stForm"] { border: 1px solid rgba(128, 128, 128, .22); border-radius: 8px; padding: 1.2rem; }
</style>
""", unsafe_allow_html=True)

inicializar_banco()
st.title("Acompanhar preço de uma rota")
st.caption(
    "A partir de hoje, acompanhamos o preço da sua rota todo santo dia e avisamos no seu "
    "WhatsApp quando ele cair de verdade — sem você precisar dizer até quanto paga."
)

destino_padrao = (st.query_params.get("destino") or "").upper()
destinos_opcoes = [aeroporto[0] for aeroporto in AEROPORTOS]

flexivel = st.checkbox("Data flexível (período em vez de uma data única)")

with st.form("form_cadastro"):
    nome = st.text_input("Seu nome", placeholder="Nome completo")
    telefone = st.text_input("Seu WhatsApp (com código do país)", placeholder="+5511999998888")
    origens_chaves = st.multiselect(
        "De onde você pode sair",
        [chave for chave, _, _ in OPCOES_ORIGEM],
        default=["GRU"] if "GRU" in ROTULO_ORIGEM else [],
        format_func=lambda chave: ROTULO_ORIGEM[chave],
        help="No Rio e em São Paulo você pode escolher o atalho com os dois aeroportos de uma vez.",
    )
    destinos = st.multiselect(
        "Destino(s)", destinos_opcoes,
        default=[destino_padrao] if destino_padrao in destinos_opcoes else ["MIA"],
        format_func=formatar_aeroporto,
    )

    if not flexivel:
        data_viagem = st.date_input("Data da viagem", value=date.today() + timedelta(days=30))
        data_inicio = data_fim = duracao_min_noites = None
    else:
        coluna_inicio, coluna_fim, coluna_noites = st.columns(3)
        data_inicio = coluna_inicio.date_input("Início do período", value=date.today() + timedelta(days=30))
        data_fim = coluna_fim.date_input("Fim do período", value=date.today() + timedelta(days=40))
        duracao_min_noites = coluna_noites.number_input("Noites mínimas", min_value=1, value=5, step=1)
        data_viagem = None

    enviado = st.form_submit_button("Começar a acompanhar", type="primary", use_container_width=True)

if enviado:
    nome, telefone = nome.strip(), telefone.strip()
    origens = origens_selecionadas(origens_chaves)
    if not nome:
        st.error("Informe seu nome.")
    elif not telefone_valido(telefone):
        st.error("Use o telefone internacional com + e DDI, por exemplo +5511999998888.")
    elif not origens:
        st.error("Selecione pelo menos uma origem.")
    elif not destinos:
        st.error("Selecione pelo menos um destino.")
    elif any(destino in origens for destino in destinos):
        st.error("Origem e destino precisam ser diferentes.")
    elif flexivel and not janela_valida(data_inicio, data_fim):
        st.error("Esse período não é válido ou é grande demais.")
    else:
        engine = obter_engine()
        try:
            id_usuario = obter_ou_criar_usuario(engine, nome, telefone)
            ids = criar_alertas_em_lote(
                engine, id_usuario, origens, destinos,
                (data_viagem or data_inicio).isoformat(), confirmado=False,
                data_inicio=data_inicio.isoformat() if flexivel else None,
                data_fim=data_fim.isoformat() if flexivel else None,
                duracao_min_noites=int(duracao_min_noites) if flexivel else None,
            )
        except (LimiteDeAlertasAtingido, ValueError) as erro:
            st.error(str(erro))
        else:
            origens_fmt = "/".join(origens)
            destinos_fmt = ", ".join(destinos)
            periodo = (
                f"entre {data_inicio.isoformat()} e {data_fim.isoformat()}, {duracao_min_noites}+ noites"
                if flexivel else data_viagem.isoformat()
            )
            if whatsapp_configurado():
                enviar_alerta_whatsapp(
                    telefone,
                    f"✈️ *VOAVOA*\n\nRecebemos seu pedido: acompanhar {origens_fmt} → {destinos_fmt}.\n"
                    f"Período: {periodo}\n\n"
                    "Responda *CONFIRMAR* nesta conversa para ativar o acompanhamento. "
                    "Em algumas horas você já recebe no WhatsApp a confirmação e, dali em diante, "
                    "um aviso sempre que o preço cair de verdade.",
                )
            st.success(
                f"Pedido recebido ({len(ids)} rota(s))! Confira seu WhatsApp: mandamos um pedido de "
                "confirmação. O acompanhamento só começa depois que você responder CONFIRMAR por lá."
            )
