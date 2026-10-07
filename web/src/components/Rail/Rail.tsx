import { useId } from 'react'
import { Icon } from '../Icon/index.ts'
import { QLogo } from '../QMark/index.ts'
import styles from './Rail.module.css'
import {
  railItemsFor,
  ROLE_NAMES,
  USAGE_RADIUS,
  usageDash,
  usageView,
  type RailItem,
  type Role,
  type UsageToday,
  type Zone,
} from './railItems.ts'

export interface RailProps {
  userRole: Role
  username: string
  active: Zone
  onNavigate: (zone: Zone) => void
  onLogout: () => void
  /** Consumo de hoy de toda la instalación (`GET /settings/usage`). Sin dato válido, no hay anillo. */
  usage?: UsageToday
}

// Carril lateral de 88 px (UI.md §2): logotipo, zonas según el rol, consumo, usuario y salir.
export function Rail({ userRole, username, active, onNavigate, onLogout, usage }: RailProps) {
  const initial = username.charAt(0).toUpperCase()
  const view = usageView(usage)

  return (
    <nav className={styles.rail} aria-label="Zonas">
      <QLogo size={34} label="Agente AF y QA" className={styles.logo} />

      <ul className={styles.items}>
        {railItemsFor(userRole).map((item) => (
          <li key={item.zone}>
            <RailButton item={item} active={item.zone === active} onNavigate={onNavigate} />
          </li>
        ))}
      </ul>

      <div className={styles.spacer} />

      {view && (
        // El `title` repite el nombre accesible: al pasar el ratón se lee qué mide (decisión 17).
        <div className={styles.usage} role="img" aria-label={view.label} title={view.label}>
          <svg viewBox="0 0 36 36" width="36" height="36" aria-hidden="true" focusable="false">
            <circle className={styles.usageTrack} cx="18" cy="18" r={USAGE_RADIUS} fill="none" strokeWidth="4" />
            <circle
              className={styles.usageValue}
              cx="18"
              cy="18"
              r={USAGE_RADIUS}
              fill="none"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={usageDash(view.percent)}
              transform="rotate(-90 18 18)"
              data-warning={view.warning ? '' : undefined}
            />
          </svg>
          <span className={`${styles.usageText} tabular-nums`} aria-hidden="true">
            {view.percent}&nbsp;%
            <span className={styles.usageScope}>consumo total</span>
          </span>
        </div>
      )}

      <div className={styles.avatar} role="img" aria-label={`${username}, ${ROLE_NAMES[userRole]}`}>
        <span aria-hidden="true">{initial}</span>
      </div>

      <button type="button" className={styles.logout} aria-label="Cerrar sesión" onClick={onLogout}>
        <Icon name="logout" size={24} />
      </button>
    </nav>
  )
}

function RailButton({ item, active, onNavigate }: { item: RailItem; active: boolean; onNavigate: (zone: Zone) => void }) {
  const soonId = useId()
  if (item.soon) {
    return (
      <>
        <button type="button" className={styles.item} aria-disabled="true" aria-describedby={soonId}>
          <Icon name={item.icon} size={24} />
          <span>{item.label}</span>
          <span className={styles.soon} aria-hidden="true">
            Pronto
          </span>
        </button>
        <span id={soonId} className="visually-hidden">
          Disponible pronto
        </span>
      </>
    )
  }
  return (
    <button
      type="button"
      className={styles.item}
      aria-current={active ? 'page' : undefined}
      onClick={() => onNavigate(item.zone)}
    >
      <Icon name={item.icon} size={24} />
      <span>{item.label}</span>
    </button>
  )
}
