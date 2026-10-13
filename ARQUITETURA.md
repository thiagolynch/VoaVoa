# VOAVOA — Arquitetura do Sistema

> Comparador de preços de passagens aéreas com vitrine pública e alertas via WhatsApp.

---

## 1. Visão Geral

O VOAVOA consulta preços de voos pelo **Google Flights via SerpApi** (não faz web scraping) e usa isso para duas coisas: publicar uma **vitrine pública estática** com os 20 destinos internacionais mais procurados, e **avisar por WhatsApp** quando o preço de uma rota acompanhada cai de verdade (novo mínimo histórico, bem abaixo da média de 30 dias, ou o Google marca como preço baixo) — sem precisar de um preço-alvo definido pelo usuário.

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
    Ultima_Verificacao TEXT,
    Confirmado         INTEGER NOT NULL DEFAULT 1,  -- 0 = pendente de confirmação por WhatsApp
    Criado_Em          TEXT,
    Data_Inicio_Janela TEXT,    -- janela de datas flexível (opcional)
    Data_Fim_Janela    TEXT,
    Duracao_Min_Noites INTEGER  -- só usado junto com a janela
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

**PC em modo suspenso, não ligado o dia todo**: como a Evolution API/bot rodam localmente, `acordar_e_processar.ps1` + duas tarefas agendadas com "Wake the computer to run this task" fazem o Windows acordar sozinho do modo suspenso 2x/dia (meio-dia e 19h), subir o Docker, deixar o bot processar o que chegou enquanto estava suspenso, e rodar `motor_busca.py` (alertas chegam por volta desses dois horários). Ver `DEPLOY.md` seção 6. Trade-offs: mensagens de WhatsApp só são respondidas na próxima janela (não instantaneamente), e rodar `motor_busca.py` 2x/dia em vez de 1x dobra o consumo de cota da SerpApi.

### 5.3 Autoatendimento: formulário público + bot de WhatsApp

Além do `dashboard.py` (cadastro manual, admin), existem duas formas de qualquer pessoa criar o próprio alerta:

- **`cadastro.py`**: app Streamlit público (sem autenticação), com formulário de nome/telefone/origem/destino(s)/preço/data. Destino aceita múltiplos valores (`st.multiselect`) — um alerta é criado por destino. A data pode ser única ou uma janela flexível (início, fim, noites mínimas).
- **`whatsapp_bot.py`**: servidor Flask que recebe os webhooks `MESSAGES_UPSERT` da Evolution API (configurado por `configurar_webhook_bot.py`) e conduz uma conversa guiada (nome → preço → data/janela → noites, só perguntando o que faltar) até criar o(s) alerta(s). Roda como container `whatsapp-bot` no `docker-compose.yml`, na mesma rede que a Evolution API.

**Confirmação em duas etapas**: alertas criados pelo `cadastro.py` nascem com `Confirmado = 0` — o bot manda uma mensagem pedindo para responder "CONFIRMAR", e só aí o alerta entra na verificação do `motor_busca.py` (que filtra `Confirmado = 1`). Isso evita que alguém cadastre o número de WhatsApp de outra pessoa sem consentimento. Alertas criados diretamente pelo bot já nascem confirmados, porque a própria mensagem já veio do WhatsApp do dono do número. Pedidos nunca confirmados são apagados depois de 48h (`alertas_repo.limpar_alertas_nao_confirmados`, chamado no início de cada execução do `motor_busca.py`).

O estado da conversa em andamento (o que já foi perguntado, o que falta) fica na tabela `Conversas_Bot` (`Telefone`, `Estado`, `Dados` em JSON, `Atualizado_Em`), com expiração de 30 minutos.

**Janela de datas flexível e custo de cota**: não existe uma única consulta da SerpApi que devolva "o melhor preço de um intervalo de datas" — cada combinação de ida precisa de uma consulta própria. Por isso, alertas em modo janela são verificados por **amostragem** (`motor_busca.buscar_melhor_preco_na_janela`): só algumas datas dentro do intervalo são testadas, espaçadas por `JANELA_AMOSTRAGEM_DIAS` (padrão 3 dias), sempre incluindo as duas pontas da janela. Uma janela de 10 dias custa ~4 consultas por verificação em vez de 1. `JANELA_MAX_DIAS` (padrão 30) limita o tamanho máximo do intervalo aceito. O limite `MAX_ALERTAS_ATIVOS` conta linhas de `Alertas`, não consultas — então muitos alertas em modo janela ainda pressionam a cota da SerpApi mais do que esse limite sozinho sugere.

---

## 6. Decisões de Design

- **Sem web scraping**: todos os preços vêm da SerpApi (motor Google Flights), que já inclui nível de preço e histórico de ~60 dias numa única chamada — evita manutenção de scrapers e bloqueios de sites de passagens.
- **Vitrine sem banco**: a página pública é só um JSON versionado no repositório, o que permite publicar em GitHub Pages/Cloudflare Pages sem precisar de servidor ou banco acessível de fora.
- **SQLite local / Postgres em produção**: `DATABASE_URL` controla o backend (`database.py` normaliza `postgres://` para `postgresql+psycopg://`); permite rodar 100% local com SQLite e opcionalmente migrar para Supabase (`migrar_sqlite_postgres.py`).
- **Evolution API em vez de WhatsApp Business oficial**: custo zero e configuração simples via Docker, ao preço de rodar localmente (não alcançável pelo GitHub Actions) e usar WhatsApp Web não oficial — por isso a recomendação de usar um número dedicado.
- **`Opt_in`** garante conformidade com LGPD e políticas do WhatsApp.
- **Códigos IATA como chave primária em `Destinos`**: únicos e semanticamente significativos.
- **Formulário público exige confirmação por WhatsApp**: sem isso, qualquer um poderia cadastrar o número de outra pessoa sem consentimento. O bot já serve como canal natural pra essa confirmação (reaproveita a mesma infraestrutura de envio).
- **Amostragem em vez de busca exaustiva na janela de datas**: testar todo dia do intervalo multiplicaria a cota da SerpApi por alerta; a amostragem é uma escolha deliberada de custo × precisão, documentada e configurável (`JANELA_AMOSTRAGEM_DIAS`, `JANELA_MAX_DIAS`).
