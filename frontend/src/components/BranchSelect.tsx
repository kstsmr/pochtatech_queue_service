import { ChevronDown, MapPin } from 'lucide-react'
import type { Branch } from '../api/types'

type BranchSelectProps = {
  branches: Branch[]
  value: string
  loading: boolean
  error: string | null
  onChange: (branchId: string) => void
  hint?: string
}

export function BranchSelect({ branches, value, loading, error, onChange, hint }: BranchSelectProps) {
  const helpId = 'branch-select-help'

  return (
    <div className="form-field">
      <label htmlFor="branch-select">Отделение</label>
      <div className="select-wrap">
        <MapPin className="select-leading-icon" size={19} aria-hidden="true" />
        <select
          id="branch-select"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={loading || Boolean(error)}
          aria-describedby={error || hint ? helpId : undefined}
          required
        >
          <option value="">{loading ? 'Загружаем отделения…' : 'Выберите адрес отделения'}</option>
          {branches.map((branch) => (
            <option key={branch.id} value={branch.id}>
              {branch.postal_code} — {branch.address}
            </option>
          ))}
        </select>
        <ChevronDown className="select-chevron" size={18} aria-hidden="true" />
      </div>
      {error && <p id={helpId} className="field-message error" role="alert">{error}. Проверьте, что backend запущен.</p>}
      {!error && hint && <p id={helpId} className="field-message hint">{hint}</p>}
    </div>
  )
}
