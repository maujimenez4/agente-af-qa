# SESIÓN MEMORIA · T-33: generador de memoria y medición de RNF-11 (área B · `core/memory/`)

Prepara un worktree propio y abre Claude Code **en esa carpeta**. Pega como primer mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa): se reutiliza el worktree area-b
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-memoria origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Trabajas en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-memoria`** (worktree propio). Hay **otras sesiones de Claude Code trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra, es dueña de los contratos, del grafo (`core/graph/`) y de la composición (`core/factories.py`).
- **UI:** `ses-ui`, en `app/`.
- **Jira:** `ses-jira`, en `adapters/`.
- **Ollama:** modelos locales (`qwen3:4b-instruct` y `bge-m3`), ya configurados en `config/models.yaml`.

**Solo tocas lo de esta sesión**; si necesitas algo de otra, para y propónlo.

Lee antes:
- `CLAUDE.md`;
- en `docs/specs/SPEC-00-fundacional.md`: §3 (`schemas/memory.py`), §4 (`MemoryGenerator`), §5.2 (nodo `memorize`) y §6 (memorias en `data/memory/<JIRA_KEY>.md` y en `documents` con `category='memoria'`);
- en `docs/decisiones/01_declaraciones_proyecto.md`: D-07 (en el MVP solo las HU publicadas generan memoria) y RF-36, RF-37, RF-38, RF-51, RNF-11 y RNF-25;
- `prompts/generate_story.md`, como modelo de prompt con datos no confiables delimitados.

## Estado de partida
- **Ya existe, de la sesión principal:**
  - `schemas/memory.Memory` (congelado), con `to_markdown()`;
  - el protocolo `MemoryGenerator.generate(artifact) -> Memory`;
  - el nodo `memorize`, que exige la publicación registrada, escribe `data/memory/<clave>.md`, reindexa sin duplicar (borra y vuelve a insertar `memoria-<clave>`) y prioriza la memoria con `memory_boost` (RF-51).
- **Falta:**
  - el **generador real**: hoy la app usa `core/factories.PendingMemoryGenerator` y las pruebas usan `tests/fakes/memory_generator.py`;
  - el prompt `prompts/synthesize_memory.md`;
  - la medición de RNF-11.
- `TaskType.SYNTHESIZE_MEMORY` y su cadena de modelos ya están en `config/models.yaml`. No toques ese archivo: lo gestiona la sesión de Ollama.

## Tareas, en este orden (con la skill `/tarea`)

### 1. `/tarea T-33` (parte de backend): `LLMMemoryGenerator` [RF-36, RF-37, RF-38, RNF-25]
- **`core/memory/generator.py`:** `LLMMemoryGenerator(llm, prompt_loader=...)`, que implementa `MemoryGenerator`.
  - Usa `llm.generate_structured(messages, Memory, TaskType.SYNTHESIZE_MEMORY)` con el prompt `prompts/synthesize_memory.md`, que lleva cabecera `version:`.
  - Reutiliza el cargador de prompts del área B (`core/rag/prompts.load_prompt`).
- **Agnóstico al tipo (RNF-25):** recibe el `Artifact` y no depende de que sea una HU. En el MVP, el nodo solo lo llama para HU (D-07).
- **Validación posterior, determinista y sin confiar en el LLM:**
  - `jira_key` y `version` salen del artefacto publicado, no del modelo;
  - las `references` solo pueden ser fuentes que el artefacto cita (`content.sources`); cualquier otra se descarta;
  - los IDs de RN y CA deben existir en la HU;
  - texto escapado y delimitado como dato no confiable, igual que `core/functional/context.escape_data`.
  - Si falla, un reintento con el error y después un error en español (patrón de `core/functional/citations.py`).
- **Pruebas** con `tests/fakes/llm.FakeLLMProvider` (añade un builder si hace falta; añadir, no romper):
  - campos, validación y reintento;
  - que el `.md` resultante tenga las 8 secciones de RF-36;
  - y una prueba de grafo (`tests/fakes/container.fake_container(memory_generator=LLMMemoryGenerator(fake_llm))`) que publique en modo live con fakes y compruebe el reindexado sin duplicados.
- **Composición:** no toques `core/factories.py`. Indica en tu informe cómo se construye, y la principal sustituirá `PendingMemoryGenerator` al fusionar.

### 2. Medición de RNF-11 (la memoria reduce los tokens ≥ 60 % frente al artefacto)
- Un script en `eval/` (por ejemplo `eval/memory_tokens.py`, con `__main__`) que compare tokens de la HU completa frente a su memoria para las HU del seed y del dataset de fakes. Usa `core/context/budget.estimate_tokens`; solo lectura, sin llamar a Jira.
- La parte con el LLM real (generar memorias de verdad) **no la ejecutes sin preguntarme**. Hazla con fakes y deja preparado el modo real.

La **pestaña Memoria** de la UI es de la sesión UI: no la hagas.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:** `core/memory/`, `prompts/synthesize_memory.md`, `eval/memory_*.py`, `tests/unit/test_memory*.py` y `tests/integration/test_memory_*`.
  - No toques `core/graph/`, `core/factories.py`, `core/container.py`, `schemas/`, `adapters/`, `app/`, `config/` ni la SPEC.
  - En `tests/fakes/` solo puedes añadir, sin romper nada.
  - Si necesitas un cambio de contrato o del nodo `memorize`, **para** y propónlo.
- **Kanban:**
  - Cambia solo el estado de tu fila (T-33; si solo haces el backend, déjala 👀 y anota que falta la pestaña).
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Numera tus propuestas en PA-250…PA-299.**
- **Seguridad:**
  - La memoria no puede llevar datos personales ni secretos.
  - Los logs no registran prompts ni contenido.
  - El texto de la HU es dato no confiable en el prompt.
- **LLM:**
  - Las pruebas usan fakes.
  - No lances pruebas `integration` con LLM sin preguntarme: desde el 2026-10-01 solo se usan modelos locales de Ollama (`config/models.yaml`), que en CPU son lentos.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - **Sin fusionar.** Haz `git push -u origin ses-memoria` y avísame.

Empieza por `/tarea T-33` y preséntame el plan antes de escribir código.
