# Implantação e recuperação

## Desenvolvimento

Use Python 3.12+ e Node 22 ou versões posteriores compatíveis com o lock. Configure uma instância PostgreSQL de desenvolvimento com `pg_trgm` e usuário capaz de instalar a extensão. A migração usa Alembic e trava concorrente.

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-dev.txt
export GOVBR_DATABASE_URL='postgresql+psycopg://USUARIO:SENHA@127.0.0.1:5432/govbr'
export GOVBR_PUBLIC_URL=http://localhost:8000
python -m govbr migrate
python -m govbr key-add "Desenvolvimento" --admin
python -m govbr serve
```

No Windows PowerShell, ative com `.\.venv\Scripts\Activate.ps1` e use `$env:GOVBR_DATABASE_URL = '…'`. Rode `npm ci` e `npm run dev` em `frontend`. O Vite encaminha o backend para a porta 8000 por padrão. Abra o painel na URL apresentada pelo Vite.

## VPS Ubuntu e HTTPS

1. Instale Docker Engine e o plugin Compose conforme a [documentação oficial](https://docs.docker.com/engine/install/ubuntu/).
2. Copie o projeto e execute `./infrastructure/scripts/init.sh` para preparar o `.env` e validar o ambiente local.
3. Aponte DNS do domínio e permita TCP 80/443 para Caddy. Em `.env`, configure `GOVBR_ENVIRONMENT=production`, `GOVBR_DOMAIN=mcp.seudominio.com` e `GOVBR_PUBLIC_URL=https://mcp.seudominio.com`.
4. Execute `docker compose --profile https up -d --build --wait`. Confira `/readyz` por HTTPS, o retorno 401 de `/mcp` sem token e a descoberta autenticada com um cliente MCP.
5. Emita uma chave de leitura individual para cada cliente compatível.

O PostgreSQL fica na rede privada do Compose. O backend publica a porta local 8787 e recebe o tráfego externo via Caddy. O painel local opcional usa a porta 8788.

### OAuth para clientes MCP

Configure um provedor OAuth 2.1/OIDC de sua administração que emita access token JWT. Configure autorização por código com PKCE S256, registro de cliente conforme o cliente escolhido, UX de consentimento e refresh token quando o cliente precisar. O provedor deve anunciar discovery metadata e entregar `govbr:read` na claim `scope`. O access token deve ter a audiência exata `https://mcp.seudominio.com/mcp`. No provedor, configure resource indicator ou um mapper de audiência que gere essa string.

| Variável | Valor |
|---|---|
| `GOVBR_OAUTH_ISSUER` | Claim `iss` exata publicada pelo provedor |
| `GOVBR_OAUTH_JWKS_URL` | Endpoint HTTPS JWKS do mesmo provedor |
| `GOVBR_OAUTH_AUDIENCE` | URL pública exata do MCP |
| `GOVBR_OAUTH_ALLOWED_SUBJECTS` | Lista separada por vírgula de valores `sub` autorizados |
| `GOVBR_OAUTH_ALGORITHMS` | Um entre RS256, ES256 e EdDSA |

Cadastre no provedor o callback exibido pelo cliente. Provedor e clientes exigem configuração na implantação real. A validação de JWT e o anúncio do recurso possuem testes locais. [Especificação MCP](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).

## Atualizar da versão 0.1

Antes de substituir os arquivos da versão 0.1, execute `docker compose stop frontend` na pasta antiga para liberar a porta 8787. Preserve o `.env` e o volume PostgreSQL, atualize os arquivos do projeto e execute o script de inicialização da sua plataforma. A migração 0002 remove os dados importados do SAGRES e a fila antiga. As APIs oficiais continuam disponíveis, com as mesmas chaves locais.

## Backups e diagnóstico

```bash
./infrastructure/scripts/backup.sh
./infrastructure/scripts/diagnostico.sh
docker compose up -d --build --wait --remove-orphans
```

O Windows tem o equivalente em `infrastructure/scripts/backup.ps1`. Guarde backups com acesso restrito. Restaure primeiro em banco auxiliar vazio, compare contagens e consulte as evidências antes de substituir o banco em uso. Exemplo no ambiente de recuperação.

```bash
docker compose exec -T postgres createdb -U govbr govbr_recuperacao
docker compose exec -T postgres pg_restore --exit-on-error -U govbr -d govbr_recuperacao < backups/ARQUIVO.dump
```

A alteração de senha no `.env` após a inicialização de um volume existente exige rotação correspondente no PostgreSQL. O script de instalação não imprime a senha. O comando de diagnóstico usa somente status, readiness e os últimos logs sem payloads de consulta.
