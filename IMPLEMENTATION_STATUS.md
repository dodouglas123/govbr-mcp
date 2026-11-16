# Estado de implementação · GovBR MCP 0.2.0

| Fonte | Consultas disponíveis | Limites |
|---|---|---|
| PNCP | Licitações, contratos, termos, atas e documentos vinculados. | A busca de atas por identificador da contratação tem um recorte menor que a busca por vigência. Contratos usam filtros locais para fornecedor, município, UF e esfera. |
| SICONFI | DCA, RREO, RGF e comparação fiscal entre UFs por função e etapa. | A disponibilidade depende da declaração do ente. A comparação usa o mesmo anexo e exercício para os dois entes. |
| Compras.gov.br | Contratos, cadastro de fornecedor e preços praticados por CATMAT. | Compare preços da mesma unidade de fornecimento. |
| IBGE | Municípios por código ou UF. | Cadastro territorial. |
| Dados Abertos da Paraíba | Despesas e receitas estaduais, empenhos, liquidações, pagamentos, contratos e licitações. | Os dados são do governo estadual. Cada operação tem seu próprio recorte de exercício ou competência. |
| CGU | Contratos, licitações, gastos, sanções, transferências, convênios, emendas e órgãos federais. | Requer chave individual. A fonte permanece com credencial pendente até receber uma chave válida. |

Buscas são feitas sob demanda. Use o campo `estado` de cada fonte para interpretar resultados parciais, vazios ou indisponíveis. A [lista de fontes](docs/sources.md) aponta a documentação oficial e o [guia de testes](docs/testing.md) mostra como reproduzir consultas.

REST e MCP Streamable HTTP usam chaves de leitura individuais. Stdio está disponível em ambiente local. HTTPS e OAuth JWT são configurações opcionais de implantação. A integração OAuth com um provedor e um cliente reais depende das credenciais de cada implantação.
