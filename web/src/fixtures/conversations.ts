import type { ConversationSummaryView } from '../components/ConversationList/index.ts'

// Datos sintéticos (proyecto DEMO de la biblioteca ficticia de Villaficticia), para pruebas y catálogo.
export const DEMO_NOW = new Date(2026, 9, 2, 16, 0)

export const DEMO_CONVERSATIONS: ConversationSummaryView[] = [
  {
    thread_id: '00000000-0000-4000-8000-000000000001',
    project_key: 'DEMO',
    mode: 'functional',
    origin_kind: 'story',
    origin_key: 'DEMO-3',
    title: 'Renovar un préstamo desde la app',
    status: 'published',
    version: 2,
    updated_at: new Date(2026, 9, 2, 15, 47).toISOString(),
  },
  {
    thread_id: '00000000-0000-4000-8000-000000000002',
    project_key: 'DEMO',
    mode: 'qa',
    origin_kind: 'story',
    origin_key: 'DEMO-3',
    title: 'Suite de pruebas de DEMO-3',
    status: 'in_review',
    version: 1,
    updated_at: new Date(2026, 9, 2, 11, 5).toISOString(),
  },
  {
    thread_id: '00000000-0000-4000-8000-000000000003',
    project_key: 'SOCI',
    mode: 'functional',
    origin_kind: 'need',
    origin_key: null,
    title: 'Alta de persona socia en línea',
    status: 'in_review',
    version: 2,
    updated_at: new Date(2026, 9, 1, 18, 30).toISOString(),
  },
  {
    thread_id: '00000000-0000-4000-8000-000000000004',
    project_key: 'DEMO',
    mode: 'functional',
    origin_kind: 'epic',
    origin_key: 'DEMO-1',
    title: 'Historial de préstamos de 12 meses',
    status: 'simulated',
    version: 1,
    updated_at: new Date(2026, 8, 30, 10, 0).toISOString(),
  },
]
