import { ChevronDown, PackageOpen } from 'lucide-react'
import type { Service } from '../api/types'

type ServiceSelectProps = {
  services: Service[]
  value: string
  loading: boolean
  error: string | null
  disabled: boolean
  onChange: (serviceId: string) => void
}

export function ServiceSelect({ services, value, loading, error, disabled, onChange }: ServiceSelectProps) {
  const placeholder = disabled
    ? 'Сначала выберите отделение'
    : loading
      ? 'Загружаем услуги…'
      : 'Выберите нужную услугу'

  return (
    <div className="form-field">
      <label htmlFor="service-select">Услуга</label>
      <div className="select-wrap">
        <PackageOpen className="select-leading-icon" size={19} aria-hidden="true" />
        <select
          id="service-select"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled || loading || Boolean(error)}
          required
        >
          <option value="">{placeholder}</option>
          {services.map((service) => (
            <option key={service.id} value={service.id}>{service.name}</option>
          ))}
        </select>
        <ChevronDown className="select-chevron" size={18} aria-hidden="true" />
      </div>
      {error && <p className="field-message error" role="alert">{error}</p>}
      {!error && disabled && <p className="field-message hint">Список зависит от выбранного отделения</p>}
    </div>
  )
}
