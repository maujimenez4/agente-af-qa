import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App.tsx'
import './styles/fonts.ts'
import './styles/tokens.css'
import './styles/base.css'

async function start() {
  // API simulada (MSW) solo en desarrollo y con VITE_API_MOCK=1. El import dinámico la deja fuera del build.
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCK === '1') {
    const { startMockApi } = await import('./mocks/browser.ts')
    await startMockApi()
  }

  const root = document.getElementById('root')
  if (!root) throw new Error('No se encuentra el elemento #root en index.html.')

  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
