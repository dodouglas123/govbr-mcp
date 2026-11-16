# Clientes e ferramentas MCP

## Cliente local por stdio

Copie [stdio-windows.json](../examples/stdio-windows.json) e ajuste o caminho do projeto. No Cursor, o arquivo do projeto fica em `.cursor/mcp.json` ou o arquivo global em `~/.cursor/mcp.json`. No Claude Desktop, use **Configurações → Desenvolvedor → Editar configuração** e reinicie o aplicativo. Com Docker Compose ativo, o cliente abre um processo stdio dentro do contêiner do backend. [Cursor](https://cursor.com/docs/mcp) · [Claude Desktop](https://modelcontextprotocol.io/docs/develop/connect-local-servers).

O stdio herda a autorização do usuário que executa o comando local. Sua identidade de histórico é local. Para que duas aplicações compartilhem histórico com o painel, use Streamable HTTP e a mesma chave individual.

## Cliente remoto

O endpoint é `https://mcp.seudominio.com/mcp`. Para Cursor local ou remoto com cabeçalho, use [cursor-http.json](../examples/cursor-http.json) e uma chave de leitura. Proteja o arquivo de configuração e evite colocá-lo em controle de versão.

No Claude, abra **Personalizar → Conectores → Adicionar → Personalizado → Web**. Informe a URL HTTPS. A opção de cabeçalhos aceita `Authorization` com valor `Bearer <chave-de-leitura>`. OAuth é outra opção de conexão quando a instalação dispõe de um provedor configurado. [Anthropic](https://support.claude.com/pt/articles/11176164-use-connectors-to-extend-claude-s-capabilities).

No ChatGPT, workspaces elegíveis podem usar **Plugins → Adicionar servidor MCP personalizado**, informar a URL HTTPS ou um Secure MCP Tunnel autorizado e configurar OAuth. A documentação descreve conexões personalizadas para Business e Enterprise/Edu e acesso de leitura no Pro. A disponibilidade depende do plano e da política do workspace. [OpenAI Help Center](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) · [Guia de integração](https://developers.openai.com/api/docs/guides/custom-mcp-server).

## Ferramentas

O servidor publica schemas de entrada e saída em `tools/list`. As ferramentas de pesquisa recebem `filtros`, com `fonte` opcional, `pagina` de 1 a 1000 e `limite` de 1 a 50. CGU usa `limite=15`. Datas são `YYYY-MM-DD`, e alguns conectores consultam exercício ou competência em vez de data. A próxima página é informada por fonte.

| Ferramentas | Filtros principais |
|---|---|
| `gov_listar_fontes`, `gov_listar_capacidades`, `gov_verificar_disponibilidade` | UF de interesse ou ID da fonte |
| `gov_pesquisar_contratos` | PNCP com datas, Dados PB com ano, Compras com órgão e datas, CGU com CNPJ ou órgão |
| `gov_consultar_contrato`, `gov_consultar_aditivos` | Identificador de controle PNCP ou ID da CGU |
| `gov_pesquisar_licitacoes`, `gov_consultar_atas` | PNCP com datas e modalidade nas licitações, controle PNCP tipo 1 ou intervalo para atas, Dados PB com ano |
| `gov_consultar_empresa`, `gov_consultar_fornecedor` | CNPJ exato no cadastro ativo do Compras |
| `gov_consultar_sancoes` | CNPJ exato e `identificador` CEIS ou CNEP, em minúsculas |
| `gov_consultar_despesas`, `gov_consultar_empenhos`, `gov_consultar_liquidacoes`, `gov_consultar_pagamentos` | Período compatível com a fonte. Para CGU por CNPJ, informe ano. |
| `gov_consultar_transferencias`, `gov_consultar_convenios`, `gov_consultar_emendas` | CGU. Intervalo mensal de recursos recebidos, filtros por convênio ou ano da emenda |
| `gov_consultar_receitas`, `gov_consultar_dados_fiscais`, `gov_comparar_gastos` | Ano e ente fiscal. Comparação DCA de duas UFs por função e estágio. |
| `gov_consultar_orgao`, `gov_consultar_municipio` | Código SIAFI/descrição ou código IBGE/UF |
| `gov_consultar_precos_materiais` | Código CATMAT |
| `gov_investigar_empresa`, `gov_cruzar_contratacoes` | CNPJ, ano, datas dentro de até 90 dias, UF ou município opcionais |
| `gov_consultar_documentos`, `gov_obter_evidencias`, `gov_status_consulta` | Controle PNCP, UUID da evidência ou UUID da consulta |

### Exemplos de entrada

```json
{"filtros":{"fonte":"pncp","uf":"PB","modalidade":6,"data_inicial":"2025-09-01","data_final":"2025-09-05","limite":10}}
```

Use com `gov_pesquisar_licitacoes`. Para avançar, informe a mesma fonte e `pagina` igual à `proxima_pagina`.

```json
{"filtros":{"fonte":"siconfi","ano":2024,"codigo_ibge":2507507,"demonstrativo":"DCA","anexo":"DCA-Anexo I-D","limite":5}}
```

Use com `gov_consultar_dados_fiscais`.

```json
{"uf_a":"PB","uf_b":"PE","ano":2024,"funcao":"12","fase":"empenhada"}
```

Use com `gov_comparar_gastos`. Códigos `06`, `10` e `12` representam segurança pública, saúde e educação.

### Saída e falhas

As buscas devolvem `consulta_id`, `estado`, `consultado_em`, `registros`, `fontes`, `avisos`, `relacoes` e `divergencias`. Cada registro tem fonte, identificador, tipo, datas, URL e UUID de evidência. O estado `parcial` sinaliza falha em parte do plano, `incompleto` sinaliza limitação do recorte e `vazio` indica uma página verificada sem registros. `proxima_pagina` exige nova chamada e `total_na_fonte` usa o total informado pelo portal.

Códigos de fonte incluem `credencial_ausente`, `filtros_obrigatorios`, `filtro_sem_suporte`, `limite_fonte`, `timeout` e `schema_fonte`. O campo `erro` vem acompanhado de aviso textual. Entradas fora do schema geram erro de ferramenta MCP. O histórico da consulta é acessível pelo próprio usuário autenticado.
