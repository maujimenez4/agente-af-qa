import { Icon, ICON_NAMES } from '../components/Icon/index.ts'
import styles from './Catalog.module.css'
import { COLOR_GROUPS, TYPE_SCALE } from './catalogTokens.ts'
import { QDemo } from './QDemo.tsx'

// Catálogo del sistema de diseño (T-56): página de revisión visual de las piezas.
export function Catalog() {
  return (
    <main className={styles.page}>
      <header>
        <h1 className={styles.title}>Sistema de diseño · Propuesta mixta</h1>
        <p className={styles.lead}>
          Piezas del frontend del Agente AF y QA. Decisiones en web/DESIGN-DECISIONS.md.
        </p>
      </header>

      <QDemo />

      <section className={styles.section} aria-labelledby="colores">
        <h2 id="colores" className={styles.sectionTitle}>
          Colores
        </h2>
        {COLOR_GROUPS.map((group) => (
          <div key={group.title} className={styles.section}>
            <h3 className={styles.groupTitle}>{group.title}</h3>
            <ul className={styles.swatches}>
              {group.colors.map((color) => (
                <li key={color.token} className={styles.swatch}>
                  <div className={styles.chip} style={{ background: `var(${color.token})` }} />
                  <div className={styles.swatchText}>
                    <span className={styles.token}>{color.token}</span>
                    <span className={`${styles.muted} tabular-nums`}>{color.hex}</span>
                    <span className={styles.muted}>{color.role}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className={styles.section} aria-labelledby="tipografia">
        <h2 id="tipografia" className={styles.sectionTitle}>
          Tipografía · DM Sans
        </h2>
        <div>
          {TYPE_SCALE.map((step) => (
            <div key={step.token} className={styles.typeRow}>
              <span className={`${styles.muted} tabular-nums`}>{step.token}</span>
              <span style={{ fontSize: `var(${step.token})`, fontWeight: `var(${step.weight})` }}>{step.sample}</span>
            </div>
          ))}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="iconos">
        <h2 id="iconos" className={styles.sectionTitle}>
          Iconos
        </h2>
        <ul className={styles.icons}>
          {ICON_NAMES.map((name) => (
            <li key={name} className={styles.iconCard}>
              <Icon name={name} size={32} />
              <span className={styles.muted}>{name}</span>
            </li>
          ))}
        </ul>
        <h3 className={styles.groupTitle}>Sobre navy: reposo, hover y zona activa</h3>
        <div className={styles.navySample}>
          <Icon name="work" size={24} className={styles.onNavy} />
          <Icon name="history" size={24} className={styles.onNavyHover} />
          <Icon name="settings" size={24} className={styles.onNavyActive} />
        </div>
      </section>
    </main>
  )
}
