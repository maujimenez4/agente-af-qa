import { useState } from 'react'
import examples from '../api/examples.json'
import type { ConversationOut } from '../api/types.ts'
import { AssistantMessage, ChatLog } from '../components/Chat/index.ts'
import { SidePanel, Workspace } from '../components/Workspace/index.ts'
import type { UserStory } from '../screens/Edit/storyDraft.ts'
import { StoryEditorActions, StoryEditorFields } from '../screens/Edit/StoryEditor.tsx'
import { useStoryEditor } from '../screens/Edit/useStoryEditor.ts'

// Catálogo (solo en desarrollo): Editar a mano (PA-340) en el panel derecho, a tamaño real, con la HU del ejemplo
// del contrato. `/?catalogo&editor` lo abre solo, para revisar 1024, 1280 y 1440 sin scroll de página. No llama a la API:
// «Guardar» crea la versión siguiente aquí mismo y `&rechazo` simula un `review.error`.
const EXAMPLE = examples['GET /api/v1/conversations/{conversation_id} 200'] as unknown as ConversationOut
const REJECTED = 'La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto.'

function Editor({ story, version, rejected, onSaved, onCancel }: { story: UserStory; version: number; rejected: boolean; onSaved: (story: UserStory) => void; onCancel: () => void }) {
  const editor = useStoryEditor(story)
  const [error, setError] = useState<string | null>(null)
  return (
    <SidePanel
      title="Editar a mano"
      subtitle={`Evolucionar DEMO-3 · versión ${version}`}
      size="lg"
      footer={
        <StoryEditorActions
          editor={editor}
          version={version}
          onCancel={onCancel}
          onSave={(content) => (rejected ? setError(REJECTED) : onSaved(content))}
        />
      }
    >
      <StoryEditorFields editor={editor} reviewError={error} />
    </SidePanel>
  )
}

export function EditorDemo() {
  const rejected = new URLSearchParams(window.location.search).has('rechazo')
  const [story, setStory] = useState(EXAMPLE.review?.artifact.content as UserStory)
  const [version, setVersion] = useState(EXAMPLE.review?.version ?? 1)
  const [saved, setSaved] = useState<string>()
  const [round, setRound] = useState(0)
  return (
    <div style={{ display: 'flex', height: '100dvh', overflow: 'hidden' }}>
      <Workspace
        title="Evolucionar DEMO-3"
        phase={2}
        panel={
          <Editor
            key={round}
            story={story}
            version={version}
            rejected={rejected}
            onCancel={() => {
              setSaved('Edición cancelada: la versión sigue como estaba.')
              setRound((n) => n + 1)
            }}
            onSaved={(content) => {
              setStory(content)
              setVersion((n) => n + 1)
              setSaved(`Versión ${version + 1} guardada (simulado, sin API).`)
              setRound((n) => n + 1)
            }}
          />
        }
      >
        <ChatLog>
          <AssistantMessage>
            <span>Catálogo · Editar a mano. {saved ?? 'Edita la HU en el panel y guarda la versión siguiente.'}</span>
          </AssistantMessage>
        </ChatLog>
      </Workspace>
    </div>
  )
}
