# Deploy do VOAVOA

## Arquitetura

- O Streamlit Community Cloud hospeda apenas o painel web.
- O Supabase PostgreSQL guarda usuários, alertas e histórico compartilhados.
- O GitHub Actions executa `motor_busca.py` uma vez por dia e acessa o mesmo Supabase.
- A Evolution API é um serviço separado; precisa estar publicamente acessível por HTTPS para o worker do GitHub Actions.
- O SQLite continua disponível para desenvolvimento local, mas o disco do Streamlit Cloud não é armazenamento persistente.

## 1. Preparar o Supabase

1. Crie um projeto no Supabase e guarde a senha do banco em um gerenciador de senhas.
2. Na tela **Connect** do projeto, copie a URL PostgreSQL do **Session Pooler** para serviços hospedados. Use SSL; a URL deve conter `sslmode=require`.
3. Copie `.env.example` para `.env` se ainda não existir:

   ```powershell
   Copy-Item .env.example .env
   ```

4. Edite apenas o arquivo local `.env` e defina `DATABASE_URL` com a URL do Supabase. Se a senha contiver caracteres especiais, use URL encoding.
5. Instale dependências e migre a base SQLite atual. O script cria o esquema e copia destinos, usuários, alertas e histórico sem substituir registros que já existam no destino:

   ```powershell
   & .\venv\Scripts\python.exe -m pip install -r requirements.txt
   & .\venv\Scripts\python.exe migrar_sqlite_postgres.py
   ```

   O SQLite de origem é `voavoa.db`. Para outro arquivo, defina `SQLITE_SOURCE_URL=sqlite:///caminho/arquivo.db` no `.env`. Não apague o SQLite até conferir os totais no Supabase.

## 2. Publicar no GitHub

Crie um repositório no GitHub. Recomenda-se **Private**, pois o painel mostra rotas e nomes de usuários. O `.gitignore` exclui `.env`, `secrets.toml`, bancos locais, logs e QR Codes.

Na pasta do projeto, confira o que será enviado antes de fazer commit:

```powershell
git init
git add .
git status --short
```

Confirme que `.env`, `.streamlit/secrets.toml` e `voavoa.db` não aparecem na lista. Então crie e envie o primeiro commit:

```powershell
git commit -m "Prepare VOAVOA for cloud deployment"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/VOAVOA.git
git push -u origin main
```

Se o repositório já existir localmente, não execute `git init` nem adicione outro `origin`; confira `git remote -v` e envie a branch existente.

## 3. Publicar o painel no Streamlit Community Cloud

1. Acesse [share.streamlit.io](https://share.streamlit.io/) e conecte sua conta GitHub.
2. Escolha **Create app**, selecione o repositório, a branch `main` e o arquivo `dashboard.py`.
3. Em **Advanced settings / Secrets**, cole os valores abaixo, preenchendo-os localmente. Não coloque os valores reais no GitHub:

   ```toml
   DATABASE_URL = "postgresql://USUARIO:SENHA@HOST:6543/postgres?sslmode=require"
   SERPAPI_KEY = "chave-serpapi"
   EVOLUTION_API_URL = "https://seu-host-evolution"
   EVOLUTION_INSTANCE_NAME = "voavoa"
   EVOLUTION_API_KEY = "chave-evolution"
   ```

4. Depois da implantação, a URL do app será exibida pelo Streamlit Cloud, normalmente `https://nome-do-app.streamlit.app`.
5. Em **App settings → Sharing**, escolha **Only specific people can view this app** e convide o e-mail da sua esposa. Um repositório público torna o app público por padrão; para privacidade, mantenha o repositório e o app privados. O Community Cloud permite somente um app privado por workspace.

O painel lê `DATABASE_URL` de `st.secrets` no Cloud e das variáveis de ambiente/`.env` localmente.

## 4. Configurar o worker diário

O workflow `.github/workflows/price-scan.yml` executa a busca diariamente (10:17 UTC) e também pode ser acionado manualmente em **Actions**. No repositório, abra **Settings → Secrets and variables → Actions → New repository secret** e crie:

- `DATABASE_URL`: a mesma URL PostgreSQL do Supabase usada pelo painel.
- `SERPAPI_KEY`: chave da SerpApi.
- `EVOLUTION_API_URL`: URL pública HTTPS da Evolution API.
- `EVOLUTION_INSTANCE_NAME`: nome da instância Evolution.
- `EVOLUTION_API_KEY`: chave da Evolution API.

Os GitHub Actions Secrets são separados dos Streamlit Secrets; cadastre as chaves nos dois locais. O workflow falha antes da busca se algum secret estiver ausente.

A URL local `http://127.0.0.1:8080` não funciona a partir do GitHub Actions. A Evolution API não é hospedada pelo Streamlit Cloud e precisa de uma hospedagem própria acessível pela internet, com HTTPS, PostgreSQL/Redis e armazenamento persistente. Sem isso, o painel e a consulta SerpApi podem funcionar, mas os avisos WhatsApp não serão entregues.

## 5. Autoatendimento público (opcional)

### Formulário (`cadastro.py`)

Mesmo processo do passo 3, só que num **segundo app** do Streamlit Community Cloud, apontando pro arquivo `cadastro.py`, com os mesmos secrets de `DATABASE_URL` (não precisa de `SERPAPI_KEY` nem Evolution). Diferente do `dashboard.py`, deixe o **Sharing** desse app como público — é pra qualquer visitante usar. A URL gerada vai no `site/config.js` (`cadastroUrl`), pra aparecer o botão "Cadastrar alerta" na vitrine.

### Bot de WhatsApp (`whatsapp_bot.py`)

Roda como container (`whatsapp-bot` no `docker-compose.yml`), na mesma rede da Evolution API — por isso só funciona enquanto a Evolution também estiver rodando localmente (não dá pra usar com o painel no Streamlit Cloud sem antes expor a Evolution publicamente, igual explicado acima pros alertas de WhatsApp).

```powershell
docker compose up -d --build whatsapp-bot
& .\venv\Scripts\python.exe configurar_webhook_bot.py
```

O segundo comando aponta a Evolution API pra chamar o bot quando chegar mensagem; só precisa rodar de novo se a instância da Evolution for recriada.

## 6. Rodar sem deixar o PC ligado o dia todo

Enquanto a Evolution API/bot rodarem localmente (sem VPS), o PC precisa estar ligado pra receber mensagens de WhatsApp em tempo real. Pra não precisar deixá-lo ligado o dia inteiro, use o **modo suspenso + despertadores do Windows**:

- `acordar_e_processar.ps1`: sobe o Docker (inicia o Docker Desktop se precisar), espera a Evolution API reconectar e o bot processar as mensagens que chegaram enquanto o PC estava suspenso, e (só quando chamado com `-RodarMotorBusca`) roda `motor_busca.py`.
- Três tarefas agendadas (`VOAVOA Acordar 0730 (alertas)`, `1330 (whatsapp)`, `1930 (whatsapp)`), com **"Wake the computer to run this task"** habilitado — o Windows acorda o PC sozinho do modo suspenso nesses horários. Só a tarefa das 07:30 passa `-RodarMotorBusca`, pra não rodar a verificação de preços 3x ao dia (triplicaria o consumo de cota da SerpApi).
- Isso exige que o Windows tenha permissão de usar despertadores (`powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1` e o mesmo com `/SETDCVALUEINDEX`, se for notebook na bateria) e que o PC seja **suspenso** (não desligado) nos intervalos — suspender permite o despertador; desligado por completo, nem sempre.
- Trade-off: mensagens de WhatsApp recebidas fora dessas janelas só são respondidas na próxima vez que o PC acordar (até ~6h de atraso, com 3 janelas por dia). Pra resposta instantânea 24h, a Evolution API/bot precisariam rodar num VPS sempre ligado, fora do PC do usuário.

## Desenvolvimento local

Com `DATABASE_URL=sqlite:///voavoa.db` no `.env`, execute:

```powershell
& .\venv\Scripts\python.exe setup_db.py
& .\venv\Scripts\python.exe -m streamlit run dashboard.py
```

Pra testar o formulário público localmente: `& .\venv\Scripts\python.exe -m streamlit run cadastro.py`.
