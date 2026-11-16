# Fontes e cobertura

| Fonte | Recortes e contrato de acesso | Documentação |
|---|---|---|
| PNCP | Pública. Contratos pela publicação. Licitações exigem modalidade. Contrato, termos, atas vinculadas à contratação e documentos por controle PNCP. UF, código IBGE, esfera e CNPJ do fornecedor são filtros locais para contratos. | [Swagger de consulta](https://pncp.gov.br/api/consulta/swagger-ui/index.html) · [Manual](https://pncp.gov.br/manual/pt-br/latest/) |
| SICONFI | Pública. DCA anual, RREO por bimestre e RGF por período, poder e periodicidade. Limite oficial de 1 req/s. | [Tesouro Nacional](https://apidatalake.tesouro.gov.br/docs/siconfi/) |
| Compras.gov.br | Pública nos módulos usados. Contratos por órgão e início da vigência, fornecedor ativo por CNPJ e preço unitário observado por CATMAT. | [Swagger](https://dadosabertos.compras.gov.br/swagger-ui/index.html) |
| IBGE | Pública. Cadastro de localidades por UF e código IBGE. | [API de Localidades](https://servicodados.ibge.gov.br/api/docs/localidades) |
| Dados PB | Pública. Despesas, empenhos, liquidações, pagamentos e receitas por competência. Contratos por início da vigência e licitações por exercício. | [API da Paraíba](https://api.dados.pb.gov.br/swagger/) · [Catálogo](https://dados.pb.gov.br/dataset/despesas) |
| CGU | Chave individual via cabeçalho `chave-api-dados`. Executivo Federal. Paginação fixa registrada por fonte. | [Swagger](https://api.portaldatransparencia.gov.br/swagger-ui/index.html) · [Catálogo federal](https://www.gov.br/conecta/catalogo/apis/portal-da-transparencia-do-governo-federal) |
| Prefeitura de João Pessoa | Consulta direta em portal web catalogada. PNCP, SICONFI e IBGE oferecem recortes do município. | [Portal municipal](https://transparencia.joaopessoa.pb.gov.br/) |

O cache usa TTL independente por fonte e operação. Um recorte disponível no catálogo pode ter lacunas, retificação ou retenção histórica própria. O campo `total_na_fonte` reproduz a contagem upstream antes dos filtros locais. Uma tela com página vazia e continuação exige percorrer as páginas.

## Fontes catalogadas para expansão

| Fonte | Interface ou formato | Validação pendente |
|---|---|---|
| TCU | Conjuntos públicos e serviços por sistema | Contrato e licença de cada conjunto |
| Banco Central | Catálogo público e séries com metadados | Série, janela e granularidade por ferramenta |
| Câmara | API e bases para download | Contrato por recurso e cadência |
| Senado | APIs e bases por área | Autorização, cobertura e atualização por serviço |
| TSE | Arquivos de dados abertos | Licenças, período eleitoral e minimização |
| INEP | Microdados e sinopses por edição | Identificadores, dicionários e limites por dataset |
| DATASUS | Arquivos por sistema e competência | Contrato, minimização e granularidade |
| Dados.gov.br | API REST de catálogo e metadados | Autorização e termos por recurso |

A licença MIT se aplica ao código. A redistribuição de dados segue os termos da fonte oficial.
