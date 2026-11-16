# Persistência e retenção

| Estrutura | Finalidade |
|---|---|
| `sources` | Catálogo, status, latência e TTL por API |
| `record_versions` | Versões por fonte, conjunto, identificador e hash do extrato |
| `evidence` | URL de consulta, URL do registro, datas, filtros, hash e extrato |
| `documents` | PDF original pelo SHA-256, com referência à evidência |
| `query_cache` | Páginas consultadas com expiração |
| `query_history` | Filtros, resultados e métricas por usuário |
| `investigations`, `investigation_queries` | Casos, notas e consultas vinculadas |
| `access_tokens`, `rate_limits`, `audit_events` | Chaves protegidas por hash, limites de requisição e administração |

As consultas trazem páginas das APIs oficiais sob demanda. O cache tem TTL por fonte. As evidências mantêm a data de coleta original e possuem retenção contada a partir da persistência. O backend roda a limpeza periódica, e o histórico vinculado a investigações segue a mesma retenção das outras consultas.

O banco guarda colunas específicas de cada origem em JSONB. Valores financeiros usam decimais, serializados como texto no JSON. Competência, publicação, atualização na fonte e coleta são campos distintos.

A migração 0002 exclui as antigas importações SAGRES e sua fila. Consultas que combinaram o SAGRES com APIs oficiais mantêm as respostas das APIs.
