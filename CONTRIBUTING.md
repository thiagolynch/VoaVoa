# Como contribuir com o VOAVOA

Obrigado pelo interesse! Este guia explica como rodar o projeto localmente e enviar melhorias.

## Pré-requisitos

- Python 3.11+
- Uma chave da [SerpApi](https://serpapi.com/) (plano gratuito já é suficiente para testar)
- Opcional, só para testar banco compartilhado: um projeto no [Supabase](https://supabase.com/) (PostgreSQL gratuito)
- Opcional, só para testar o fluxo de WhatsApp: [Docker](https://www.docker.com/) + [Evolution API](https://github.com/EvolutionAPI/evolution-api)

## Configurar o ambiente

```bash
git clone https://github.com/thiagolynch/VoaVoa.git
cd VoaVoa
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Preencha pelo menos `SERPAPI_KEY` no `.env`. Sem `DATABASE_URL`, o projeto usa SQLite local (`voavoa.db`) — suficiente para desenvolver.

```bash
python setup_db.py              # cria/atualiza as tabelas
streamlit run cadastro.py       # formulário público (porta padrão 8501)
streamlit run dashboard.py      # painel administrativo
python coleta_diaria.py         # roda a coleta de preços e os alertas uma vez
```

## Rodar os testes

```bash
pip install pytest
pytest tests_voavoa.py -v
```

Todos os testes usam um banco SQLite temporário e mockam as chamadas à SerpApi e ao WhatsApp — não é preciso ter chaves reais para rodá-los.

## Testar o fluxo de WhatsApp (opcional)

1. Suba a Evolution API com `docker compose up -d` (veja `docker-compose.yml`).
2. Preencha `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE_NAME` e `EVOLUTION_API_KEY` no `.env`.
3. Rode `python conectar_whatsapp.py` para parear o número via QR Code.
4. `python whatsapp_bot.py` sobe o bot de conversa; `python coleta_diaria.py` envia os alertas.

## Enviando uma mudança

1. Crie um branch a partir de `main`: `git checkout -b minha-melhoria`.
2. Garanta que `pytest tests_voavoa.py` passa antes de abrir o PR.
3. Descreva no PR o que mudou e por quê — prints da UI ajudam bastante quando a mudança é visual.
4. Evite commitar `.env`, `voavoa.db`, `venv/` ou qualquer credencial — o `.gitignore` já cobre o básico, mas confira com `git status` antes de commitar.

## Reportando bugs ou ideias

Abra uma [issue](https://github.com/thiagolynch/VoaVoa/issues) descrevendo o comportamento esperado vs. o observado (ou a ideia de melhoria). Issues com passos claros pra reproduzir são resolvidas mais rápido.
