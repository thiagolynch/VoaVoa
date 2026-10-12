# -*- coding: utf-8 -*-
"""
google_flights.py
Cliente da SerpApi (motor Google Flights). Retorna o menor preço e também os
"price insights" do Google: nível do preço (baixo/típico/alto), faixa típica
e o histórico de preços dos últimos ~60 dias — com uma única consulta.
"""
import os
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).resolve().parent / ".env")

SERPAPI_URL = "https://serpapi.com/search.json"


@dataclass
class ResultadoBusca:
    preco: float
    nivel: str | None = None                    # "low" | "typical" | "high"
    faixa_tipica: list[float] | None = None     # [mín, máx] típico segundo o Google
    historico: list[tuple[str, float]] = field(default_factory=list)  # [(AAAA-MM-DD, preço)]
    companhia: str | None = None
    escalas: int | None = None
    duracao_min: int | None = None
    google_flights_url: str | None = None


def link_google_flights(origem: str, destino: str, ida: str, volta: str | None = None) -> str:
    consulta = f"Flights to {destino} from {origem} on {ida}"
    if volta:
        consulta += f" through {volta}"
    else:
        consulta += " oneway"
    return "https://www.google.com/travel/flights?" + urllib.parse.urlencode(
        {"q": consulta, "curr": "BRL", "hl": "pt-BR", "gl": "BR"}
    )


def _historico(price_history) -> list[tuple[str, float]]:
    pontos = {}
    for item in price_history or []:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            continue
        ts, preco = item
        if not isinstance(ts, (int, float)) or not isinstance(preco, (int, float)):
            continue
        dia = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        pontos[dia] = float(preco)
    return sorted(pontos.items())


def buscar_voo(origem: str, destino: str, ida: str, volta: str | None = None) -> ResultadoBusca | None:
    """Consulta a SerpApi. `ida`/`volta` em AAAA-MM-DD; sem `volta` = só ida."""
    chave = os.getenv("SERPAPI_KEY")
    if not chave:
        logger.error("SERPAPI_KEY não configurada (.env ou secrets do GitHub).")
        return None

    params = {
        "engine": "google_flights",
        "departure_id": origem,
        "arrival_id": destino,
        "outbound_date": ida,
        "type": "1" if volta else "2",  # 1 = ida e volta, 2 = só ida
        "currency": "BRL",
        "hl": "pt",
        "gl": "br",
        "api_key": chave,
    }
    if volta:
        params["return_date"] = volta

    rota = f"{origem} ➔ {destino} ({ida}{' / ' + volta if volta else ''})"
    try:
        logger.debug(f"Consultando Google Flights: {rota}")
        resposta = requests.get(SERPAPI_URL, params=params, timeout=60)
        payload = resposta.json()
    except requests.RequestException as erro:
        # Não loga a URL completa para não vazar a chave da API.
        logger.error(f"Falha de conexão com a SerpApi em {rota}: {type(erro).__name__}")
        return None
    except ValueError:
        logger.error(f"Resposta inválida da SerpApi em {rota} (HTTP {resposta.status_code}).")
        return None

    if resposta.status_code != 200 or "error" in payload:
        logger.error(f"SerpApi recusou {rota}: HTTP {resposta.status_code} - {payload.get('error')}")
        return None

    voos = [v for v in payload.get("best_flights", []) + payload.get("other_flights", [])
            if isinstance(v.get("price"), (int, float))]
    insights = payload.get("price_insights") or {}

    if voos:
        melhor = min(voos, key=lambda v: v["price"])
        trechos = melhor.get("flights") or [{}]
        preco = float(melhor["price"])
        companhia = trechos[0].get("airline")
        escalas = max(len(trechos) - 1, 0)
        duracao = melhor.get("total_duration")
    elif isinstance(insights.get("lowest_price"), (int, float)):
        preco, companhia, escalas, duracao = float(insights["lowest_price"]), None, None, None
    else:
        logger.warning(f"Nenhum preço retornado para {rota}.")
        return None

    faixa = insights.get("typical_price_range")
    url = (payload.get("search_metadata") or {}).get("google_flights_url")
    if not url or url.rstrip("/").endswith("flights?hl=en"):
        url = link_google_flights(origem, destino, ida, volta)

    resultado = ResultadoBusca(
        preco=preco,
        nivel=insights.get("price_level"),
        faixa_tipica=[float(x) for x in faixa] if isinstance(faixa, list) and len(faixa) == 2 else None,
        historico=_historico(insights.get("price_history")),
        companhia=companhia,
        escalas=escalas,
        duracao_min=duracao if isinstance(duracao, int) else None,
        google_flights_url=url,
    )
    logger.debug(
        f"{rota}: R$ {preco:.2f} | nível={resultado.nivel} | "
        f"{len(resultado.historico)} pontos de histórico"
    )
    return resultado
