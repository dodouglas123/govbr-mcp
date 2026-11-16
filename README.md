# GovBR MCP

Servidor de código aberto para consultar dados públicos brasileiros por REST e MCP. As consultas usam as APIs oficiais do PNCP, SICONFI, Compras.gov.br, IBGE, Dados Abertos da Paraíba e Portal da Transparência da CGU. O PostgreSQL guarda cache, histórico e evidências das consultas.

## Instalar

Tenha o Docker com Docker Compose v2 em execução. Clone o projeto ou extraia o ZIP da [versão mais recente](https://github.com/dodouglas123/govbr-mcp/releases/latest).

```bash
git clone https://github.com/dodouglas123/govbr-mcp.git
cd govbr-mcp
```

No Windows, execute no PowerShell.

```powershell
powershell -ExecutionPolicy Bypass -File .\infrastructure\scripts\init.ps1
```

No Linux ou macOS, execute no terminal.

```bash
./infrastructure/scripts/init.sh
```

A API fica em [localhost:8787](http://localhost:8787). Confira a [prontidão](http://localhost:8787/readyz) e consulte o [esquema OpenAPI](http://localhost:8787/api/openapi.json).

## Consultar a API

Gere uma chave de leitura para enviar no cabeçalho `Authorization: Bearer ...`. O comando mostra o valor de `token` uma vez.

```bash
docker compose exec -T backend python -m govbr key-add "Cliente local"
```

No Linux ou macOS, substitua `<CHAVE>` pelo token gerado.

```bash
curl --fail-with-body http://localhost:8787/api/consultas \
  -H "Authorization: Bearer <CHAVE>" \
  -H "Content-Type: application/json" \
  -d '{"operacao":"contrato","fonte":"pncp","identificador":"04564530000113-2-000059/2024"}'
```

No PowerShell, use os mesmos filtros.

```powershell
$headers = @{ Authorization = 'Bearer <CHAVE>' }
$body = @{ operacao = 'contrato'; fonte = 'pncp'; identificador = '04564530000113-2-000059/2024' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://localhost:8787/api/consultas' -Headers $headers -ContentType 'application/json' -Body $body
```

| Rota | Uso |
|---|---|
| `GET /api/fontes` | Fontes, operações, limites e disponibilidade |
| `POST /api/consultas` | Buscar registros oficiais com filtros |
| `GET /api/consultas/{id}` | Recuperar o resultado de uma consulta da própria chave |
| `GET /api/consultas/{id}/exportar?formato=csv` | Exportar os registros da consulta |
| `GET /api/evidencias/{id}` | Ver a origem, a data de coleta e o SHA-256 |

A CGU exige uma chave própria. Preencha `GOVBR_CGU_KEY` no arquivo `.env` e execute `docker compose up -d --force-recreate --wait backend`. [Cadastro oficial da CGU](https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email).

## Usar MCP ou o painel

- Configure um cliente MCP para `http://localhost:8787/mcp`, com uma chave de leitura no cabeçalho Bearer. Há exemplos para Streamable HTTP e stdio no [guia MCP](docs/mcp-tools.md).
- Para usar o painel opcional, execute `docker compose --profile painel up -d --build --wait` e abra [localhost:8788](http://localhost:8788). Gere uma chave com `--admin` para administrar chaves e fontes pelo painel.
- Para oferecer a API em outro computador, configure domínio, HTTPS e credenciais individuais conforme o [guia de implantação](docs/deployment.md).

## Consultas para experimentar

Use os campos da tabela no JSON de `POST /api/consultas`.

| Operação | Fonte | Campos |
|---|---|---|
| `municipio` | `ibge` | `codigo_ibge: 2507507` para João Pessoa |
| `fiscais` | `siconfi` | `ano: 2024`, `codigo_ibge: 2507507`, `demonstrativo: "DCA"`, `anexo: "DCA-Anexo I-D"` |
| `licitacoes` | `pncp` | `uf: "PB"`, `modalidade: 6`, `data_inicial: "2025-09-01"`, `data_final: "2025-09-05"` |
| `atas` | `pncp` | `identificador: "15126437000305-1-002417/2025"` |
| `fornecedor` | `compras` | `cnpj: "00000000000191"` |

A cobertura varia conforme a fonte, o órgão e o período. Veja a [matriz de implementação](IMPLEMENTATION_STATUS.md) e os [limites das fontes](docs/sources.md).

## Documentação

- [Arquitetura](docs/architecture.md)
- [Banco, cache e retenção](docs/database.md)
- [Segurança](docs/security.md)
- [Implantação e atualização](docs/deployment.md)
- [Testes](docs/testing.md)

GovBR MCP é um projeto independente. A [licença MIT](LICENSE) se aplica ao código. Os dados seguem os termos de cada fonte oficial.
