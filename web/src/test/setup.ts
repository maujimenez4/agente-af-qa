import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { setCsrfToken } from '../api/client.ts'
import { mockServer, resetMockApi } from '../mocks/node.ts'

// API simulada para todas las pruebas: una petición sin handler es un error, no una llamada real.
beforeAll(() => {
  mockServer.listen({ onUnhandledFrame: 'error' })
})

beforeEach(() => {
  resetMockApi()
  setCsrfToken(null)
})

afterEach(() => {
  cleanup()
})

afterAll(() => {
  mockServer.close()
})
