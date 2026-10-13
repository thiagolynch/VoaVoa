# -*- coding: utf-8 -*-
"""
cadastro.py
Formulário público de autoatendimento: qualquer visitante cria o próprio
alerta de preço. Diferente de dashboard.py (privado), este app não tem
autenticação nem mostra dados de outros usuários — só recebe o pedido.

O alerta nasce não confirmado (Confirmado=0): o bot de WhatsApp
(whatsapp_bot.py) manda uma mensagem de confirmação pro número informado, e
o alerta só fica ativo quando a própria pessoa responde "CONFIRMAR" pelo
WhatsApp dela. Isso evita que alguém cadastre o número de outra pessoa.
"""
import os
from datetime import date, timedelta

import streamlit as st

from aeroportos import AEROPORTOS
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


st.set_page_config(page_title="VOAVOA · Cadastrar alerta", page_icon="✈️", layout="centered")
st.markdown("""
<style>
.block-container { max-width: 640px; padding-top: 2.5rem; padding-bottom: 3rem; }
div[data-testid="stForm"] { border: 1px solid rgba(128, 128, 128, .22); border-radius: 8px; padding: 1.2rem; }
</style>
""", unsafe_allow_html=True)

inicializar_banco()
st.title("Criar alerta de preço")
st.caption("Avisamos no seu WhatsApp quando o preço da sua rota cair até o valor que você escolher.")

aeroportos = [aeroporto[0] for aeroporto in AEROPORTOS]
destino_padrao = (st.query_params.get("destino") or "").upper()

flexivel = st.checkbox("Data flexível (período em vez de uma data única)")

with st.form("form_cadastro"):
    nome = st.text_input("Seu nome", placeholder="Nome completo")
    telefone = st.text_input("Seu WhatsApp (com código do país)", placeholder="+5511999998888")
    origem = st.selectbox(
        "Origem", aeroportos, index=indice_param(aeroportos, "origem", "GRU"),
        format_func=formatar_aeroporto,
    )
    destinos = st.multiselect(
        "Destino(s)", aeroportos,
        default=[destino_padrao] if destino_padrao in aeroportos else ["MIA"],
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

    preco_alvo = st.number_input("Preço alvo (R$)", min_value=1.0, value=1000.0, step=50.0)
    enviado = st.form_submit_button("Criar alerta", type="primary", use_container_width=True)

if enviado:
    nome, telefone = nome.strip(), telefone.strip()
    if not nome:
        st.error("Informe seu nome.")
    elif not telefone_valido(telefone):
        st.error("Use o telefone internacional com + e DDI, por exemplo +5511999998888.")
    elif not destinos:
        st.error("Selecione pelo menos um destino.")
    elif origem in destinos:
        st.error("Origem e destino precisam ser diferentes.")
    elif flexivel and not janela_valida(data_inicio, data_fim):
        st.error("Esse período não é válido ou é grande demais.")
    else:
        engine = obter_engine()
        try:
            id_usuario = obter_ou_criar_usuario(engine, nome, telefone)
            ids = criar_alertas_em_lote(
                engine, id_usuario, origem, destinos,
                (data_viagem or data_inicio).isoformat(), preco_alvo, confirmado=False,
                data_inicio=data_inicio.isoformat() if flexivel else None,
                data_fim=data_fim.isoformat() if flexivel else None,
                duracao_min_noites=int(duracao_min_noites) if flexivel else None,
            )
        except (LimiteDeAlertasAtingido, ValueError) as erro:
            st.error(str(erro))
        else:
            destinos_fmt = ", ".join(destinos)
            preco_fmt = f"R$ {preco_alvo:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
            periodo = (
                f"entre {data_inicio.isoformat()} e {data_fim.isoformat()}, {duracao_min_noites}+ noites"
                if flexivel else data_viagem.isoformat()
            )
            if whatsapp_configurado():
                enviar_alerta_whatsapp(
                    telefone,
                    f"✈️ *VOAVOA*\n\nRecebemos seu pedido de alerta {origem} → {destinos_fmt} "
                    f"até {preco_fmt}.\nPeríodo: {periodo}"
                    "\n\nResponda *CONFIRMAR* nesta conversa para ativar o(s) alerta(s).",
                )
            st.success(
                f"Pedido recebido ({len(ids)} alerta(s))! Confira seu WhatsApp: mandamos um pedido de "
                "confirmação. O(s) alerta(s) só ficam ativos depois que você responder CONFIRMAR por lá."
            )
