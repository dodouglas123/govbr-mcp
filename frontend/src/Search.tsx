import { Download, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, brl, describeError, download, localDate, operations, ufs } from './api'
import type { Evidence, HistoryDetail, Results, Source } from './api'
import { Empty, External, Notice, Section, State } from './components'

type Input = Record<string, string>
const dates = ['contratos', 'licitacoes', 'atas', 'despesas', 'empenhos', 'liquidacoes', 'pagamentos', 'transferencias', 'convenios', 'sancoes', 'preco_material']
const years = ['contratos', 'licitacoes', 'despesas', 'empenhos', 'liquidacoes', 'pagamentos', 'fiscais', 'receitas', 'emendas']
const numbers = new Set(['codigo_ibge', 'ano', 'periodo', 'ente_fiscal', 'modalidade', 'pagina', 'limite', 'codigo_material'])
const idHint: Record<string, string> = { contrato: 'CNPJ-2-000001/2025', documentos: 'CNPJ-1-000001/2025', atas: 'CNPJ-1-000001/2025', sancoes: 'ceis ou cnep' }

export default function SearchView({token, sources, detail, onQuery}: {token: string; sources: Source[]; detail?: HistoryDetail; onQuery: () => void}) {
  const [input, setInput] = useState<Input>({operacao: 'contratos', limite: '15'})
  const [result, setResult] = useState<Results>()
  const [resultFilters, setResultFilters] = useState<Input>()
  const [evidence, setEvidence] = useState<Evidence>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [hash, setHash] = useState('')

  useEffect(() => {
    if (!detail) return
    setResult(detail.response)
    const filters = Object.fromEntries(Object.entries(detail.request).filter(([,v]) => v != null).map(([k, v]) => [k, String(v)]))
    setInput(filters)
    setResultFilters(filters)
    setEvidence(undefined)
  }, [detail])

  function pick(name: string, value: string) {
    setInput(prev => name === 'operacao' ? {operacao: value, limite: '15'} : {...prev, [name]: value})
  }

  async function run(params: Input) {
    setBusy(true); setError(''); setEvidence(undefined)
    const compare = params.operacao === 'comparar_gastos'
    const block = compare ? new Set(['operacao', 'limite']) : new Set<string>()
    const body = Object.fromEntries(Object.entries(params).filter(([k,v]) => !block.has(k) && v.trim() && !(params.operacao === 'atas' && params.identificador && ['data_inicial','data_final'].includes(k)))
      .map(([k, v]) => [k, numbers.has(k) ? Number(v) : v.trim()]))
    try {
      const response = await api<Results>(token, compare ? '/api/comparar' : '/api/consultas', {
        method: 'POST', body: JSON.stringify(body),
      })
      setResult(response)
      setResultFilters(params)
      onQuery()
    } catch (err) { setError(describeError(err)) }
    finally { setBusy(false) }
  }

  async function showEvidence(id: string) {
    setHash(''); setError('')
    try { setEvidence(await api<Evidence>(token, `/api/evidencias/${id}`)) }
    catch (err) { setError(describeError(err)) }
  }

  async function exportResult(format: 'csv' | 'json') {
    if (!result) return
    try { await download(token, `/api/consultas/${result.consulta_id}/exportar?formato=${format}`, `govbr-${result.consulta_id}.${format}`) }
    catch (err) { setError(describeError(err)) }
  }

  function field(label: string, name: string, type = 'text', placeholder?: string) {
    return <label key={name}>{label}<input type={type} placeholder={placeholder} value={input[name] ?? ''}
      onChange={event => pick(name, event.target.value)} /></label>
  }
  function selectField(label: string, name: string, options: string[], captions: Record<string, string> = {}, all = 'Selecione') {
    return <label key={name}>{label}<select value={input[name] ?? ''} onChange={event => pick(name, event.target.value)}>
      <option value="">{all}</option>{options.map(value => <option key={value} value={value}>{captions[value] ?? value}</option>)}</select></label>
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void run(input)
  }

  const op = input.operacao
  const compare = op === 'comparar_gastos'
  const allowedSources = sources.filter(source => source.capacidades.includes(op) && source.habilitada)
  const shouldShowId = ['contrato', 'documentos', 'aditivos', 'atas', 'sancoes', 'convenios', 'emendas'].includes(op)
  return <div className="stack">
    <Section title="Filtros da consulta" actions={<button className="link" onClick={() => setInput({
      operacao: 'licitacoes', fonte: 'pncp', uf: 'PB', data_inicial: '2025-09-01', data_final: '2025-09-05', modalidade: '6', limite: '10',
    })}>Carregar exemplo PNCP</button>}>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>Operação<select value={op} onChange={event => pick('operacao', event.target.value)}>
            {Object.entries(operations).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {compare ? <>
            {selectField('UF A', 'uf_a', ufs)}{selectField('UF B', 'uf_b', ufs)}{field('Ano', 'ano', 'number')}
            {selectField('Função', 'funcao', ['06','10','12'], {'06':'Segurança pública','10':'Saúde','12':'Educação'})}
            {selectField('Estágio', 'fase', ['empenhada','liquidada','paga'])}
          </> : <>
            <label>Fonte<select value={input.fonte ?? ''} onChange={event => pick('fonte', event.target.value)}>
              <option value="">Seleção automática</option>{allowedSources.map(source => <option key={source.id} value={source.id}>{source.nome}</option>)}</select></label>
            {selectField('Esfera', 'esfera', ['F','E','M','D'], {F:'Federal', E:'Estadual', M:'Municipal', D:'Distrital'}, 'Todas')}
            {selectField('UF', 'uf', ufs, {}, 'Todas')}
            {field('Código IBGE', 'codigo_ibge', 'number', '2507507')}
            {op !== 'municipio' && field('CNPJ do fornecedor', 'cnpj', 'text', '00.000.000/0000-00')}
            {dates.includes(op) && !(op === 'atas' && input.identificador) && field('Data inicial', 'data_inicial', 'date')}
            {dates.includes(op) && !(op === 'atas' && input.identificador) && field('Data final', 'data_final', 'date')}
            {years.includes(op) && field('Ano', 'ano', 'number', '2025')}
            {['despesas', 'empenhos', 'liquidacoes', 'pagamentos', 'fiscais', 'receitas'].includes(op) && field('Mês ou período fiscal', 'periodo', 'number')}
            {op === 'licitacoes' && field('Modalidade PNCP', 'modalidade', 'number', '6')}
            {op === 'preco_material' && field('Código CATMAT', 'codigo_material', 'number')}
            {shouldShowId && field('Identificador', 'identificador', 'text', idHint[op])}
            {op === 'municipio' && field('Nome do município', 'texto', 'search')}
          </>}
        </div>
        {!compare && <details className="filter-details"><summary>Filtros avançados</summary><div className="form-grid">
          {field('Código do órgão / UG', 'codigo_orgao')}{field('CNPJ do órgão', 'cnpj_orgao')}
          {!shouldShowId && field('Identificador', 'identificador')}{op !== 'municipio' && field('Texto', 'texto', 'search')}
          {field('Valor mínimo', 'valor_minimo')}{field('Valor máximo', 'valor_maximo')}
          {field('Página', 'pagina', 'number')}{field('Registros por página', 'limite', 'number')}
          {['fiscais', 'receitas'].includes(op) && <>
            {selectField('Demonstrativo', 'demonstrativo', ['DCA','RREO','RGF'])}{field('Anexo', 'anexo')}
            {field('Ente fiscal', 'ente_fiscal', 'number')}{field('Poder', 'poder')}{selectField('Periodicidade', 'periodicidade', ['Q','S'])}
          </>}
        </div></details>}
        <div className="form-footer"><button className="primary" disabled={busy}><Search size={16} />{busy ? 'Consultando…' : 'Consultar'}</button></div>
      </form>
    </Section>
    <Notice text={error} />
    {result && <Section title={`Resultados (${result.registros.length})`} actions={<div className="actions">
      <button className="secondary" onClick={() => exportResult('csv')}><Download size={14} /> CSV</button>
      <button className="secondary" onClick={() => exportResult('json')}><Download size={14} /> JSON</button>
    </div>}>
      <div className="result-meta"><State value={result.estado} /><span>{localDate(result.consultado_em)}</span></div>
      {!!result.registros.length && <div className="scroll"><table><thead><tr>
        <th>Fonte</th><th>Órgão e registro</th><th>Valor</th><th>Data</th><th>Evidência</th>
      </tr></thead><tbody>{result.registros.map((row, i) => <tr key={row.evidencia_id ?? i}>
        <td>{sources.find(source => source.id === row.fonte)?.nome ?? row.fonte}</td>
        <td className="record-title"><strong>{row.titulo}</strong><div className="muted">{row.orgao ?? row.id_original}</div></td>
        <td className="amount">{brl(row.valor)}{row.natureza_valor && <div className="muted">{row.natureza_valor.replaceAll('_', ' ')}</div>}</td>
        <td>{localDate(row.data_publicacao ?? row.competencia)}</td>
        <td>{row.evidencia_id && <button className="link" onClick={() => void showEvidence(row.evidencia_id!)}>Ver evidência</button>}
          <div><External url={row.url_oficial}>Original</External></div></td>
      </tr>)}</tbody></table></div>}
      {!result.registros.length && <Empty>Nenhum registro nesta página. Confira a situação de cada fonte.</Empty>}
      {result.calculo && <details open className="inline-details"><summary>Método e resultado da comparação</summary><pre>{JSON.stringify(result.calculo, null, 2)}</pre></details>}
      {!!result.fontes.length && <details className="inline-details" open><summary>Respostas das fontes</summary>
        <ul className="source-results">{result.fontes.map((source, index) => <li key={`${source.fonte}:${index}`}>
          <div><strong>{sources.find(item => item.id === source.fonte)?.nome ?? source.fonte}</strong> <State value={source.estado} />
            <span className="muted"> Página {source.pagina} · {source.registros_utilizados}/{source.registros_recebidos} registros · {source.cache ? 'Cache' : 'Consulta'} </span></div>
          <div className="muted">{source.avisos.join(' ')}</div>
          {source.proxima_pagina && <button className="link" disabled={busy}
            onClick={() => void run({...(resultFilters ?? input), fonte: source.fonte, pagina: String(source.proxima_pagina)})}>Próxima página</button>}
        </li>)}</ul>
      </details>}
      <ul className="warnings">{result.avisos.map(note => <li key={note}>{note}</li>)}</ul>
      {!!(result.relacoes.length + result.divergencias.length) && <details className="inline-details"><summary>Relações e divergências</summary>
        <pre>{JSON.stringify({relacoes: result.relacoes, divergencias: result.divergencias}, null, 2)}</pre></details>}
    </Section>}
    {evidence && <Section title="Evidência" actions={<button className="secondary" onClick={() => setEvidence(undefined)}>Fechar</button>}>
      <dl className="key-values">
        <dt>Origem</dt><dd><External url={evidence.url}>Abrir fonte oficial</External></dd>
        <dt>Consulta enviada</dt><dd><External url={evidence.request_url}>Abrir requisição oficial</External></dd>
        <dt>Identificador</dt><dd>{evidence.upstream_id}</dd><dt>Coleta</dt><dd>{localDate(evidence.captured_at)}</dd>
        <dt>SHA-256 da resposta</dt><dd className="mono">{evidence.sha256}</dd>
        {hash && <><dt>SHA-256 do PDF</dt><dd className="mono">{hash}</dd></>}
      </dl>
      {evidence.dataset === 'documentos' && <button className="secondary" onClick={async () => {
        try { setHash(await download(token, `/api/evidencias/${evidence.id}/pdf`, `pncp-${evidence.id}.pdf`) ?? '') }
        catch (err) { setError(describeError(err)) }
      }}><Download size={15} /> Baixar PDF original</button>}
      <details className="inline-details"><summary>Filtros, extrato e transformações</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>
    </Section>}
  </div>
}
