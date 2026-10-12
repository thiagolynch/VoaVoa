# -*- coding: utf-8 -*-
"""
vitrine.py
Atualiza a página pública (site/data/precos.json) com os preços das rotas
"origens da vitrine" ➔ 20 destinos internacionais mais procurados.

Para caber na cota da SerpApi, cada execução consulta só as N rotas mais
desatualizadas (VITRINE_BUSCAS_POR_EXECUCAO). Como cada consulta já traz o
histórico de ~60 dias do Google, menor/maior/média de 30 dias ficam corretos
mesmo atualizando cada rota só uma vez por semana.

Uso:  python vitrine.py            (consulta a SerpApi)
      python vitrine.py --so-recalcular   (só refaz as estatísticas, sem consultar)
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from loguru import logger

from aeroportos import DESTINOS_TOP20, NOMES
from google_flights import buscar_voo, link_google_flights

ARQUIVO = Path(__file__).resolve().parent / "site" / "data" / "precos.json"
ORIGENS = [o.strip().upper() for o in os.getenv("VITRINE_ORIGENS", "GRU,GIG").split(",") if o.strip()]
BUSCAS_POR_EXECUCAO = int(os.getenv("VITRINE_BUSCAS_POR_EXECUCAO", "6"))
ANTECEDENCIA_DIAS = int(os.getenv("VITRINE_ANTECEDENCIA_DIAS", "60"))
NOITES = int(os.getenv("VITRINE_NOITES", "7"))
DIAS_HISTORICO = 90


def carregar() -> dict:
    if ARQUIVO.exists():
        return json.loads(ARQUIVO.read_text(encoding="utf-8"))
    return {"rotas": []}


def estatisticas(historico: list, hoje: date) -> dict | None:
    limite = (hoje - timedelta(days=30)).isoformat()
    precos = [p for d, p in historico if d >= limite]
    if not precos:
        return None
    return {"min": min(precos), "max": max(precos), "media": round(mean(precos), 2), "pontos": len(precos)}


def montar_rota(origem: str, destino: tuple, anterior: dict | None) -> dict:
    iata, cidade, pais, codigo_pais = destino
    rota = dict(anterior or {})
    rota.update({
        "id": f"{origem}-{iata}",
        "origem": origem,
        "origem_nome": NOMES.get(origem, origem),
        "destino": iata,
        "destino_nome": cidade,
        "pais": pais,
        "pais_codigo": codigo_pais,
        "ranking": [d[0] for d in DESTINOS_TOP20].index(iata) + 1,
    })
    rota.setdefault("historico", [])
    return rota


def atualizar_rota(rota: dict, hoje: date) -> bool:
    ida = (hoje + timedelta(days=ANTECEDENCIA_DIAS)).isoformat()
    volta = (hoje + timedelta(days=ANTECEDENCIA_DIAS + NOITES)).isoformat()
    resultado = buscar_voo(rota["origem"], rota["destino"], ida, volta)
    if resultado is None:
        return False

    # O histórico do Google é para a data pesquisada; quando vem, ele substitui
    # o anterior. Sem ele, mantemos o nosso e somamos o ponto de hoje.
    pontos = dict(resultado.historico) if resultado.historico else dict(rota.get("historico", []))
    pontos[hoje.isoformat()] = resultado.preco
    limite = (hoje - timedelta(days=DIAS_HISTORICO)).isoformat()

    rota.update({
        "data_ida": ida,
        "data_volta": volta,
        "preco_atual": resultado.preco,
        "nivel": resultado.nivel,
        "faixa_tipica": resultado.faixa_tipica,
        "companhia": resultado.companhia,
        "escalas": resultado.escalas,
        "duracao_min": resultado.duracao_min,
        "google_flights_url": resultado.google_flights_url,
        "historico": sorted([d, p] for d, p in pontos.items() if d >= limite),
        "verificado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return True


def main(consultar: bool = True):
    hoje = date.today()
    dados = carregar()
    anteriores = {r["id"]: r for r in dados.get("rotas", [])}
    rotas = [montar_rota(o, d, anteriores.get(f"{o}-{d[0]}")) for o in ORIGENS for d in DESTINOS_TOP20]

    if consultar:
        fila = sorted(rotas, key=lambda r: r.get("verificado_em") or "")[:BUSCAS_POR_EXECUCAO]
        logger.info(f"Vitrine: {len(rotas)} rotas, consultando as {len(fila)} mais desatualizadas.")
        ok = sum(atualizar_rota(r, hoje) for r in fila)
        logger.info(f"Vitrine: {ok}/{len(fila)} rotas atualizadas.")

    for rota in rotas:
        rota["stats_30d"] = estatisticas(rota.get("historico", []), hoje)
        if rota.get("data_ida") and not rota.get("google_flights_url"):
            rota["google_flights_url"] = link_google_flights(
                rota["origem"], rota["destino"], rota["data_ida"], rota.get("data_volta"))

    dados = {
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parametros": {"origens": ORIGENS, "antecedencia_dias": ANTECEDENCIA_DIAS, "noites": NOITES},
        "origens": [{"iata": o, "nome": NOMES.get(o, o)} for o in ORIGENS],
        "rotas": rotas,
    }
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.success(f"Página atualizada: {ARQUIVO}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main(consultar="--so-recalcular" not in sys.argv)
