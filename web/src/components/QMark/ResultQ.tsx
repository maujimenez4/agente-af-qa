import { QShape, type QMotion } from './QShape.tsx'

export type PublishOutcomeKind = 'published' | 'partial' | 'simulated'

// Lienzo: MixtoPublicado y QaResultado (Q de 56 px).
const OUTCOMES: Record<PublishOutcomeKind, { offset: number; motion: QMotion; label: string }> = {
  published: {
    offset: 0,
    motion: { kind: 'fill', from: 326, duration: 1.2, delay: 0 },
    label: 'Publicado en Jira',
  },
  partial: {
    offset: 65,
    motion: { kind: 'fill', from: 326, duration: 1.2, delay: 0 },
    label: 'Publicada en parte',
  },
  simulated: {
    offset: 81.5,
    motion: { kind: 'none' },
    label: 'Publicación simulada',
  },
}

export interface ResultQProps {
  outcome: PublishOutcomeKind
  size?: number
}

// Q que se completa al publicar (UI.md §8, n.º 6); en simulación queda fija en 3/4.
export function ResultQ({ outcome, size = 56 }: ResultQProps) {
  const { offset, motion, label } = OUTCOMES[outcome]
  return (
    <span role="img" aria-label={label} style={{ display: 'inline-flex' }}>
      <QShape key={outcome} size={size} offset={offset} motion={motion} state={`result-${outcome}`} />
    </span>
  )
}
