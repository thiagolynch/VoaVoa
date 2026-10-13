# VOAVOA ✈️

**Pare de ficar checando preço de passagem manualmente.** O VOAVOA acompanha o preço das rotas que importam pra você — ou já publica os 20 destinos internacionais mais buscados por brasileiros — e avisa no WhatsApp quando o preço cai de verdade, comparado com o histórico real daquela rota.

🔗 **Demo ao vivo:** [voavoa1.streamlit.app](https://voavoa1.streamlit.app/)

![Status](https://img.shields.io/badge/status-em%20produção-1C7C54)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/streamlit-painel%20%26%20cadastro-FF4B4B?logo=streamlit&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

## Por que o VOAVOA é diferente

A maioria dos comparadores mostra o preço de hoje e para por aí. O VOAVOA guarda **o histórico de preço de cada rota desde o primeiro dia em que alguém passou a acompanhá-la**, e só manda mensagem quando o preço:

- bate o **menor valor já visto** para aquela rota,
- fica **bem abaixo da média** dos últimos 30 dias, ou
- o próprio Google passa a marcar como **"preço baixo"**.

Sem "digite seu preço-alvo e torça": o sistema decide quando vale avisar, usando dado real de variação de preço.

Outros diferenciais:
- **Múltiplas origens num só alerta** — mora no Rio? Acompanhe GIG e SDU ao mesmo tempo, sem duplicar cadastro.
- **Uma coleta serve todo mundo** — se duas pessoas pedem a mesma rota, só uma consulta é feita e os dois recebem o resultado (economiza cota de API).
- **Vitrine pública** com os 20 destinos mais buscados do Brasil, sem precisar de login.
- **Confirmação por WhatsApp** antes de qualquer alerta entrar no ar, pra ninguém cadastrar o número de outra pessoa.

## Como funciona

| Peça | Arquivo | O que faz |
|---|---|---|
| Vitrine pública | `site/` | Página estática (HTML/CSS/JS puro) com os 20 destinos mais buscados. Publica no GitHub Pages ou Cloudflare Pages. |
| Painel administrativo | `dashboard.py` | Streamlit: cadastro de usuários/alertas, acompanhamento (menor/maior/média desde o início) e análise de variação de preço com exportação em CSV. |
| Cadastro público | `cadastro.py` | Streamlit sem login: qualquer pessoa cria o próprio acompanhamento — múltiplas origens e destinos, data única ou janela flexível. Nasce pendente até confirmar no WhatsApp. |
| Bot de WhatsApp | `whatsapp_bot.py` | Conversa guiada que cria ou confirma acompanhamentos direto pelo WhatsApp. |
| Motor de coleta | `coleta_diaria.py` | Roda todo dia: consulta o Google Flights (via SerpApi), grava o preço no banco, decide se há motivo pra avisar e dispara o WhatsApp. |
| Robô agendado | `.github/workflows/price-scan.yml` | Roda a coleta na nuvem (GitHub Actions, grátis) todo dia às 07h17 (Brasília) — **não depende do seu computador estar ligado**. |

Cada consulta à SerpApi já devolve o **histórico de ~60 dias do Google**, o nível do preço (baixo/normal/alto) e a faixa típica — por isso a série de 30 dias fica correta desde a primeira consulta.

## Stack

Python 3.11+ · Streamlit · SQLAlchemy (SQLite local / PostgreSQL via Supabase em produção) · SerpApi (Google Flights, sem scraping) · Evolution API (WhatsApp) · GitHub Actions · GitHub Pages / Cloudflare Pages.

Arquitetura detalhada em [ARQUITETURA.md](ARQUITETURA.md). Passo a passo de deploy completo em [DEPLOY.md](DEPLOY.md).

## Rodar localmente

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # preencha SERPAPI_KEY e demais variáveis
python setup_db.py
streamlit run cadastro.py       # formulário público
streamlit run dashboard.py      # painel administrativo
python coleta_diaria.py         # roda a coleta/alertas uma vez
```

Para ver a vitrine pública localmente: `python -m http.server 8000 --directory site` e abra `http://localhost:8000`.

Quer contribuir ou testar o fluxo completo (inclusive WhatsApp)? Veja [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- [ ] WhatsApp sem depender de computador local (hospedar a Evolution API ou migrar para a WhatsApp Cloud API da Meta)
- [ ] Plano gratuito com limite de acompanhamentos + plano pago sem limite
- [ ] Notificação por e-mail como alternativa ao WhatsApp
- [ ] Mais destinos nacionais e internacionais na vitrine pública

## Fontes de dados

- Aeroportos: [OurAirports](https://github.com/davidmegginson/ourairports-data) — 129 aeroportos brasileiros com voo regular.
- Ranking de destinos: levantamentos de buscas da Decolar ([jan–fev/2026](https://www.panrotas.com.br/mercado/pesquisas-e-estatisticas/2026/03/decolar-rio-lidera-buscas-de-brasileiros-santiago-e-destino-internacional-mais-procurado_226777.html), [2º sem./2025](https://www.mercadoeeventos.com.br/?p=658055)).

## Licença

[MIT](LICENSE) — use, copie e adapte à vontade, inclusive comercialmente.
