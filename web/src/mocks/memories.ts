// Memorias de la API simulada (PA-329): los ejemplos del contrato (DEMO-9001, con su detalle, y DEMO-9002, solo en
// la lista). El detalle de DEMO-9002 se construye a partir del de DEMO-9001. Solo datos ficticios.
import type { components } from '../api/schema'
import type { MemoryOut, MemorySummary } from '../api/types.ts'
import { example } from './examples.ts'

export function mockMemorySummaries(): MemorySummary[] {
  return example<MemorySummary[]>('GET /api/v1/memories 200')
}

/** `.md` de la memoria, con el mismo formato que el del ejemplo (core/memory). */
export function memoryMarkdown(memory: MemoryOut['memory']): string {
  const list = (title: string, items: string[]) => [`## ${title}`, ...items.map((item) => `- ${item}`), '']
  return [
    '---',
    `jira_key: ${memory.jira_key}`,
    `artifact_type: ${memory.artifact_type}`,
    `version: ${memory.version}`,
    '---',
    '',
    `# Memoria · ${memory.jira_key} (v${memory.version})`,
    '',
    '## Objetivo',
    memory.objective,
    '',
    '## Alcance',
    memory.scope,
    '',
    ...list('Reglas de negocio', memory.business_rules),
    ...list('Decisiones', memory.decisions),
    ...list('Dependencias', memory.dependencies),
    ...list('Cambios', memory.changes),
    ...list('Criterios de aceptación', memory.acceptance_criteria),
    ...list('Referencias', memory.references),
  ].join('\n')
}

/** Detalle de cada memoria de la lista: el del ejemplo y, para las demás, uno hecho a partir de él. */
export function mockMemoryDetails(summaries: readonly MemorySummary[]): Map<string, MemoryOut> {
  const base = example<MemoryOut>('GET /api/v1/memories/{key} 200')
  const details = new Map<string, MemoryOut>([[base.key, base]])
  for (const summary of summaries) {
    if (details.has(summary.key)) continue
    const memory: MemoryOut['memory'] = {
      ...structuredClone(base.memory),
      jira_key: summary.key,
      version: summary.version,
      objective: summary.title,
      scope: `Memoria de ejemplo FICTICIA de ${summary.key}: no es una HU real.`,
      business_rules: ['RN-1: una reserva ficticia caduca a los 3 días de avisar a la persona socia.'],
      decisions: [],
      dependencies: [`${base.key}: renovación de préstamos (memoria de ejemplo).`],
      changes: [],
      acceptance_criteria: ['CA-1: al reservar un libro prestado, la persona socia queda en la cola de espera.'],
      references: [summary.key],
    }
    details.set(summary.key, { ...summary, memory, markdown: memoryMarkdown(memory) })
  }
  return details
}

/** Como `GET /memories`: proyecto exacto, `q` en la clave y en el texto (sin mayúsculas ni tildes) y `limit`. */
export function filterMemories(
  summaries: readonly MemorySummary[],
  details: ReadonlyMap<string, MemoryOut>,
  { project, q, limit }: { project: string | null; q: string; limit: number },
): MemorySummary[] {
  const fold = (text: string) => text.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
  const needle = fold(q.trim())
  return summaries
    .filter((item) => !project || item.project === project)
    .filter((item) => !needle || fold([item.key, item.title, details.get(item.key)?.markdown ?? ''].join(' ')).includes(needle))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .slice(0, limit)
}

type UserStory = components['schemas']['UserStory']

/** El título de la lista: el objetivo recortado a 120 caracteres, como la API. */
function memoryTitle(objective: string): string {
  return objective.length > 120 ? `${objective.slice(0, 119)}…` : objective
}

/**
 * Memoria que deja una HU al publicarse (`memorize`, T-33), con la forma de la de ejemplo (DEMO-9001) y el
 * contenido de la HU publicada. Indexada, como dice el Resultado («se ha generado e indexado»).
 */
export function mockPublishedMemory(story: UserStory, key: string, project: string, version: number, now = new Date()): MemoryOut {
  const base = example<MemoryOut>('GET /api/v1/memories/{key} 200')
  const objective = [story.title, story.business_goal].filter(Boolean).join('. ')
  const includes = story.scope_includes.length > 0 ? `Incluye: ${story.scope_includes.join('; ')}.` : ''
  const excludes = story.scope_excludes.length > 0 ? ` No incluye: ${story.scope_excludes.join('; ')}.` : ''
  const memory: MemoryOut['memory'] = {
    ...structuredClone(base.memory),
    jira_key: key,
    version,
    objective,
    scope: `${includes}${excludes}`.trim() || 'Sin alcance indicado.',
    business_rules: story.business_rules.map((rule) => `${rule.id}: ${rule.description}`),
    acceptance_criteria: story.acceptance_criteria.map((criterion) => `${criterion.id}: ${criterion.title}`),
    decisions: [],
    dependencies: [],
    changes: story.changes_from_previous.map((change) => `v${version}: ${change}`),
    references: [key],
  }
  return {
    key,
    project,
    title: memoryTitle(objective),
    version,
    updated_at: now.toISOString(),
    indexed: true,
    memory,
    markdown: memoryMarkdown(memory),
  }
}
