# Testes e aceite

## Suíte automatizada

Em `backend`, instale `requirements-dev.txt` e execute.

```bash
python -m pytest -q
ruff check govbr tests
```

Para a suíte integral, crie um banco de testes separado e aponte `GOVBR_DATABASE_URL` para ele ao aplicar a migração com `python -m govbr migrate`. Aponte `GOVBR_TEST_DATABASE_URL` para o mesmo banco ao executar os testes. A suíte grava registros transitórios de teste, chaves de teste e eventos isolados por usuário.

| Camada | O que é verificado |
|---|---|
| Núcleo | CNPJ numérico e alfanumérico, datas, UF, IBGE, paginação, valores Decimais e duplicatas |
| Conectores | HTTP 429, retry de timeout, mudanças de schema, credencial ausente e consultas sem filtro upstream inventado |
| Segurança | URLs externas e DNS privado, redirecionamento, assinatura OAuth, audiência e validade, ACL, CSV e escape de conteúdo |
| PostgreSQL | Migração, persistência, cache, histórico por usuário e anexos |
| REST | OpenAPI, autenticação Bearer, remoção de rotas antigas e limite do corpo em streaming |
| MCP | Descoberta, schema estruturado, consulta autenticada e rejeição de origem inválida |

## Cliente para conferência real

```bash
cd backend
python ../examples/sdk_smoke.py --stdio
python ../examples/sdk_smoke.py --url http://localhost:8787/mcp --live
```

O segundo comando usa `GOVBR_TEST_TOKEN` no ambiente de execução. Ele inicia uma sessão com o SDK oficial, descobre as ferramentas, consulta as fontes e verifica SHA-256, URLs e histórico para cada resultado. Saídas JSON por linha permitem registrar as requisições e repetir os recortes.

Para uma reprodução manual, abra o painel, autentique-se com a mesma chave do cliente MCP e abra **Investigações → Histórico de consultas**. Selecione a consulta e confira a evidência. O teste de CNPJ, credenciais, registros e fontes é local e de leitura.

Depois de configurar a CGU, use **Fontes → Portal da Transparência → Verificar conexão**. A validação exige chave individual autorizada. Os resultados observados na entrega estão em [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).
