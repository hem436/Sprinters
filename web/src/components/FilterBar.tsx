import type { MetricsFilters } from '../api/types'

const ROUTES = ['DOCS', 'SQL', 'BOTH', 'CONVERSATIONAL', 'BLOCKED']
const OUTCOMES = ['SUCCESS', 'PARTIAL', 'FAILED']

/** Filters shared by the dashboard and the query list (contract 11 section 9). */
export function FilterBar({ value, onChange }: { value: MetricsFilters; onChange: (f: MetricsFilters) => void }) {
  const set = (patch: Partial<MetricsFilters>) => onChange({ ...value, ...patch })
  return (
    <div className="card mb-5 grid grid-cols-2 gap-3 p-3 sm:grid-cols-3 lg:grid-cols-6">
      <label>
        <span className="label">From</span>
        <input type="date" className="input" value={value.from ?? ''} onChange={(e) => set({ from: e.target.value || undefined })} />
      </label>
      <label>
        <span className="label">To</span>
        <input type="date" className="input" value={value.to ?? ''} onChange={(e) => set({ to: e.target.value || undefined })} />
      </label>
      <label>
        <span className="label">Config</span>
        <select className="input" value={value.config_id ?? ''} onChange={(e) => set({ config_id: e.target.value as MetricsFilters['config_id'] })}>
          <option value="">All</option>
          <option value="A">A</option>
          <option value="B">B</option>
        </select>
      </label>
      <label>
        <span className="label">Route</span>
        <select className="input" value={value.route ?? ''} onChange={(e) => set({ route: e.target.value as MetricsFilters['route'] })}>
          <option value="">All</option>
          {ROUTES.map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </label>
      <label>
        <span className="label">Outcome</span>
        <select className="input" value={value.outcome ?? ''} onChange={(e) => set({ outcome: e.target.value as MetricsFilters['outcome'] })}>
          <option value="">All</option>
          {OUTCOMES.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </select>
      </label>
      <div className="flex items-end">
        <button type="button" className="btn-secondary w-full" onClick={() => onChange({})}>
          Clear filters
        </button>
      </div>
    </div>
  )
}
