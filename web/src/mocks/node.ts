// API simulada para Vitest. Cada prueba parte de un estado nuevo con `resetMockApi()`.
import { setupServer } from 'msw/node'
import { createMockDb, type MockDb } from './db.ts'
import { createHandlers } from './handlers.ts'

export let mockDb: MockDb = createMockDb({ stepDelayMs: 0 })

export const mockServer = setupServer(...createHandlers(mockDb))

export function resetMockApi(): MockDb {
  mockDb = createMockDb({ stepDelayMs: 0 })
  mockServer.resetHandlers(...createHandlers(mockDb))
  return mockDb
}
