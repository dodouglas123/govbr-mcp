import { Check, Copy, Plus, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, describeError, localDate } from './api'
import type { Session } from './api'
import { Empty, Notice, Section, State } from './components'

type Key = {id: string; label: string; scopes: string[]; created_at: string; revoked_at?: string}
type Config = {cgu_configurada: boolean; oauth_configurado: boolean; requests_per_minute: number; query_concurrency: number;
  history_days: number; evidence_days: number; document_max_mib: number}
type Event = {id: string; action: string; created_at: string; data: Record<string, unknown>}
const tabs = ['Chaves de API', 'Limites', 'Auditoria'] as const
type Tab = typeof tabs[number]

export default function Admin({token, session}: {token: string; session: Session}) {
  const [tab, setTab] = useState<Tab>('Chaves de API')
  const [keys, setKeys] = useState<Key[]>([])
  const [config, setConfig] = useState<Config>()
  const [events, setEvents] = useState<Event[]>([])
  const [create, setCreate] = useState(false)
  const [newKey, setNewKey] = useState('')
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(false)
  const [copied, setCopied] = useState(false)

  const refresh = useCallback(async () => {
    setChecking(true)
    try {
      if (tab === 'Chaves de API') {
        const [list, info] = await Promise.all([
          api<Key[]>(token, '/api/admin/chaves'), api<Config>(token, '/api/admin/config'),
        ])
        setKeys(list); setConfig(info)
      } else if (tab === 'Limites') setConfig(await api<Config>(token, '/api/admin/config'))
      else setEvents(await api<Event[]>(token, '/api/admin/auditoria'))
    } catch (err) { setError(describeError(err)) }
    finally { setChecking(false) }
  }, [token, tab])
  useEffect(() => { void refresh() }, [refresh])

  async function grant(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(''); setNewKey(''); setCopied(false)
    const data = new FormData(event.currentTarget)
    try {
      const result = await api<{token: string}>(token, '/api/admin/chaves', {
        method: 'POST', body: JSON.stringify({label: data.get('label'), admin: data.get('admin') === 'on'}),
      })
      setNewKey(result.token); setCreate(false); await refresh()
    } catch (err) { setError(describeError(err)) }
  }

  async function revoke(key: Key) {
    if (!window.confirm(`Revogar a chave “${key.label}”?`)) return
    try { await api(token, `/api/admin/chaves/${key.id}`, {method: 'DELETE'}); await refresh() }
    catch (err) { setError(describeError(err)) }
  }

  return <div className="stack">
    <nav className="tabs" aria-label="Administração">{tabs.map(item => <button key={item} aria-current={tab === item ? 'page' : undefined}
      className={tab === item ? 'active' : ''} onClick={() => {setTab(item); setError('')}}>{item}</button>)}</nav>
    <Notice text={error} />
    {tab === 'Chaves de API' && <>
      <Section title={`Chaves de API (${keys.filter(key => !key.revoked_at).length})`} actions={<button className="primary" onClick={() => setCreate(true)}><Plus size={16} /> Nova chave</button>}>
        {!!newKey && <div className="new-key"><label>Copie a nova chave<input readOnly value={newKey} /></label>
          <button className="secondary" onClick={async () => {
            try { await navigator.clipboard.writeText(newKey); setCopied(true) }
            catch { setError('Selecione e copie o valor no campo.') }
          }}>{copied ? <Check size={15} /> : <Copy size={15} />} {copied ? 'Copiada' : 'Copiar'}</button>
          <button className="link" onClick={() => setNewKey('')}>Ocultar</button></div>}
        {create && <form className="compact-row" onSubmit={grant}>
          <label>Descrição<input name="label" required maxLength={100} /></label>
          <label className="checkbox"><input type="checkbox" name="admin" /> Acesso administrativo</label>
          <button className="primary">Criar</button><button className="secondary" type="button" onClick={() => setCreate(false)}>Cancelar</button>
        </form>}
        <div className="scroll"><table><thead><tr><th>Descrição</th><th>Escopos</th><th>Criada em</th><th>Status</th><th>Ação</th></tr></thead>
          <tbody>{keys.map(key => <tr key={key.id}><td><strong>{key.label}</strong></td>
            <td>{key.scopes.join(', ')}</td><td>{localDate(key.created_at)}</td>
            <td><State value={key.revoked_at ? 'Revogada' : 'operacional'} /></td>
            <td>{!key.revoked_at && session.id !== `token:${key.id}` && <button className="link danger" onClick={() => void revoke(key)}>Revogar</button>}</td>
          </tr>)}</tbody></table></div>
      </Section>
      <Section title="Conexões">
        <dl className="key-values"><dt>Endpoint MCP</dt><dd className="mono">{session.mcp}</dd>
          <dt>Chave da CGU</dt><dd>{config?.cgu_configurada ? 'Configurada' : 'Pendente · GOVBR_CGU_KEY'}</dd>
          <dt>OAuth</dt><dd>{config?.oauth_configurado ? 'Configurado' : 'Opcional · origem e provedor externos'}</dd>
        </dl>
      </Section>
    </>}
    {tab === 'Limites' && <Section title="Limites e retenção">
      <dl className="key-values">
        <dt>Requisições por usuário</dt><dd>{config?.requests_per_minute ?? '—'} por minuto</dd>
        <dt>Consultas simultâneas</dt><dd>{config?.query_concurrency ?? '—'}</dd>
        <dt>PDF original</dt><dd>{config?.document_max_mib ?? '—'} MiB por arquivo</dd>
        <dt>Histórico</dt><dd>{config?.history_days ?? '—'} dias</dd>
        <dt>Evidências</dt><dd>{config?.evidence_days ?? '—'} dias</dd>
      </dl>
    </Section>}
    {tab === 'Auditoria' && <Section title="Eventos recentes" actions={<button className="secondary" onClick={refresh} disabled={checking}><RefreshCw size={15} /> Atualizar</button>}>
      {!events.length ? <Empty>Nenhum evento registrado.</Empty> : <div className="scroll"><table>
        <thead><tr><th>Evento</th><th>Data</th><th>Detalhes</th></tr></thead><tbody>{events.map(row => <tr key={row.id}>
          <td>{row.action.replaceAll('_', ' ')}</td><td>{localDate(row.created_at)}</td><td><details><summary>Ver detalhes</summary><pre>{JSON.stringify(row.data, null, 2)}</pre></details></td>
        </tr>)}</tbody>
      </table></div>}
    </Section>}
  </div>
}
