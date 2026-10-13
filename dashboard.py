import os
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text

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


def formatar_reais(valor):
    return f"R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def carregar_alertas_ativos():
    with obter_engine().connect() as connection:
        return connection.execute(text("""
            SELECT a."ID_Alerta", a."ID_Usuario", u."Nome" AS "Nome_Usuario",
                   a."IATA_Origem", a."IATA_Destino", a."Mes_Viagem_Ou_Data",
                   a."Preco_Alvo", a."Preco_Atual", a."Ultima_Verificacao",
                   a."Data_Inicio_Janela", a."Data_Fim_Janela", a."Duracao_Min_Noites",
                   o."Nome_Cidade" AS "Cidade_Origem", d."Nome_Cidade" AS "Cidade_Destino"
            FROM "Alertas" a
            JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
            JOIN "Destinos" o ON a."IATA_Origem" = o."IATA"
            JOIN "Destinos" d ON a."IATA_Destino" = d."IATA"
            WHERE u."Opt_in" = 1 AND a."Confirmado" = 1
            ORDER BY a."ID_Alerta" DESC
        """)).mappings().all()


def carregar_historico_30_dias(id_alerta):
    limite = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    with obter_engine().connect() as connection:
        linhas = connection.execute(text("""
            SELECT "Data_Verificacao", "Preco_Encontrado"
            FROM "Historico_Precos"
            WHERE "ID_Alerta" = :id_alerta AND "Data_Verificacao" >= :limite
            ORDER BY "Data_Verificacao"
        """), {"id_alerta": id_alerta, "limite": limite}).mappings().all()
    return pd.DataFrame(
        [(datetime.fromisoformat(linha["Data_Verificacao"]), linha["Preco_Encontrado"])
         for linha in linhas],
        columns=["Data", "Preço (R$)"],
    )


def aba_monitoramento():
    st.subheader("Monitoramento VIP")
    alertas = carregar_alertas_ativos()
    if not alertas:
        st.info("Nenhum alerta ativo. Cadastre um usuário e um alerta na aba Gestão do Sistema.")
        return

    for alerta in alertas:
        rota = f"{alerta['IATA_Origem']} → {alerta['IATA_Destino']}"
        st.markdown(f"#### {rota} · {alerta['Nome_Usuario']}")
        if alerta["Data_Fim_Janela"] and alerta["Data_Fim_Janela"] != alerta["Data_Inicio_Janela"]:
            viagem = (
                f"{alerta['Data_Inicio_Janela']} a {alerta['Data_Fim_Janela']} "
                f"({alerta['Duracao_Min_Noites']}+ noites)"
            )
        else:
            viagem = alerta["Mes_Viagem_Ou_Data"]
        st.caption(
            f"{alerta['Cidade_Origem']} para {alerta['Cidade_Destino']} · "
            f"Viagem: {viagem} · "
            f"Meta: {formatar_reais(alerta['Preco_Alvo'])}"
        )

        historico = carregar_historico_30_dias(alerta["ID_Alerta"])
        metricas = st.columns(3)
        if historico.empty:
            for coluna, rotulo in zip(metricas, ("Maior preço · 30 dias", "Menor preço · 30 dias", "Preço médio · 30 dias")):
                coluna.metric(rotulo, "—")
        else:
            metricas[0].metric("Maior preço · 30 dias", formatar_reais(historico["Preço (R$)"].max()))
            metricas[1].metric("Menor preço · 30 dias", formatar_reais(historico["Preço (R$)"].min()))
            metricas[2].metric("Preço médio · 30 dias", formatar_reais(historico["Preço (R$)"].mean()))

        preco_atual = alerta["Preco_Atual"]
        if preco_atual is not None and preco_atual <= alerta["Preco_Alvo"]:
            st.success(f"Abaixo da meta: {formatar_reais(preco_atual)}")
        elif preco_atual is not None:
            st.caption(f"Preço atual: {formatar_reais(preco_atual)}")
        else:
            st.caption("Aguardando a primeira verificação de preço.")

        figura = px.line(
            historico,
            x="Data",
            y="Preço (R$)",
            markers=True,
            labels={"Data": "Verificação", "Preço (R$)": "Preço (R$)"},
        )
        figura.update_layout(
            height=300,
            margin=dict(l=8, r=8, t=16, b=8),
            hovermode="x unified",
        )
        figura.update_traces(line_color="#0f766e", marker_color="#0f766e")
        if historico.empty:
            st.info("Ainda não há registros de preço nos últimos 30 dias.")
            figura.add_annotation(text="Sem histórico", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        st.plotly_chart(figura, use_container_width=True, key=f"historico_{alerta['ID_Alerta']}")
        st.divider()


def cadastrar_usuario():
    with st.form("form_usuario", clear_on_submit=True):
        st.markdown("#### Novo usuário")
        nome = st.text_input("Nome", placeholder="Nome completo")
        telefone = st.text_input("Telefone com código do país", placeholder="+5511999998888")
        enviado = st.form_submit_button("Cadastrar usuário", type="primary", use_container_width=True)

    if enviado:
        nome = nome.strip()
        telefone = telefone.strip()
        if not nome:
            st.error("Informe o nome do usuário.")
        elif not telefone_valido(telefone):
            st.error("Use o telefone internacional com + e DDI, por exemplo +5511999998888.")
        else:
            obter_ou_criar_usuario(obter_engine(), nome, telefone)
            st.success("Usuário cadastrado (ou já existia com esse telefone).")
            st.rerun()


def cadastrar_alerta():
    with obter_engine().connect() as connection:
        usuarios = connection.execute(text(
            'SELECT "ID", "Nome" FROM "Usuarios" ORDER BY "Nome"'
        )).mappings().all()

    st.markdown("#### Novo alerta")
    if not usuarios:
        st.info("Cadastre um usuário antes de criar um alerta.")
        return

    ids_usuarios = [usuario["ID"] for usuario in usuarios]
    aeroportos = [aeroporto[0] for aeroporto in AEROPORTOS]
    flexivel = st.checkbox("Data flexível (período em vez de uma data única)", key="flex_dashboard")

    with st.form("form_alerta", clear_on_submit=True):
        id_usuario = st.selectbox(
            "Usuário",
            ids_usuarios,
            format_func=lambda valor: next(u["Nome"] for u in usuarios if u["ID"] == valor),
        )
        origem = st.selectbox("Origem", aeroportos, format_func=formatar_aeroporto)
        destinos = st.multiselect(
            "Destino(s)", aeroportos, default=["MIA"], format_func=formatar_aeroporto
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
        if not destinos:
            st.error("Selecione pelo menos um destino.")
        elif origem in destinos:
            st.error("Origem e destino precisam ser diferentes.")
        elif flexivel and not janela_valida(data_inicio, data_fim):
            st.error("Esse período não é válido ou é grande demais.")
        else:
            try:
                ids = criar_alertas_em_lote(
                    obter_engine(), id_usuario, origem, destinos,
                    (data_viagem or data_inicio).isoformat(), preco_alvo, confirmado=True,
                    data_inicio=data_inicio.isoformat() if flexivel else None,
                    data_fim=data_fim.isoformat() if flexivel else None,
                    duracao_min_noites=int(duracao_min_noites) if flexivel else None,
                )
            except (LimiteDeAlertasAtingido, ValueError) as erro:
                st.error(str(erro))
            else:
                st.success(f"{len(ids)} alerta(s) criado(s).")
                st.rerun()


def aba_gestao():
    st.subheader("Gestão do Sistema")
    coluna_usuario, coluna_alerta = st.columns(2, gap="large")
    with coluna_usuario:
        cadastrar_usuario()
    with coluna_alerta:
        cadastrar_alerta()


st.set_page_config(page_title="VOAVOA · Painel", page_icon="✈️", layout="wide")
st.markdown("""
<style>
.block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem; }
[data-testid="stMetric"] { border: 1px solid rgba(128, 128, 128, .22); padding: 14px; border-radius: 8px; }
div[data-testid="stForm"] { border: 1px solid rgba(128, 128, 128, .22); border-radius: 8px; padding: 1rem; }
</style>
""", unsafe_allow_html=True)

inicializar_banco()
st.title("VOAVOA")
st.caption("Preços de voos e alertas em um só lugar")
aba_vip, aba_sistema = st.tabs(["Monitoramento VIP", "Gestão do Sistema"])
with aba_vip:
    aba_monitoramento()
with aba_sistema:
    aba_gestao()