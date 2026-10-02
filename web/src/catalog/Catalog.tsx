import styles from './Catalog.module.css'
import { COLOR_GROUPS, TYPE_SCALE } from './catalogTokens.ts'

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
    </main>
  )
}
