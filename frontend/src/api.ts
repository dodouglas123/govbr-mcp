export type Source = {
  id: string; nome: string; orgao: string; esferas: string[]; uf: string | null;
  oficial: string; documentacao: string; acesso: string; formato: string; autenticacao: string;
  atualizacao: string; limite: string; restricoes: string; capacidades: string[];
  estado: string; habilitada: boolean; ttl: number; ttl_ativo: number; ultima_consulta_ok: string | null;
  ultimo_erro: string | null; ultimo_erro_em: string | null; latencia_ms: number | null;
}
export type RecordRow = {
  fonte: string; conjunto: string; id_original: string; tipo: string; titulo: string;
  esfera?: string; uf?: string; codigo_ibge?: number; cnpj?: string; orgao?: string;
  valor?: string; moeda?: string; natureza_valor?: string; data_publicacao?: string; competencia?: string;
  url_oficial: string; evidencia_id?: string; atributos: Record<string, unknown>;
}
export type SourceResult = {
  fonte: string; estado: string; pagina: number; proxima_pagina?: number; erro?: string;
  cache: boolean; registros_recebidos: number; registros_utilizados: number; total_na_fonte?: number;
  consultado_em?: string; avisos: string[];
}
export type Results = {
  consulta_id: string; estado: string; operacao: string; consultado_em: string; registros: RecordRow[];
  fontes: SourceResult[]; avisos: string[]; relacoes: Record<string, unknown>[];
  divergencias: Record<string, unknown>[]; calculo?: Record<string, unknown>;
}
export type History = {
  id: string; operation: string; state: string; created_at: string;
  duration_ms: number; sources: number; request: Record<string, unknown>;
}
export type HistoryDetail = History & {response: Results}
export type Dashboard = {
  consultas: number; latencia_media_ms: number | null; acertos: number; fontes_consultadas: number;
  erros: number; banco_bytes: number; limite_req_min: number; fontes_operacionais: number;
  fontes: Source[]; recentes: History[];
}
export type Evidence = {
  id: string; source_id: string; dataset: string; upstream_id: string; url: string; request_url: string;
  captured_at: string; sha256: string; original: Record<string, unknown>; normalized: RecordRow;
  transforms: string[]; limitations: string[]; filters: Record<string, unknown>;
  documentos: {sha256: string; downloaded_at: string}[];
}
export type Case = {id: string; title: string; notes: string; status: 'aberta' | 'concluida'; updated_at: string; queries: string[]}
export type Session = {id: string; scopes: string[]; mcp: string}

export const operations: Record<string, string> = {
  contratos: 'Contratos', contrato: 'Contrato por ID', aditivos: 'Termos e aditivos', licitacoes: 'Licitações',
  atas: 'Atas', fornecedor: 'Fornecedor por CNPJ', sancoes: 'Sanções por CNPJ', despesas: 'Despesas',
  empenhos: 'Empenhos', liquidacoes: 'Liquidações', pagamentos: 'Pagamentos', transferencias: 'Transferências',
  convenios: 'Convênios', emendas: 'Emendas', fiscais: 'Demonstrativos fiscais', receitas: 'Receitas',
  orgao: 'Órgãos', municipio: 'Municípios', documentos: 'Documentos PNCP', preco_material: 'Preços de materiais',
  comparar_gastos: 'Comparar gastos entre UFs',
}
export const states: Record<string, string> = {
  operacional: 'Operacional', nao_verificada: 'A verificar', planejada: 'Planejada', credencial_pendente: 'Chave pendente',
  indisponivel: 'Indisponível', desativada: 'Desativada', ok: 'OK', vazio: 'Sem registros', erro: 'Erro',
  incompleto: 'Incompleto', parcial: 'Parcial', aberta: 'Em andamento', concluida: 'Concluída',
  aguardando: 'Aguardando', agendado: 'Agendado', executando: 'Em execução', concluido: 'Concluído', falhou: 'Falhou',
}
export const ufs = 'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split(' ')

export async function api<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  return (await request(token, path, init)).json() as Promise<T>
}

async function request(token: string, path: string, init?: RequestInit): Promise<globalThis.Response> {
  const headers = new Headers(init?.headers)
  headers.set('Authorization', `Bearer ${token}`)
  if (init?.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, {...init, headers, cache: 'no-store'})
  if (response.ok) return response
  const data = await response.json().catch(() => ({}))
  const errors = Array.isArray(data.campos) ? data.campos.map((field: {campo: string; mensagem: string}) =>
    `${field.campo.replace(/^body\./, '')} · ${field.mensagem}`).join(' | ') : null
  throw new Error(errors || data.mensagem || (typeof data.detail === 'string' ? data.detail : null) || `Erro HTTP ${response.status}`)
}

export async function download(token: string, path: string, filename: string) {
  const response = await request(token, path)
  saveBlob(await response.blob(), filename)
  return response.headers.get('X-Content-SHA256')
}

export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(href), 1500)
}

export function localDate(value?: string | null): string {
  if (!value) return '—'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.split('-').reverse().join('/')
  const date = new Date(value)
  return Number.isNaN(+date) ? value : new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Sao_Paulo',
  }).format(date)
}

export function brl(value?: string): string {
  if (value == null) return '—'
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value)
  if (!match) return value
  const [, sign, integer, fraction = ''] = match
  return `${sign}R$ ${BigInt(integer).toLocaleString('pt-BR')},${fraction.padEnd(2, '0')}`
}

export function officialLink(value?: string) {
  if (!value) return undefined
  try {
    const link = new URL(value)
    if (link.protocol === 'https:' && !link.username && !link.password) return link.href
  } catch { /* registro sem link público utilizável */ }
}

export const describeError = (error: unknown) => error instanceof Error ? error.message : 'A operação falhou.'
