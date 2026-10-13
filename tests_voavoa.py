# -*- coding: utf-8 -*-
"""
tests_voavoa.py
Testes do novo modelo sem preço-alvo: rotas compartilhadas, origens
múltiplas e regras de aviso. Usa SQLite em arquivo temporário e a SerpApi
mockada — nunca gasta cota real.

Uso:  pytest tests_voavoa.py -v
"""
import os
import sys
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    caminho = tmp_path / f"teste_{uuid.uuid4().hex}.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{caminho}")
    from database import get_engine
    get_engine.cache_clear()
    eng = get_engine(f"sqlite:///{caminho}")
    from setup_db import setup_database
    setup_database(eng)
    yield eng
    get_engine.cache_clear()


def resultado_mock(preco=2000.0, nivel="typical", historico=None, aeroporto_saida="GIG"):
    from google_flights import ResultadoBusca
    return ResultadoBusca(
        preco=preco, nivel=nivel, faixa_tipica=[preco * 0.85, preco * 1.15],
        historico=historico or [], companhia="LATAM", escalas=0, duracao_min=200,
        aeroporto_saida=aeroporto_saida, google_flights_url="https://google.com/travel/flights",
    )


# ─── origens múltiplas ──────────────────────────────────────────────────────

def test_origens_normalizadas_ordena_e_deduplica():
    from alertas_repo import origens_normalizadas
    assert origens_normalizadas(["SDU", "GIG", "GIG"]) == "GIG,SDU"
    assert origens_normalizadas("sdu,gig") == "GIG,SDU"


def test_criar_alerta_sem_preco_alvo_aceita_multi_origem(engine):
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario
    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990001")
    data = (date.today() + timedelta(days=40)).isoformat()
    ids = criar_alertas_em_lote(engine, id_usuario, ["GIG", "SDU"], ["MCZ"], data, confirmado=True)
    assert len(ids) == 1

    from sqlalchemy import text
    with engine.connect() as connection:
        linha = connection.execute(text(
            'SELECT "IATA_Origem", "Preco_Alvo", "ID_Rota_Coleta" FROM "Alertas" WHERE "ID_Alerta" = :id'
        ), {"id": ids[0]}).mappings().first()
    assert linha["IATA_Origem"] == "GIG,SDU"
    assert linha["Preco_Alvo"] is None
    assert linha["ID_Rota_Coleta"] is not None


def test_pedido_repetido_nao_duplica_monitoramento(engine):
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario
    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990002")
    data = (date.today() + timedelta(days=40)).isoformat()
    primeiros = criar_alertas_em_lote(engine, id_usuario, "GIG", ["MCZ", "REC"], data, confirmado=True)
    repetidos = criar_alertas_em_lote(engine, id_usuario, "GIG", ["MCZ", "REC"], data, confirmado=True)
    assert sorted(primeiros) == sorted(repetidos)

    from sqlalchemy import text
    with engine.connect() as connection:
        total = connection.execute(text('SELECT COUNT(*) FROM "Alertas"')).scalar()
    assert total == 2


def test_duas_pessoas_mesma_rota_compartilham_rota_coleta(engine):
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario
    data = (date.today() + timedelta(days=40)).isoformat()
    id_u1 = obter_ou_criar_usuario(engine, "Larissa", "+5521999990003")
    id_u2 = obter_ou_criar_usuario(engine, "Thiago", "+5521999990004")
    criar_alertas_em_lote(engine, id_u1, "GIG", ["MCZ"], data, confirmado=True)
    criar_alertas_em_lote(engine, id_u2, "GIG", ["MCZ"], data, confirmado=True)

    from sqlalchemy import text
    with engine.connect() as connection:
        total_rotas = connection.execute(text('SELECT COUNT(*) FROM "Rotas_Coleta"')).scalar()
        total_alertas = connection.execute(text('SELECT COUNT(DISTINCT "ID_Rota_Coleta") FROM "Alertas"')).scalar()
    assert total_rotas == 1
    assert total_alertas == 1


# ─── coleta diária com múltiplas origens ───────────────────────────────────

def test_coleta_consulta_origens_separadas_por_virgula(engine):
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario
    import coleta_diaria

    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990005")
    data = (date.today() + timedelta(days=40)).isoformat()
    criar_alertas_em_lote(engine, id_usuario, ["GIG", "SDU"], ["MCZ"], data, confirmado=True)

    capturado = {}
    def fake_buscar_voo(origem, destino, ida, volta=None):
        capturado["origem"] = origem
        return resultado_mock(preco=1500.0)

    with patch("coleta_diaria.buscar_voo", side_effect=fake_buscar_voo):
        coleta_diaria.coletar_rotas_fixas(engine, date.today().isoformat(), 10)

    assert capturado["origem"] == "GIG,SDU"


# ─── regras de aviso (sem preço-alvo) ───────────────────────────────────────

def test_sem_historico_nao_notifica_no_primeiro_dia():
    from coleta_diaria import motivo_notificacao
    assert motivo_notificacao(2000.0, "typical", []) is None


def test_novo_minimo_dispara_aviso():
    from coleta_diaria import motivo_notificacao
    serie = [("2026-10-01", 2500.0, "typical"), ("2026-10-02", 2300.0, "typical")]
    motivo, _ = motivo_notificacao(2000.0, "typical", serie)
    assert motivo == "novo_minimo"


def test_preco_normal_nao_dispara_aviso():
    from coleta_diaria import motivo_notificacao
    serie = [("2026-10-01", 2000.0, "typical"), ("2026-10-02", 1950.0, "typical")]
    assert motivo_notificacao(2000.0, "typical", serie) is None


def test_abaixo_da_media_dispara_aviso():
    """Preço bem abaixo da média, mas NÃO é um novo mínimo (já houve um dia
    mais barato) — isolando a regra "abaixo_media" da regra "novo_minimo"."""
    from coleta_diaria import motivo_notificacao
    hoje = date.today()
    serie = [((hoje - timedelta(days=i)).isoformat(), 2050.0, "typical") for i in range(2, 11)]
    serie.append(((hoje - timedelta(days=1)).isoformat(), 1650.0, "typical"))  # já houve mínimo menor
    motivo, detalhes = motivo_notificacao(1700.0, "typical", serie)  # ~14% abaixo da média (~1965)
    assert motivo == "abaixo_media"
    assert 1950 < detalhes["media_30d"] < 2050


def test_nivel_ficou_low_dispara_aviso_mesmo_sem_novo_minimo():
    from coleta_diaria import motivo_notificacao
    serie = [("2026-10-01", 1900.0, "typical"), ("2026-10-02", 1900.0, "typical")]
    motivo, _ = motivo_notificacao(1950.0, "low", serie)  # preço subiu, mas Google marcou "low"
    assert motivo == "ficou_barato"


def test_ja_notificado_hoje_nao_repete(engine):
    from sqlalchemy import text
    from coleta_diaria import ja_notificado_hoje, registrar_notificacao
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario

    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990006")
    data = (date.today() + timedelta(days=40)).isoformat()
    [id_alerta] = criar_alertas_em_lote(engine, id_usuario, "GIG", ["MCZ"], data, confirmado=True)
    hoje = date.today().isoformat()

    with engine.begin() as connection:
        assert not ja_notificado_hoje(connection, id_alerta, "novo_minimo", hoje)
        registrar_notificacao(connection, id_alerta, "novo_minimo", 1500.0)
    with engine.connect() as connection:
        assert ja_notificado_hoje(connection, id_alerta, "novo_minimo", hoje)


def test_fluxo_completo_grava_cotacao_e_notifica(engine):
    """Dois dias de coleta: no 1º dia só grava (sem o que comparar); no 2º,
    um preço bem mais baixo dispara 'novo_minimo' e manda WhatsApp."""
    from sqlalchemy import text
    from alertas_repo import criar_alertas_em_lote, obter_ou_criar_usuario
    import coleta_diaria

    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990007")
    data = (date.today() + timedelta(days=40)).isoformat()
    [id_alerta] = criar_alertas_em_lote(engine, id_usuario, "GIG", ["MCZ"], data, confirmado=True)

    enviados = []
    with patch("coleta_diaria.enviar_alerta_whatsapp", side_effect=lambda tel, msg: enviados.append(msg) or True), \
         patch("coleta_diaria.whatsapp_configurado", return_value=True):

        with patch("coleta_diaria.buscar_voo", return_value=resultado_mock(preco=2000.0)):
            coleta_diaria.coletar_rotas_fixas(engine, date.today().isoformat(), 10)
        assert len(enviados) == 0  # dia 1: nada para comparar ainda

        amanha = (date.today() + timedelta(days=1)).isoformat()
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE "Cotacoes" SET "Data_Referencia" = :ontem WHERE "Data_Referencia" = :hoje
            """), {"ontem": date.today().isoformat(), "hoje": date.today().isoformat()})
        # (simula a passagem de um dia: a cotação de "hoje" vira "ontem")

        with patch("coleta_diaria.buscar_voo", return_value=resultado_mock(preco=1200.0)), \
             patch("coleta_diaria.date") as data_mock:
            data_mock.today.return_value = date.today() + timedelta(days=1)
            data_mock.fromisoformat = date.fromisoformat
            coleta_diaria.coletar_rotas_fixas(engine, amanha, 10)

    assert len(enviados) == 1
    assert "menor preço" in enviados[0].lower()

    with engine.connect() as connection:
        total_cotacoes = connection.execute(text('SELECT COUNT(*) FROM "Cotacoes"')).scalar()
    assert total_cotacoes == 2


def test_migracao_e_idempotente(engine):
    from sqlalchemy import text
    from alertas_repo import obter_ou_criar_usuario
    import migrar_para_cotacoes as migracao

    id_usuario = obter_ou_criar_usuario(engine, "Larissa", "+5521999990008")
    data_viagem = (date.today() + timedelta(days=40)).isoformat()
    with engine.begin() as connection:
        resultado = connection.execute(text("""
            INSERT INTO "Alertas" ("ID_Usuario", "IATA_Origem", "IATA_Destino",
                                    "Mes_Viagem_Ou_Data", "Preco_Alvo", "Confirmado")
            VALUES (:u, 'GIG', 'MCZ', :data, 1500.0, 1)
        """), {"u": id_usuario, "data": data_viagem})
        id_alerta = resultado.lastrowid
        connection.execute(text("""
            INSERT INTO "Historico_Precos" ("ID_Alerta", "Data_Verificacao", "Preco_Encontrado")
            VALUES (:a, '2026-09-01T12:00:00', 1800.0), (:a, '2026-09-02T12:00:00', 1750.0)
        """), {"a": id_alerta})

    with patch("migrar_para_cotacoes.get_engine", return_value=engine):
        migracao.migrar()
        migracao.migrar()  # roda de novo: não pode duplicar nada

    with engine.connect() as connection:
        n_rotas = connection.execute(text('SELECT COUNT(*) FROM "Rotas_Coleta"')).scalar()
        n_cotacoes = connection.execute(text('SELECT COUNT(*) FROM "Cotacoes"')).scalar()
        ligado = connection.execute(text(
            'SELECT "ID_Rota_Coleta" FROM "Alertas" WHERE "ID_Alerta" = :id'
        ), {"id": id_alerta}).scalar()
    assert n_rotas == 1
    assert n_cotacoes == 2
    assert ligado is not None


# ─── formulário público (Streamlit AppTest) ────────────────────────────────

def test_cadastro_form_grava_multi_origem_e_multi_destino(engine, monkeypatch):
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        pytest.skip("streamlit.testing.v1 indisponível nesta versão do Streamlit")

    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    with patch("whatsapp.enviar_alerta_whatsapp", return_value=True), \
         patch("whatsapp.whatsapp_configurado", return_value=False):
        at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "cadastro.py"))
        at.run(timeout=30)
        assert not at.exception

        at.text_input(key=None)  # garante que os widgets carregaram
        inputs = at.text_input
        inputs[0].set_value("Larissa Teste")
        inputs[1].set_value("+5521999990009")

        multiselects = at.multiselect
        multiselects[0].set_value(["GRUPO:GIG+SDU"])  # Rio: os dois aeroportos de uma vez
        multiselects[1].set_value(["MCZ", "REC"])

        at.button[0].click().run(timeout=30)
        assert not at.exception

    from sqlalchemy import text
    with engine.connect() as connection:
        linhas = connection.execute(text(
            'SELECT "IATA_Origem", "IATA_Destino" FROM "Alertas" ORDER BY "IATA_Destino"'
        )).all()
    assert len(linhas) == 2
    assert all(origem == "GIG,SDU" for origem, _ in linhas)
    assert {destino for _, destino in linhas} == {"MCZ", "REC"}
