import { ExternalLink, Search } from 'lucide-react'
import type { ReactNode } from 'react'
import { localDate, officialLink, operations, states } from './api'
import type { History, Source } from './api'

export function State({value}: {value: string}) {
  return <span className={`state state-${value}`}>{states[value] ?? value}</span>
}

export function Section({title, actions, children}: {title: string; actions?: ReactNode; children: ReactNode}) {
  return <section className="panel"><div className="panel-title"><h2>{title}</h2>{actions}</div>{children}</section>
}

export function Empty({children}: {children: ReactNode}) {
  return <div className="empty"><Search size={24} strokeWidth={1.6} /><p>{children}</p></div>
}

export function Notice({text, kind = 'error'}: {text?: string; kind?: 'error' | 'info'}) {
  return text ? <p role={kind === 'error' ? 'alert' : 'status'} className={`notice ${kind}`}>{text}</p> : null
}

export function External({url, children}: {url?: string; children: ReactNode}) {
  const target = officialLink(url)
  return target ? <a href={target} target="_blank" rel="noreferrer noopener" className="external">{children}<ExternalLink size={13} /></a> : null
}

export function HistoryTable({items, open}: {items: History[]; open: (id: string) => void}) {
  if (!items.length) return <Empty>Nenhuma consulta no histórico.</Empty>
  return <div className="scroll"><table><thead><tr><th>Operação</th><th>Data e hora</th><th>Resultado</th></tr></thead>
    <tbody>{items.map(row => <tr key={row.id}>
      <td><button className="link" onClick={() => open(row.id)}>{operations[row.operation] ?? row.operation}</button></td>
      <td>{localDate(row.created_at)}</td><td><State value={row.state} /></td>
    </tr>)}</tbody></table></div>
}

export function SourceTable({sources, test}: {sources: Source[]; test?: (source: Source) => void}) {
  return <div className="scroll"><table className={test ? "sources-table with-actions" : "sources-table"}>
    <thead><tr><th>Fonte</th><th>Cobertura</th><th>Situação</th><th>Última consulta</th>{test && <th>Ações</th>}</tr></thead>
    <tbody>{sources.map(source => <tr key={source.id}>
      <td><strong>{source.nome}</strong>{test && <div className="muted">{source.orgao}</div>}</td>
      <td>{source.uf ?? (source.esferas.length > 1 ? 'Nacional' : 'Federal')}</td>
      <td><State value={source.estado} /></td><td>{localDate(source.ultima_consulta_ok)}</td>
      {test && <td><button className="secondary" onClick={() => test(source)}>Detalhes</button></td>}
    </tr>)}</tbody>
  </table></div>
}
