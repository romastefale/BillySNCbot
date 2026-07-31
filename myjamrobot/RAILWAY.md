# Deploy no Railway

Este documento descreve a configuração de produção do **BillySNCbot** no Railway. O repositório é um monorepo e a aplicação Python está isolada em `myjamrobot/`.

## 1. Fonte e monorepo

Configure o serviço com:

```text
Repository: romastefale/BillySNCbot
Branch: main
Root Directory: /myjamrobot
Config File Path: /myjamrobot/railway.toml
```

O caminho do arquivo de configuração é absoluto em relação à raiz do repositório e não acompanha automaticamente o Root Directory.

Não defina comandos Node, pnpm, Wrangler ou Cloudflare para este serviço. Com o Root Directory correto, o Railway deve detectar `myjamrobot/Dockerfile`. O comando de inicialização e o healthcheck são definidos em `railway.toml`.

## 2. Persistência

Crie um volume no mesmo serviço e monte em:

```text
/app/data
```

Configure:

```text
MYJAM_DATA_DIR=/app/data
MYJAM_DATABASE_URL=sqlite:////app/data/app.db
```

Use uma única réplica. Serviços com SQLite e volume não devem executar múltiplas instâncias concorrentes gravando no mesmo arquivo.

Ative backups do volume antes do corte de produção. Mantenha o modo Serverless desativado para evitar suspensão e cold start do bot.

## 3. Domínio e variáveis

Gere um domínio público HTTPS no Railway. No painel de variáveis, prefira uma referência ao domínio gerado:

```text
MYJAM_BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}
```

Variáveis mínimas:

```text
MYJAM_TELEGRAM_BOT_TOKEN=
MYJAM_SPOTIFY_CLIENT_ID=
MYJAM_SPOTIFY_CLIENT_SECRET=
MYJAM_LASTFM_API_KEY=
MYJAM_CODE_OWNER_IDS=
MYJAM_BASE_URL=https://${{RAILWAY_PUBLIC_DOMAIN}}
MYJAM_DATA_DIR=/app/data
MYJAM_DATABASE_URL=sqlite:////app/data/app.db
```

Para importação de scrobbles pelo owner:

```text
MYJAM_LASTFM_API_SECRET=
MYJAM_LASTFM_SESSION_KEY=
```

Cadastre secrets diretamente no Railway. Não faça commit de `.env`, tokens, chaves, banco SQLite ou conteúdo do volume.

## 4. Callback do Spotify

No aplicativo Spotify, autorize exatamente:

```text
https://<dominio-publico>/callback
```

O domínio deve ser o mesmo valor efetivo de `MYJAM_BASE_URL`.

## 5. Gates antes do deploy

Execute em `myjamrobot/`:

```bash
python -m compileall app scripts tests
PYTHONPATH=. python scripts/smoke_imports.py
PYTHONPATH=. pytest -q
docker build -t billysncbot-railway .
```

O workflow `.github/workflows/railway-readiness.yml` automatiza esses gates em pull requests e em pushes para `main`.

## 6. Primeiro deploy

Nos logs, confirme:

```text
BOOTSTRAP_START
DATABASE_STARTUP_READY
TELEGRAM_STARTUP_READY
```

Falhas bloqueadoras:

```text
STARTUP_MISSING_ENV_VARS
DATABASE_STARTUP_FAILED
TELEGRAM_STARTUP_FAILED
PORT_INVALID
```

Valide:

```text
GET /healthz  -> HTTP 200
GET /readyz   -> HTTP 200 e status=ready
```

O healthcheck do Railway usa `/readyz`; portanto, credenciais e inicialização do núcleo do bot devem estar corretas antes de o deployment ser promovido.

## 7. Homologação funcional

Teste pelo menos:

- `/start` e `/help`;
- consulta Last.fm;
- login e consulta Spotify;
- geração de imagens e fontes;
- funcionalidade que usa Playwright;
- funcionalidade que usa `ffmpeg`;
- comandos em grupo e inline queries;
- comando owner-only;
- endpoint `/inline-icons/playing.png`;
- rejeição de webhook sem o secret esperado.

Depois, crie um dado verificável, reinicie o serviço e faça um redeploy para comprovar que o conteúdo permanece no volume.

## 8. Corte e rollback

Um token Telegram só deve ter um ambiente registrando o webhook de produção.

Ordem de corte:

1. homologar o novo serviço;
2. parar o serviço antigo;
3. aplicar o token de produção no Railway;
4. confirmar `TELEGRAM_STARTUP_READY` e `/readyz`;
5. executar os testes críticos no Telegram.

Rollback:

1. remover ou substituir o token no Railway;
2. reativar o serviço anterior;
3. reiniciá-lo para registrar novamente o webhook;
4. testar `/start`;
5. preservar os logs e o volume do Railway para diagnóstico.

## 9. Critério de aceite

A entrega é considerada concluída somente quando:

- CI e Docker build estiverem aprovados;
- Root Directory e Config File Path estiverem corretos;
- volume estiver montado em `/app/data` com backup;
- Serverless estiver desativado e houver uma única réplica;
- `/healthz` e `/readyz` retornarem HTTP 200;
- os logs mostrarem banco e Telegram prontos;
- Spotify, Last.fm, Playwright, imagens e `ffmpeg` estiverem homologados;
- dados sobreviverem a restart e redeploy;
- o serviço antigo não disputar o webhook.
