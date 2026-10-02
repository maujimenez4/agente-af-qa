import { Icon } from '../Icon/index.ts'
import { QLogo } from '../QMark/index.ts'
import styles from './Rail.module.css'
import { railItemsFor, ROLE_NAMES, USAGE_RADIUS, USAGE_WARNING, usageDash, type Role, type Zone } from './railItems.ts'

export interface RailProps {
  userRole: Role
  username: string
  active: Zone
  onNavigate: (zone: Zone) => void
  onLogout: () => void
  /** Consumo diario de tokens en %. Opcional: el contrato aún no lo da (PA-305). Sin dato, no se pinta. */
  usagePercent?: number
}

// Carril lateral de 88 px (UI.md §2): logotipo, zonas según el rol, consumo, usuario y salir.
export function Rail({ userRole, username, active, onNavigate, onLogout, usagePercent }: RailProps) {
  const initial = username.charAt(0).toUpperCase()

  return (
    <nav className={styles.rail} aria-label="Zonas">
      <QLogo size={34} label="Agente AF y QA" className={styles.logo} />

      <ul className={styles.items}>
        {railItemsFor(userRole).map((item) => (
          <li key={item.zone}>
            <button
              type="button"
              className={styles.item}
              aria-current={item.zone === active ? 'page' : undefined}
              onClick={() => onNavigate(item.zone)}
            >
              <Icon name={item.icon} size={24} />
              <span>{item.label}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className={styles.spacer} />

      {usagePercent !== undefined && <UsageRing percent={usagePercent} />}

      <div className={styles.avatar} role="img" aria-label={`${username}, ${ROLE_NAMES[userRole]}`}>
        <span aria-hidden="true">{initial}</span>
      </div>

      <button type="button" className={styles.logout} aria-label="Cerrar sesión" onClick={onLogout}>
        <Icon name="logout" size={24} />
      </button>
    </nav>
  )
}

function UsageRing({ percent }: { percent: number }) {
  const rounded = Math.round(Math.min(Math.max(percent, 0), 100))
  return (
    <div className={styles.usage} role="img" aria-label={`Consumo diario de tokens: ${rounded} %`}>
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
          strokeDasharray={usageDash(rounded)}
          transform="rotate(-90 18 18)"
          data-warning={rounded >= USAGE_WARNING ? '' : undefined}
        />
      </svg>
      <span className="tabular-nums" aria-hidden="true">
        {rounded}&nbsp;% tokens
      </span>
    </div>
  )
}
