import { Database, House, Search, ClipboardList, Settings, Plus, LogOut, KeyRound, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, describeError, localDate, operations } from './api'
import type { Dashboard, HistoryDetail, Session, Source } from './api'
import { Empty, External, Notice, Section, SourceTable, State } from './components'
import SearchView from './Search'
import Admin from './Admin'
import Investigations from './Investigations'

const panels = [
  ['overview', 'Visão geral', House], ['sources', 'Fontes', Database], ['search', 'Consultas', Search],
  ['cases', 'Investigações', ClipboardList], ['admin', 'Administração', Settings],
] as const
type Panel = typeof panels[number][0]

export default function App() {
  const [session, setSession] = useState<Session>()
  const [token, setToken] = useState('')
  const [panel, setPanel] = useState<Panel>('overview')
  const [stats, setStats] = useState<Dashboard>()
  const [selected, setSelected] = useState<HistoryDetail>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const admin = !!session?.scopes.includes('govbr:admin')

  const refresh = useCallback(async () => {
    if (!session) return
    try { setStats(await api<Dashboard>(token, '/api/dashboard')) }
    catch (error) { setError(describeError(error)) }
  }, [session, token])
  useEffect(() => { void refresh() }, [refresh])

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    const key = String(new FormData(event.currentTarget).get('key')).trim()
    try {
      const data = await api<Session>(key, '/api/me')
      setToken(key)
      setPanel('overview')
      setSession(data)
    } catch (error) { setError(describeError(error)) }
    finally { setBusy(false) }
  }

  function navigate(next: Panel) {
    setError('')
    setSelected(undefined)
    setPanel(next)
    if (next === 'overview' || next === 'sources') void refresh()
  }

  async function open(id: string) {
    try {
      setSelected(await api<HistoryDetail>(token, `/api/consultas/${id}`))
      setPanel('search')
      setError('')
    } catch (error) { setError(describeError(error)) }
  }

  if (!session) return <div className="login">
    <section className="login-card">
      <div className="login-brand"><Database size={25} /> GovBR MCP</div>
      <h1>Acessar painel</h1>
      <form onSubmit={login}>
        <label>Chave do GovBR MCP<input name="key" required autoComplete="off" type="password" /></label>
        <Notice text={error} />
        <button className="primary" disabled={busy}><KeyRound size={16} /> {busy ? 'Verificando…' : 'Entrar'}</button>
      </form>
      <p className="muted">Emita a chave administrativa no terminal da instalação.</p>
    </section>
  </div>

  const title = panels.find(row => row[0] === panel)?.[1]
  const accessiblePanels = panels.filter(([id]) => id !== 'admin' || admin)
  return <div className="shell">
    <aside className="rail">
      <button className="brand" onClick={() => navigate('overview')} aria-label="GovBR MCP, visão geral">
        <Database size={30} strokeWidth={1.55} /><span><strong>GovBR MCP</strong><small>Dados públicos</small></span>
      </button>
      <nav aria-label="Navegação principal">
        {accessiblePanels.map(([id, label, Icon]) => <button key={id} className={panel === id ? 'active' : ''}
          aria-current={panel === id ? 'page' : undefined} onClick={() => navigate(id)}>
          <Icon size={18} strokeWidth={1.75} /><span>{label}</span>
        </button>)}
      </nav>
      <div className="rail-footer"><span>Projeto independente</span>
        <button className="rail-exit" onClick={() => {
          setSession(undefined); setToken(''); setStats(undefined); setSelected(undefined); setError('')
        }}><LogOut size={15} /> Sair</button>
      </div>
    </aside>
    <main className="workspace">
      <header className="page-header">
        <h1>{title}</h1>
        {panel === 'overview' && <button className="primary" onClick={() => navigate('search')}><Plus size={17} /> Nova consulta</button>}
      </header>
      <Notice text={error} />
      {panel === 'overview' && <Overview info={stats} open={open} refresh={refresh} />}
      {panel === 'sources' && <Sources items={stats?.fontes ?? []} token={token} admin={admin} refresh={refresh} />}
      {panel === 'search' && <SearchView token={token} sources={stats?.fontes ?? []} detail={selected} onQuery={refresh} />}
      {panel === 'cases' && <Investigations token={token} onOpen={open} />}
      {panel === 'admin' && <Admin token={token} session={session} />}
    </main>
  </div>
}

function Overview({info, open, refresh}: {info?: Dashboard; open: (id: string) => void; refresh: () => void}) {
  const percentage = (count: number, total: number) => total ? `${(100 * count / total).toLocaleString('pt-BR', {maximumFractionDigits: 1})}%` : '—'
  const values = [
    ['Fontes operacionais', info?.fontes_operacionais],
    ['Consultas', info?.consultas],
    ['Latência média', info?.latencia_media_ms != null ? `${info.latencia_media_ms} ms` : null],
    ['Acertos de cache', info && percentage(info.acertos, info.fontes_consultadas)],
  ]
  return <>
    <div className="metrics" aria-label="Indicadores do servidor">{values.map(([label, value]) =>
      <div className="metric" key={label}><span>{label}</span><strong>{value ?? '—'}</strong></div>)}</div>
    <div className="overview-grid">
      <Section title="Fontes de dados" actions={<button className="icon-button" aria-label="Atualizar indicadores" onClick={refresh}><RefreshCw size={15} /></button>}>
        {info ? <SourceTable sources={info.fontes.filter(s => s.estado !== 'planejada').sort((a, b) =>
          (['pncp', 'siconfi', 'cgu', 'dados_pb', 'compras', 'ibge'].indexOf(a.id)) -
          (['pncp', 'siconfi', 'cgu', 'dados_pb', 'compras', 'ibge'].indexOf(b.id)))} /> : <Empty>Carregando fontes.</Empty>}
      </Section>
      <Section title="Consultas recentes">
        {info?.recentes.length ? <ul className="activity">{info.recentes.map(row =>
          <li key={row.id}><button className="link" onClick={() => open(row.id)}>{operations[row.operation] ?? row.operation}</button>
            <div><span>{localDate(row.created_at)}</span><State value={row.state} /></div></li>)}</ul> :
          <Empty>Nenhuma consulta ainda.</Empty>}
      </Section>
    </div>
    {info && <div className="system-metrics"><span>Taxa de erros <strong>{percentage(info.erros, info.consultas)}</strong></span>
      <span>Banco <strong>{(info.banco_bytes / 1048576).toFixed(1)} MiB</strong></span>
      <span>Limite <strong>{info.limite_req_min} req/min</strong></span></div>}
  </>
}

function Sources({items, token, admin, refresh}: {items: Source[]; token: string; admin: boolean; refresh: () => void}) {
  const [sel, setSel] = useState<string>()
  const [filter, setFilter] = useState('todas')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const selected = items.find(s => s.id === sel)
  const visible = items.filter(s => filter === 'todas' || (filter === 'ativas' ? s.habilitada : s.estado === filter))

  async function test() {
    if (!selected) return
    setBusy(true); setNotice(''); setError('')
    try {
      const result = await api<{estado: string; mensagem?: string; status_http?: number}>(token, `/api/fontes/${sel}/verificar`, {method:'POST'})
      result.estado === 'ok' ? setNotice(`Fonte respondeu HTTP ${result.status_http}.`) : setError(result.mensagem ?? result.estado)
      await refresh()
    } catch (err) { setError(describeError(err)) }
    finally { setBusy(false) }
  }

  async function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    setBusy(true); setNotice(''); setError('')
    try {
      await api(token, `/api/fontes/${sel}`, {method: 'PUT', body: JSON.stringify({
        enabled: data.get('enabled') === 'on', ttl: data.get('ttl') ? Number(data.get('ttl')) : null,
      })})
      setNotice('Configuração atualizada.'); await refresh()
    } catch (err) { setError(describeError(err)) }
    finally { setBusy(false) }
  }

  return <div className="stack">
    <Section title="Catálogo de fontes" actions={<select aria-label="Filtrar fontes" value={filter} onChange={event => setFilter(event.target.value)}>
      <option value="todas">Todas</option><option value="ativas">Habilitadas</option><option value="operacional">Operacionais</option>
      <option value="planejada">Planejadas</option></select>}>
      <SourceTable sources={visible} test={source => { setSel(source.id); setError(''); setNotice('') }} />
    </Section>
    {selected && <Section title={selected.nome} actions={selected.habilitada &&
      <button className="secondary" disabled={busy} onClick={test}>Verificar conexão</button>}>
      <dl className="key-values">
        <dt>Documentação</dt><dd><External url={selected.documentacao}>Abrir documentação oficial</External></dd>
        <dt>Capacidades</dt><dd>{selected.capacidades.map(cap => operations[cap] ?? cap).join(', ') || 'A catalogar'}</dd>
        <dt>Acesso e formato</dt><dd>{selected.acesso} · {selected.formato}</dd>
        <dt>Autenticação</dt><dd>{selected.autenticacao}</dd><dt>Limite</dt><dd>{selected.limite}</dd>
        <dt>Atualização</dt><dd>{selected.atualizacao}</dd><dt>Cobertura</dt><dd>{selected.restricoes}</dd>
        <dt>Último erro</dt><dd>{selected.ultimo_erro ? `${selected.ultimo_erro} · ${localDate(selected.ultimo_erro_em)}` : '—'}</dd>
      </dl>
      {admin && selected.estado !== 'planejada' && <form className="compact-row" key={sel} onSubmit={update}>
        <label className="checkbox"><input type="checkbox" name="enabled" defaultChecked={selected.habilitada} /> Habilitada</label>
        <label>Cache em segundos<input type="number" name="ttl" min="0" max="86400" defaultValue={selected.ttl_ativo} /></label>
        <button disabled={busy} className="secondary">Salvar</button>
      </form>}
      <Notice text={error} /><Notice text={notice} kind="info" />
    </Section>}
  </div>
}
