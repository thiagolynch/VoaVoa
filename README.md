# VOAVOA ✈️

Acompanha o preço das passagens para os 20 destinos internacionais mais procurados por brasileiros, mostra **menor, maior e média dos últimos 30 dias** numa página pública e manda **alerta no WhatsApp** quando o preço chega no valor desejado.

## Como funciona

| Peça | Arquivo | O que faz |
|---|---|---|
| Página pública | `site/` | HTML estático que lê `site/data/precos.json`. Publica no GitHub Pages ou Cloudflare Pages. |
| Atualizador da página | `vitrine.py` | Consulta o Google Flights (via SerpApi) para as rotas *origens × 20 destinos* e grava o JSON. |
| Alertas | `motor_busca.py` | Lê os alertas do banco, grava histórico e envia WhatsApp pela Evolution API. |
| Painel admin | `dashboard.py` | Streamlit para cadastrar usuários/alertas e ver gráficos. |
| Robô diário | `.github/workflows/price-scan.yml` | Roda tudo todo dia às 07h17 (Brasília), salva os preços e publica a página. |

Cada consulta à SerpApi já devolve o **histórico de ~60 dias do Google** (`price_insights`), o nível do preço (baixo / normal / alto) e a faixa típica. Por isso a estatística de 30 dias fica correta desde a primeira consulta, e dá para atualizar cada rota só uma vez por semana, economizando cota.

## Rodar no seu PC (Windows / VS Code)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # depois preencha SERPAPI_KEY etc.
python setup_db.py
python vitrine.py           # atualiza site/data/precos.json
python motor_busca.py       # verifica alertas
streamlit run dashboard.py  # painel admin
```

Para ver a página localmente: `python -m http.server 8000 --directory site` e abra http://localhost:8000.
Enquanto `precos.json` não tiver preços, a página mostra **dados de demonstração** (`site/data/demo.json`) com um aviso.

## Publicar no GitHub

1. Crie um repositório **público** em https://github.com/new (ex.: `voavoa`), sem README.
2. No terminal do VS Code, dentro da pasta VOAVOA:
   ```powershell
   git init
   git add .
   git status          # confira: .env, voavoa.db, venv e qrcode NÃO podem aparecer
   git commit -m "VOAVOA: primeira versão"
   git branch -M main
   git remote add origin https://github.com/thiagolynch/voavoa.git
   git push -u origin main
   ```
3. **Settings → Secrets and variables → Actions → New repository secret**:
   - `SERPAPI_KEY` (obrigatório)
   - `DATABASE_URL` (opcional: URL do Supabase — sem ele o robô só atualiza a página, sem alertas)
   - `EVOLUTION_API_URL`, `EVOLUTION_INSTANCE_NAME`, `EVOLUTION_API_KEY` (opcional, ver WhatsApp abaixo)
4. (Opcional) Aba **Variables**: `VITRINE_ORIGENS` (ex.: `GRU,GIG,BSB`) e `VITRINE_BUSCAS_POR_EXECUCAO`.
5. **Settings → Pages → Source: GitHub Actions**.
6. **Actions → Varredura diária de preços → Run workflow** para rodar a primeira vez.
   A página fica em `https://thiagolynch.github.io/voavoa/`.

### Ou no Cloudflare Pages

Cloudflare → Workers & Pages → Create → Pages → *Connect to Git* → escolha o repositório.
Build command: *(vazio)* · Build output directory: `site`. Cada commit do robô republica sozinho.

## Cota da SerpApi

Conta: *rotas consultadas por dia × 30*. Padrão = 6 por dia ≈ 180/mês, e cada uma das 40 rotas (GRU e GIG × 20) é atualizada a cada ~7 dias. Cada alerta de WhatsApp gasta mais 1 consulta por dia. Confira o limite do seu plano no painel da SerpApi e ajuste `VITRINE_BUSCAS_POR_EXECUCAO`.

## WhatsApp

A Evolution API do `docker-compose.yml` roda **no seu PC**, e o GitHub Actions não consegue alcançar `127.0.0.1`. Duas saídas:

- **Rodar os alertas no seu PC**: Agendador de Tarefas do Windows chamando `venv\Scripts\python.exe motor_busca.py` uma vez por dia (o robô do GitHub continua cuidando da página).
- **Expor a Evolution API**: Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:8080`) ou hospedar num VPS, e colocar essa URL no secret `EVOLUTION_API_URL`.

A Evolution API usa o WhatsApp Web (não oficial): use um número separado e envie só para quem pediu o alerta, para não arriscar bloqueio. Para escalar, o caminho oficial é a WhatsApp Cloud API da Meta.

O botão **"Quero alerta no WhatsApp"** da página aparece quando você coloca seu número em `site/config.js`; ele abre uma conversa com a rota já escrita, e você cadastra o alerta no painel.

## Fontes

- Aeroportos: [OurAirports](https://github.com/davidmegginson/ourairports-data) — 129 aeroportos brasileiros com voo regular.
- Ranking de destinos: levantamentos de buscas da Decolar ([jan–fev/2026](https://www.panrotas.com.br/mercado/pesquisas-e-estatisticas/2026/03/decolar-rio-lidera-buscas-de-brasileiros-santiago-e-destino-internacional-mais-procurado_226777.html), [2º sem./2025](https://www.mercadoeeventos.com.br/?p=658055)); posições 14–20 completadas com destinos tradicionais (Miami, Nova York, Madri, Londres, Porto, Barcelona, Mendoza).
