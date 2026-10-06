// API simulada en el navegador: solo con `npm run dev` y VITE_API_MOCK=1 (src/main.tsx).
import { setupWorker } from 'msw/browser'
import type { ConnectionsTestOut } from '../api/types.ts'
import { example } from './examples.ts'
import { connectionDownFrom, createMockDb, forcedApprovalFrom, forcedCoverageFrom, manyConversations, manyConversationsFrom, memoryMissingFrom, noMemoriesFrom, takenFrom } from './db.ts'
import { createHandlers } from './handlers.ts'

export async function startMockApi(): Promise<void> {
  const db = createMockDb()
  // Revisión en el navegador de casos que la pantalla no provoca sola (web/README.md, «API simulada»).
  db.forceApprove = forcedApprovalFrom(window.location.search)
  db.forceTaken = takenFrom(window.location.search)
  db.forceCoverage = forcedCoverageFrom(window.location.search)
  if (noMemoriesFrom(window.location.search)) db.memories = []
  db.skipPublishedMemory = memoryMissingFrom(window.location.search)
  if (connectionDownFrom(window.location.search)) db.connections = example<ConnectionsTestOut>('POST /api/v1/admin/connections/test 200')
  const [first] = db.conversations
  if (first && manyConversationsFrom(window.location.search)) db.conversations = manyConversations(first)
  const worker = setupWorker(...createHandlers(db))
  await worker.start({ serviceWorker: { url: '/mockServiceWorker.js' }, onUnhandledFrame: 'bypass', quiet: true })
}
