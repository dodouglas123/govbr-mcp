import { Download, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, describeError, localDate, operations, saveBlob } from './api'
import type { Case, History, HistoryDetail } from './api'
import { Empty, HistoryTable, Notice, Section, State } from './components'

export default function Investigations({token, onOpen}: {token: string; onOpen:(id: string) => void}) {
  const [cases, setCases] = useState<Case[]>([])
  const [history, setHistory] = useState<History[]>([])
  const [filter, setFilter] = useState('')
  const [status, setStatus] = useState('')
  const [id, setId] = useState('')
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const [offset, setOffset] = useState(0)
  const selected = cases.find(item => item.id === id)
  const [attached, setAttached] = useState<History[]>([])

  const refresh = useCallback(async () => {
    try {
      const [items, past] = await Promise.all([
        api<Case[]>(token, '/api/investigacoes'), api<History[]>(token, `/api/consultas?offset=${offset}`),
      ])
      setCases(items); setHistory(past)
    } catch (err) { setError(describeError(err)) }
  }, [token, offset])
  useEffect(() => { void refresh() }, [refresh])
  const queryIds = (selected?.queries ?? []).join(',')
  useEffect(() => {
    let active = true
    setAttached([])
    if (!queryIds) return
    Promise.all(queryIds.split(',').slice(0, 20).map(id => api<HistoryDetail>(token, `/api/consultas/${id}`)))
      .then(items => { if (active) setAttached(items) }).catch(error => { if (active) setError(describeError(error)) })
    return () => { active = false }
  }, [token, queryIds])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    const data = new FormData(event.currentTarget)
    try {
      const result = await api<{id: string}>(token, id ? `/api/investigacoes/${id}` : '/api/investigacoes', {
        method: id ? 'PUT' : 'POST', body: JSON.stringify(Object.fromEntries(data)),
      })
      setId(result.id); setEditing(false); await refresh()
    } catch (err) { setError(describeError(err)) }
  }
  async function link(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      await api(token, `/api/investigacoes/${id}/consultas`, {method: 'POST', body: JSON.stringify({consulta_id: data.get('consulta_id')})})
      await refresh()
    } catch (err) { setError(describeError(err)) }
  }
  async function report() {
    if (!selected) return
    try {
      const items: HistoryDetail[] = []
      for (const id of selected.queries) items.push(await api<HistoryDetail>(token, `/api/consultas/${id}`))
      saveBlob(new Blob([JSON.stringify({investigacao: selected, consultas: items}, null, 2)], {type:'application/json'}),
        `investigacao-${selected.id}.json`)
    } catch (err) { setError(describeError(err)) }
  }
  const visible = cases.filter(row => (!status || row.status === status) && row.title.toLowerCase().includes(filter.toLowerCase()))
  return <div className="stack">
    <Notice text={error} />
    <Section title="Pesquisas salvas" actions={<button className="primary" onClick={() => {setId(''); setEditing(true)}}><Plus size={16} /> Nova investigação</button>}>
      <div className="compact-row">
        <label>Status<select value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">Todos</option><option value="aberta">Em andamento</option><option value="concluida">Concluída</option></select></label>
        <label>Buscar investigação<input value={filter} type="search" onChange={event => setFilter(event.target.value)} /></label>
      </div>
      {visible.length ? <div className="scroll"><table><thead><tr><th>Investigação</th><th>Última atualização</th><th>Consultas</th><th>Status</th></tr></thead>
        <tbody>{visible.map(row => <tr key={row.id}><td><button className="link" onClick={() => {setId(row.id); setEditing(false)}}>{row.title}</button></td>
          <td>{localDate(row.updated_at)}</td><td>{row.queries.length}</td><td><State value={row.status} /></td></tr>)}</tbody></table></div> :
        <Empty>Nenhuma investigação para exibir.</Empty>}
    </Section>
    {editing && <Section title={id ? 'Editar investigação' : 'Nova investigação'}>
      <form key={id} onSubmit={save}>
        <div className="form-grid"><label>Título<input name="title" required maxLength={160} defaultValue={selected?.title} /></label>
          <label>Status<select name="status" defaultValue={selected?.status ?? 'aberta'}><option value="aberta">Em andamento</option>
            <option value="concluida">Concluída</option></select></label></div>
        <label>Notas<textarea name="notes" maxLength={4000} defaultValue={selected?.notes} rows={4} /></label>
        <div className="form-footer"><button className="secondary" type="button" onClick={() => setEditing(false)}>Cancelar</button><button className="primary">Salvar</button></div>
      </form>
    </Section>}
    {selected && !editing && <Section title={selected.title} actions={<div className="actions">
      <button className="secondary" onClick={() => setEditing(true)}>Editar</button>
      <button className="secondary" onClick={() => void report()}><Download size={14} /> Exportar relatório</button>
    </div>}>
      {selected.notes && <p className="case-notes">{selected.notes}</p>}
      <form className="compact-row" onSubmit={link}><label>Vincular do histórico
        <select required name="consulta_id"><option value="">Selecione uma consulta</option>{history.filter(row => !selected.queries.includes(row.id)).map(row =>
          <option key={row.id} value={row.id}>{operations[row.operation] ?? row.operation} · {localDate(row.created_at)}</option>)}</select>
      </label><button className="secondary">Vincular</button></form>
      <HistoryTable items={attached} open={onOpen} />
    </Section>}
    <Section title="Histórico de consultas" actions={<div className="actions">
      <button className="secondary" disabled={offset === 0} onClick={() => setOffset(value => value - 20)}>Anterior</button>
      <button className="secondary" disabled={history.length < 20} onClick={() => setOffset(value => value + 20)}>Próxima</button>
    </div>}><HistoryTable items={history} open={onOpen} /></Section>
  </div>
}
