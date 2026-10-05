import { Icon, ICON_NAMES } from '../components/Icon/index.ts'
import styles from './Catalog.module.css'
import { CATALOG_SECTIONS, COLOR_GROUPS, LAYOUT, RADII, SPACES, TYPE_SCALE } from './catalogTokens.ts'
import { ComponentsDemo } from './ComponentsDemo.tsx'
import { QDemo } from './QDemo.tsx'
import { ShellDemo } from './ShellDemo.tsx'
import { StatesDemo } from './StatesDemo.tsx'
import { safeHref } from '../security/safeHref.ts'

function ColorsSection() {
  return (
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
  )
}

function TypographySection() {
  return (
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
  )
}

function MeasuresSection() {
  return (
    <section className={styles.section} aria-labelledby="medidas">
      <h2 id="medidas" className={styles.sectionTitle}>
        Forma y medidas
      </h2>

      <h3 className={styles.groupTitle}>Radios</h3>
      <ul className={styles.radii}>
        {RADII.map((radius) => (
          <li key={radius.token} className={styles.radiusItem}>
            <span className={styles.radiusSample} style={{ borderRadius: `var(${radius.token})` }} />
            <span className={styles.token}>{radius.token}</span>
            <span className={`${styles.muted} tabular-nums`}>{radius.value}</span>
            <span className={styles.muted}>{radius.use}</span>
          </li>
        ))}
      </ul>

      <h3 className={styles.groupTitle}>Espaciado</h3>
      <ul className={styles.spaces}>
        {SPACES.map((space) => (
          <li key={space} className={styles.spaceItem}>
            <span className={`${styles.token} tabular-nums`}>{space}</span>
            <span className={styles.spaceBar} style={{ width: `var(${space})` }} />
          </li>
        ))}
      </ul>

      <h3 className={styles.groupTitle}>Layout y controles</h3>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Token</th>
            <th scope="col">Valor</th>
            <th scope="col">Uso</th>
          </tr>
        </thead>
        <tbody>
          {LAYOUT.map((item) => (
            <tr key={item.token}>
              <td className={styles.token}>{item.token}</td>
              <td className="tabular-nums">{item.value}</td>
              <td className={styles.muted}>{item.use}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function IconsSection() {
  return (
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
  )
}

// Catálogo del sistema de diseño (T-56): revisión visual de todas las piezas, con datos sintéticos.
export function Catalog() {
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Sistema de diseño · Propuesta mixta</h1>
        <p className={styles.lead}>
          Piezas del frontend del Agente AF y QA. Las decisiones están en web/DESIGN-DECISIONS.md y todos los
          datos son ficticios.
        </p>
        <nav aria-label="Secciones del catálogo">
          <ul className={styles.toc}>
            {CATALOG_SECTIONS.map((section) => (
              <li key={section.id}>
                <a className={styles.tocLink} href={safeHref(`#${section.id}`)}>
                  {section.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <ColorsSection />
      <TypographySection />
      <MeasuresSection />
      <IconsSection />
      <QDemo />
      <ShellDemo />
      <ComponentsDemo />
      <StatesDemo />
    </main>
  )
}
