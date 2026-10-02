import { lazy, Suspense } from 'react'
import { AppShell } from './app/AppShell.tsx'
import styles from './app/AppShell.module.css'
import { LoadingQ } from './components/QMark/index.ts'
import { useSession } from './session/sessionContext.ts'
import { SessionProvider } from './session/SessionProvider.tsx'

// Catálogo del sistema de diseño: solo en desarrollo y con ?catalogo (PA-309). En el build,
// import.meta.env.DEV es false y el import dinámico desaparece del bundle.
const CatalogPage = import.meta.env.DEV
  ? lazy(() => import('./catalog/Catalog.tsx').then((module) => ({ default: module.Catalog })))
  : null

function wantsCatalog(): boolean {
  return new URLSearchParams(window.location.search).has('catalogo')
}

export function App() {
  if (CatalogPage && wantsCatalog()) {
    return (
      <Suspense fallback={null}>
        <CatalogPage />
      </Suspense>
    )
  }
  return (
    <SessionProvider>
      <Root />
    </SessionProvider>
  )
}

function Root() {
  const { state } = useSession()
  if (state.status === 'loading') {
    return (
      <div className={styles.loading}>
        <LoadingQ done={0} running label="Cargando" />
      </div>
    )
  }
  if (state.status === 'anonymous') {
    return (
      <main className={styles.loading}>
        <h1>Inicia sesión</h1>
      </main>
    )
  }
  return <AppShell user={state.user} />
}
