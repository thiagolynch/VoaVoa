# VOAVOA — Arquitetura do Sistema

> Comparador de preços de passagens aéreas com vitrine pública e alertas via WhatsApp.

---

## 1. Visão Geral

O VOAVOA consulta preços de voos pelo **Google Flights via SerpApi** (não faz web scraping) e usa isso para duas coisas: publicar uma **vitrine pública estática** com os 20 destinos internacionais mais procurados, e **avisar por WhatsApp** quando um alerta cadastrado por um usuário atinge o preço-alvo.

```
                         ┌────────────────────────┐
                         │   SerpApi (Google       │
                         │   Flights engine)       │
                         └───────────┬────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    ▼                                  ▼
          vitrine.py (robô diário)            motor_busca.py (robô diário)
          atualiza site/data/precos.json      lê Alertas no banco, grava
          (sem usar banco de dados)           histórico, dispara WhatsApp
                    │                                  │
                    ▼                                  ▼
          GitHub Pages (site/ estático)        Evolution API (Docker local)
                                                        │
                                                        ▼
                                                   WhatsApp do usuário
```

- **vitrine.py** não depende de banco: lê/escreve direto em `site/data/precos.json`, guardando o histórico de preços de cada rota *origem × destino* junto com o próprio JSON.
- **motor_busca.py** depende do banco (SQLite local ou Postgres/Supabase em produção) para saber quais alertas existem e enviar as notificações.

---

## 2. Stack Tecnológico

| Camada | Tecnologia | Finalidade |
|---|---|---|
| Linguagem | **Python 3.11+** | Base do sistema |
| Preços de voos | **SerpApi** (`engine=google_flights`) | Busca o menor preço, nível (baixo/típico/alto), faixa típica e histórico de ~60 dias — tudo numa única requisição, sem scraping |
| Banco de dados | **SQLite** (local) ou **PostgreSQL/Supabase** (produção) | Usuários, alertas e histórico de preços dos alertas |
| ORM / Acesso a BD | **SQLAlchemy Core** (`database.py`) | Define as tabelas e cria a engine (SQLite ou Postgres via `DATABASE_URL`) |
| Vitrine pública | HTML/CSS/JS estático em `site/`, dados em `site/data/precos.json` | Publicada no GitHub Pages (ou Cloudflare Pages) |
| Painel admin | **Streamlit** (`dashboard.py`) | Cadastro de usuários/alertas e visualização de gráficos |
| Notificações | **Evolution API** (WhatsApp Web não oficial, via Docker) | Envio de alertas (`whatsapp.py`) |
| Agendamento | **GitHub Actions** (`cron`) + **Agendador de Tarefas do Windows** | Robô diário na nuvem (vitrine + alertas, se o banco for acessível) e robô diário local (alertas via Evolution API no PC) |
| Variáveis de ambiente | `python-dotenv` | Gestão de chaves/credenciais (`.env` local, Secrets/Variables no GitHub Actions) |
| Logging | `loguru` | Rastreamento de execução e erros (console + `voavoa.log`) |

---

## 3. Esquema da Base de Dados

Usado por `motor_busca.py` e `dashboard.py` (a vitrine pública não usa o banco). Definido em `database.py` com SQLAlchemy Core; criado/migrado por `setup_db.py`.

### 3.1 Tabela `Usuarios`

```sql
CREATE TABLE Usuarios (
    ID                INTEGER PRIMARY KEY AUTOINCREMENT,
    Nome              TEXT    NOT NULL,
    Telefone_WhatsApp TEXT    NOT NULL UNIQUE,
    Opt_in            INTEGER NOT NULL DEFAULT 1
);
```

| Coluna | Descrição |
|---|---|
| `Telefone_WhatsApp` | Número com DDI/DDD, único por usuário |
| `Opt_in` | `1` = ativo, `0` = cancelou (conformidade LGPD / WhatsApp) |

### 3.2 Tabela `Destinos`

```sql
CREATE TABLE Destinos (
    IATA        TEXT PRIMARY KEY,
    Nome_Cidade TEXT NOT NULL,
    Pais        TEXT NOT NULL
);
```

Catálogo de aeroportos (origens no Brasil + os 20 destinos internacionais, definidos em `aeroportos.py`).

### 3.3 Tabela `Alertas`

```sql
CREATE TABLE Alertas (
    ID_Alerta          INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Usuario         INTEGER NOT NULL REFERENCES Usuarios (ID),
    IATA_Origem        TEXT    NOT NULL REFERENCES Destinos (IATA),
    IATA_Destino       TEXT    NOT NULL REFERENCES Destinos (IATA),
    Mes_Viagem_Ou_Data TEXT    NOT NULL,  -- 'YYYY-MM' ou 'YYYY-MM-DD'
    Preco_Alvo         REAL    NOT NULL,
    Preco_Atual        REAL,
    Ultima_Verificacao TEXT
);
```

### 3.4 Tabela `Historico_Precos`

```sql
CREATE TABLE Historico_Precos (
    ID_Historico     INTEGER PRIMARY KEY AUTOINCREMENT,
    ID_Alerta        INTEGER NOT NULL REFERENCES Alertas (ID_Alerta) ON DELETE CASCADE,
    Data_Verificacao TEXT    NOT NULL,
    Preco_Encontrado REAL    NOT NULL
);
CREATE INDEX idx_historico_precos_alerta_data ON Historico_Precos (ID_Alerta, Data_Verificacao);
```

Guarda a série de preços de cada alerta ao longo do tempo (usada pelos gráficos do `dashboard.py`). Na primeira consulta de um alerta, já é povoada com o histórico de ~60 dias que a SerpApi devolve, não só com o ponto do dia.

---

## 4. Vitrine pública (`site/data/precos.json`)

Não usa banco de dados. `vitrine.py` lê o JSON existente, atualiza as rotas mais desatualizadas (`VITRINE_BUSCAS_POR_EXECUCAO` por execução, para economizar cota da SerpApi) e regrava o arquivo inteiro com:

- `rotas[]`: uma entrada por `origem-destino`, com `preco_atual`, `nivel`, `faixa_tipica`, `historico` (lista de `[data, preço]` dos últimos 90 dias) e `stats_30d` (mín/máx/média calculados a partir do histórico).
- `origens[]` e `parametros`: metadados usados pela página para montar os seletores.

A página estática (`site/index.html` + `site/config.js`) lê esse JSON diretamente; enquanto ele não tem preços reais, mostra `site/data/demo.json` com aviso de "dados de demonstração".

---

## 5. Fluxo de Operação

### 5.1 Vitrine (diário, GitHub Actions)
```
1. price-scan.yml dispara vitrine.py (cron 07:17 Brasília)
2. vitrine.py escolhe as N rotas mais desatualizadas e consulta a SerpApi
3. Atualiza site/data/precos.json com preço, nível, histórico e stats_30d
4. Commit + push do JSON no próprio repositório
5. Job "deploy" publica site/ no GitHub Pages
```

### 5.2 Alertas de WhatsApp
```
1. Usuário cadastra alerta no dashboard.py (Streamlit) → INSERT em Alertas
2. motor_busca.py roda (GitHub Actions, se DATABASE_URL for Postgres acessível;
   e/ou Agendador de Tarefas do Windows no PC, para alcançar a Evolution API local)
3. Para cada alerta ativo, consulta a SerpApi (google_flights.py)
4. Grava o preço em Historico_Precos e atualiza Preco_Atual/Ultima_Verificacao
5. Se preço <= Preco_Alvo (e é novidade em relação à última notificação),
   envia WhatsApp via Evolution API (whatsapp.py)
```

`whatsapp.py` desativa o envio automaticamente quando roda no GitHub Actions apontando para uma Evolution API em `localhost`/`127.0.0.1` (inalcançável da nuvem) — nesse caso o preço ainda é gravado, só a mensagem não é enviada.

---

## 6. Decisões de Design

- **Sem web scraping**: todos os preços vêm da SerpApi (motor Google Flights), que já inclui nível de preço e histórico de ~60 dias numa única chamada — evita manutenção de scrapers e bloqueios de sites de passagens.
- **Vitrine sem banco**: a página pública é só um JSON versionado no repositório, o que permite publicar em GitHub Pages/Cloudflare Pages sem precisar de servidor ou banco acessível de fora.
- **SQLite local / Postgres em produção**: `DATABASE_URL` controla o backend (`database.py` normaliza `postgres://` para `postgresql+psycopg://`); permite rodar 100% local com SQLite e opcionalmente migrar para Supabase (`migrar_sqlite_postgres.py`).
- **Evolution API em vez de WhatsApp Business oficial**: custo zero e configuração simples via Docker, ao preço de rodar localmente (não alcançável pelo GitHub Actions) e usar WhatsApp Web não oficial — por isso a recomendação de usar um número dedicado.
- **`Opt_in`** garante conformidade com LGPD e políticas do WhatsApp.
- **Códigos IATA como chave primária em `Destinos`**: únicos e semanticamente significativos.
