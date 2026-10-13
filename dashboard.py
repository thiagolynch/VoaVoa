import os
import re
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from aeroportos import AEROPORTOS, GRUPOS_ORIGEM_MULTI
from alertas_repo import LimiteDeAlertasAtingido, criar_alertas_em_lote, janela_valida, obter_ou_criar_usuario
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
            SELECT a."ID_Alerta", a."ID_Usuario", a."ID_Rota_Coleta", u."Nome" AS "Nome_Usuario",
                   a."IATA_Origem", a."IATA_Destino", a."Mes_Viagem_Ou_Data",
                   a."Preco_Atual", a."Ultima_Verificacao", a."Confirmado",
                   d."Nome_Cidade" AS "Cidade_Destino"
            FROM "Alertas" a
            JOIN "Usuarios" u ON u."ID" = a."ID_Usuario"
            JOIN "Destinos" d ON a."IATA_Destino" = d."IATA"
            WHERE u."Opt_in" = 1
            ORDER BY a."ID_Alerta" DESC
        """)).mappings().all()


def carregar_historico(alerta):
    """Prefere o histórico novo (Cotacoes, ligado pela Rota_Coleta — já tem
    o preço desde o início do acompanhamento); cai para o Historico_Precos
    antigo quando o alerta ainda não foi migrado."""
    with obter_engine().connect() as connection:
        if alerta["ID_Rota_Coleta"]:
            linhas = connection.execute(text("""
                SELECT "Data_Referencia" AS "Data", "Preco", "Nivel_Google"
                FROM "Cotacoes" WHERE "ID_Rota" = :r
                ORDER BY "Data_Referencia",
                         CASE "Fonte" WHEN 'coleta_diaria' THEN 0 ELSE 1 END
            """), {"r": alerta["ID_Rota_Coleta"]}).mappings().all()
            por_dia = {}
            for linha in linhas:
                por_dia.setdefault(linha["Data"], (linha["Preco"], linha["Nivel_Google"]))
            dados = [(dia, preco) for dia, (preco, _nivel) in sorted(por_dia.items())]
        else:
            linhas = connection.execute(text("""
                SELECT "Data_Verificacao", "Preco_Encontrado" FROM "Historico_Precos"
                WHERE "ID_Alerta" = :id ORDER BY "Data_Verificacao"
            """), {"id": alerta["ID_Alerta"]}).all()
            dados = [(d[:10], p) for d, p in linhas]
    return pd.DataFrame(dados, columns=["Data", "Preço (R$)"])


def aba_monitoramento():
    st.subheader("Acompanhamentos")
    alertas = carregar_alertas_ativos()
    if not alertas:
        st.info("Nenhum acompanhamento cadastrado. Crie um na aba Gestão do Sistema.")
        return

    for alerta in alertas:
        rota = f"{alerta['IATA_Origem']} → {alerta['IATA_Destino']}"
        status = "" if alerta["Confirmado"] else " · ⏳ aguardando confirmação no WhatsApp"
        st.markdown(f"#### {rota} · {alerta['Nome_Usuario']}{status}")
        st.caption(f"Destino: {alerta['Cidade_Destino']} · Viagem: {alerta['Mes_Viagem_Ou_Data']}")

        historico = carregar_historico(alerta)
        metricas = st.columns(4)
        if historico.empty:
            for coluna, rotulo in zip(metricas, ("Hoje", "Menor desde o início", "Média desde o início", "Maior desde o início")):
                coluna.metric(rotulo, "—")
        else:
            precos = historico["Preço (R$)"]
            metricas[0].metric("Hoje", formatar_reais(precos.iloc[-1]))
            metricas[1].metric("Menor desde o início", formatar_reais(precos.min()))
            metricas[2].metric("Média desde o início", formatar_reais(precos.mean()))
            metricas[3].metric("Maior desde o início", formatar_reais(precos.max()))

        figura = px.line(
            historico, x="Data", y="Preço (R$)", markers=True,
            labels={"Data": "Data", "Preço (R$)": "Preço (R$)"},
        )
        figura.update_layout(height=280, margin=dict(l=8, r=8, t=16, b=8), hovermode="x unified")
        figura.update_traces(line_color="#0f766e", marker_color="#0f766e")
        if historico.empty:
            st.info("Ainda não há preços coletados para essa rota.")
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
        elif not re.fullmatch(r"\+\d{8,15}", telefone):
            st.error("Use o telefone internacional com + e DDI, por exemplo +5511999998888.")
        else:
            try:
                with obter_engine().begin() as connection:
                    connection.execute(text(
                        'INSERT INTO "Usuarios" ("Nome", "Telefone_WhatsApp") '
                        'VALUES (:nome, :telefone)'
                    ), {"nome": nome, "telefone": telefone})
                st.success("Usuário cadastrado.")
                st.rerun()
            except IntegrityError:
                st.error("Esse telefone já está cadastrado.")


def cadastrar_alerta():
    with obter_engine().connect() as connection:
        usuarios = connection.execute(text(
            'SELECT "ID", "Nome" FROM "Usuarios" ORDER BY "Nome"'
        )).mappings().all()

    st.markdown("#### Novo acompanhamento")
    if not usuarios:
        st.info("Cadastre um usuário antes de criar um acompanhamento.")
        return

    ids_usuarios = [usuario["ID"] for usuario in usuarios]
    aeroportos = [aeroporto[0] for aeroporto in AEROPORTOS]
    opcoes_origem = GRUPOS_ORIGEM_MULTI + [(iata, formatar_aeroporto(iata), (iata,)) for iata in aeroportos]
    rotulo_origem = {chave: rotulo for chave, rotulo, _ in opcoes_origem}
    iatas_origem = {chave: iatas for chave, _, iatas in opcoes_origem}

    with st.form("form_alerta", clear_on_submit=True):
        id_usuario = st.selectbox(
            "Usuário", ids_usuarios,
            format_func=lambda valor: next(u["Nome"] for u in usuarios if u["ID"] == valor),
        )
        origem_chaves = st.multiselect(
            "Origem(ns)", [chave for chave, _, _ in opcoes_origem],
            default=["GRU"], format_func=lambda chave: rotulo_origem[chave],
        )
        destinos = st.multiselect("Destino(s)", aeroportos, default=["MIA"], format_func=formatar_aeroporto)
        data_viagem = st.date_input("Data da viagem", value=date.today() + timedelta(days=30))
        enviado = st.form_submit_button("Criar acompanhamento", type="primary", use_container_width=True)

    if enviado:
        origens = []
        for chave in origem_chaves:
            for iata in iatas_origem.get(chave, ()):
                if iata not in origens:
                    origens.append(iata)
        if not origens:
            st.error("Selecione pelo menos uma origem.")
        elif not destinos:
            st.error("Selecione pelo menos um destino.")
        elif any(destino in origens for destino in destinos):
            st.error("Origem e destino precisam ser diferentes.")
        else:
            try:
                ids = criar_alertas_em_lote(
                    obter_engine(), id_usuario, origens, destinos,
                    data_viagem.isoformat(), confirmado=True,
                )
            except (LimiteDeAlertasAtingido, ValueError) as erro:
                st.error(str(erro))
            else:
                st.success(f"{len(ids)} acompanhamento(s) criado(s).")
                st.rerun()


def aba_gestao():
    st.subheader("Gestão do Sistema")
    coluna_usuario, coluna_alerta = st.columns(2, gap="large")
    with coluna_usuario:
        cadastrar_usuario()
    with coluna_alerta:
        cadastrar_alerta()


def aba_analise():
    st.subheader("Análise de variação de preços")
    with obter_engine().connect() as connection:
        linhas = connection.execute(text("""
            SELECT r."ID_Rota", r."Origens", r."IATA_Destino", r."Data_Ida", r."Data_Volta",
                   c."Data_Referencia", c."Preco"
            FROM "Rotas_Coleta" r JOIN "Cotacoes" c ON c."ID_Rota" = r."ID_Rota"
            ORDER BY r."ID_Rota", c."Data_Referencia"
        """)).mappings().all()
    if not linhas:
        st.info("Ainda não há cotações coletadas para analisar.")
        return

    tabela = pd.DataFrame(linhas)
    tabela["Rota"] = tabela["Origens"] + " → " + tabela["IATA_Destino"]
    rota_escolhida = st.selectbox("Rota", sorted(tabela["Rota"].unique()))
    filtrada = tabela[tabela["Rota"] == rota_escolhida].sort_values("Data_Referencia")
    filtrada["Variação vs. dia anterior (%)"] = filtrada["Preco"].pct_change() * 100
    filtrada["Variação vs. início (%)"] = (filtrada["Preco"] / filtrada["Preco"].iloc[0] - 1) * 100
    filtrada["Média móvel 30d"] = filtrada["Preco"].rolling(30, min_periods=1).mean()

    st.dataframe(
        filtrada[["Data_Referencia", "Preco", "Variação vs. dia anterior (%)", "Variação vs. início (%)", "Média móvel 30d"]]
        .rename(columns={"Data_Referencia": "Data", "Preco": "Preço (R$)"}),
        use_container_width=True, hide_index=True,
    )
    st.download_button(
        "Baixar CSV da rota", filtrada.to_csv(index=False).encode("utf-8"),
        file_name=f"voavoa_{rota_escolhida.replace(' ', '')}.csv", mime="text/csv",
    )


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
st.caption("Preços de voos acompanhados dia a dia, em um só lugar")
aba_vip, aba_sistema, aba_dados = st.tabs(["Acompanhamentos", "Gestão do Sistema", "Análise"])
with aba_vip:
    aba_monitoramento()
with aba_sistema:
    aba_gestao()
with aba_dados:
    aba_analise()
