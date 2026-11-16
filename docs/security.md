# Segurança

- A configuração pública exige origem HTTPS. A instalação inicial publica o serviço em loopback. O transporte MCP valida Host e Origin.
- Chaves individuais usam 288 bits de entropia e ficam no banco como hash SHA-256. O painel mostra a chave apenas na emissão. Chaves de clientes de IA devem receber `govbr:read`.
- OAuth valida assinatura, emissor, audiência, validade, escopo e sujeitos permitidos em produção. `/.well-known/oauth-protected-resource/mcp` anuncia o servidor de autorização configurado. A administração usa chaves individuais.
- Todas as consultas aos portais usam GET ou HEAD. Endereços são construídos em conectores. A camada de rede valida hostname e DNS público, bloqueia redirecionamentos e limita bytes, prazo e tentativas.
- O proxy de saída, quando configurado, deve ser operado pelo mesmo responsável. Reforce o bloqueio de redes privadas e metadados de nuvem no firewall de produção.
- Extratos usam allowlists de campos e minimização de CPF e nomes de credores PF. Campos livres ainda podem mencionar dados pessoais. Evite inserir dados pessoais em consultas e notas quando a finalidade não exigir.
- PDFs são tratados como anexos externos com origem, mídia e assinatura de arquivo verificadas. São armazenados por hash e servidos com `Content-Disposition: attachment` e `nosniff`. O conteúdo do PDF fica fora do contexto automático do MCP.
- O MCP indica que itens de portais são dados externos. A interface renderiza texto escapado e o CSV protege contra fórmulas. Trate texto oficial recebido como conteúdo de pesquisa.
- Limites por usuário, PostgreSQL privado, logs sem segredos, retenção configurável e atualização com lockfiles integram a operação.

Use apenas uma chave CGU autorizada. Respeite os limites documentados e os termos de cada portal. A validação de schema e a retenção apoiam a minimização operacional. Ajuste a configuração à finalidade e à legislação aplicável antes de redistribuir dados. [LGPD, texto oficial](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm).
