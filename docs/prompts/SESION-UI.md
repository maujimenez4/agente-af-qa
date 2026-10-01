# SESIÓN UI · Cierre de T-24, T-31 y T-28 (área B · `app/`)

Prepara un worktree propio y abre Claude Code **en esa carpeta**. Pega como primer mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git worktree add .claude/worktrees/ses-ui -b ses-ui origin/PreProduccion
cd .claude/worktrees/ses-ui
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

Para arrancar la app a mano hace falta tu `.env`: cópialo tú a esta carpeta (está en `.gitignore`). Ollama y PostgreSQL son los de `docker compose` de la carpeta principal (`docker compose --profile local-llm up -d db ollama`).

---

Trabajas en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-ui`** (worktree propio). Hay **otras sesiones de Claude Code trabajando a la vez** en otras ramas:
- **Principal:** `PreProduccion`. Integra, es dueña de los contratos y hace T-48.
- **Jira:** `ses-jira`, con T-27 y T-30 en `adapters/`.
- **Memoria:** `ses-memoria`, con T-33 en `core/memory/`.
- **Ollama:** modelos locales (`qwen3:4b-instruct` y `bge-m3`), ya configurados en `config/models.yaml`.

Para no pisaros, **solo tocas lo de esta sesión**. Si necesitas algo de otra, para y propónlo.

Lee antes:
- `CLAUDE.md`;
- `docs/specs/UI.md` (la UI decidida, «Propuesta mixta», con el contrato de aprobación en §5 y los errores en §7);
- el anexo §11 de `docs/specs/SPEC-00-fundacional.md` (versión 1.7);
- en `docs/KANBAN.md`, las «Decisiones del día 6», las últimas filas del registro diario y las propuestas PA-47, PA-54…PA-58 y PA-72…PA-74.

## Estado de partida
`app/` tiene la UI de T-24, en 👀: login, Mixta 1, 1b, 2, 2b y 3, selector de modelo y unas 220 pruebas. Desde la fusión, `Conversation.config` lleva `"user"`, porque el contenedor de la app exige saber quién actúa (`require_actor`, T-52).

El backend que la UI aún no usa ya está en `PreProduccion`:
- **T-52:**
  - `core/factories.build_checkpointer(config)`;
  - `container.conversations.list_for(user)`;
  - `core/conversations.new_conversation_config(user)` y `resume_config(store, user, thread_id)`.
- **T-53:** `core/guided_start.GuidedStart(container)`, con `propose(texto, proyecto, modo)` y `preview_sources(origin, excluded)`.

## Tareas, en este orden (con la skill `/tarea`)

### 1. Cerrar T-24: adoptar T-52 y T-53 y corregir la revisión de seguridad [RF-14, RF-20, RF-47]
- **Checkpointer persistente:**
  - `build_checkpointer(config)` **una sola vez por proceso**, con `st.cache_resource` (abre un pool);
  - pásalo a `build_graph(container, checkpointer=…)` en lugar de `memory_checkpointer()`;
  - si falla al arrancar (`ExternalServiceError`), muestra el mensaje de UI.md §7.
- **Conversación nueva:** `new_conversation_config(user)`. El `thread_id` lo genera el servidor: nunca lo tomes de la URL ni de la persona. Quita el `uuid4` propio de `Conversation`.
- **Lista:** `container.conversations.list_for(user)`, con título (solo flujo y clave), proyecto, flujo, estado y versión; las etiquetas por estado están en UI.md. Quita el texto «llegará con T-52».
- **Retomar:** `resume_config(...)`. La pausa pendiente se lee de `graph.get_state(config).tasks[*].interrupts`, **no de `next`**; desde ahí se reconstruyen la vista y las versiones.
- **Arranque guiado (Mixta 1 y 2):**
  - `GuidedStart.propose` sustituye al reconocimiento de clave con `normalize_issue_key`;
  - si `project_changed`, avisa y llama a `container.projects.choose(user, proposal.project)` (PA-47);
  - si `ignored_projects` no está vacío, avisa;
  - la tarjeta «HU parecida» necesita la épica y el número de CA y RN: usa `get_issue` (PA-56).
- **Panel «Antes de generar»:**
  - `preview_sources(origin, excluded)` con casillas;
  - la fila `required` no se puede desmarcar;
  - las desmarcadas van en `excluded_sources`. Quita el apaño de desmarcar después de la primera versión.
  - Las restricciones van a `origin.text` en una necesidad y a `initial_state(..., feedback=[...])` en una evolución.
- **Revisión de seguridad de la fusión:**
  - **MEDIO:** `message_for` (`app/conversation.py`) muestra `str(exc)` de cualquier `ValueError`. Usa una lista blanca: `AgentError`, `core.graph.nodes.ReviewRejectedError`, `core.approvals.ApprovalError` y los `ValueError` de `core/projects`, `core/graph/state` y `app/origin`. El resto debe dar `UNEXPECTED`.
  - **BAJO:** límite de intentos de login por sesión.
  - **BAJO:** `md_escape` en el `format_func` del selector de proyecto (`app/views/inicio.py`).
- **PA-74:** prueba de humo con `streamlit.testing.v1.AppTest` (login con fakes y navegación hasta Mixta 3).

### 2. `/tarea T-31`: recibo de aprobación y resultado [RF-31, RF-32, RNF-16]
UI.md §4.6, §4.7 y §5:
- el recibo se construye con `plan` del payload: una casilla por operación;
- *Aprobar y publicar* se activa con todas marcadas y devuelve la **huella del último payload**;
- el resultado puede ser simulado (la aprobación sigue vigente) o real;
- el `error` de la pausa se muestra junto al recibo o al editor;
- un `ApprovalError` ofrece «empezar de nuevo».

Incluye las marcas «Cambiado en vN» / «Nueva» que salgan de `impact.diffs` (PA-73). Lo que necesite datos que el grafo no da, como la versión *Jira* o el presupuesto de tokens, déjalo propuesto.

### 3. Si terminas: `/tarea T-28`, pantallas QA 1 … QA 3
UI.md §6. El modo QA del grafo ya usa `TestWriter`; la matriz sale de `suite.coverage_md()` y la estrategia de `suite.strategy_md`. El recibo y el resultado de QA siguen el patrón de T-31.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:** `app/`, `.streamlit/` y `tests/unit/test_app_*.py`.
  - No toques `core/`, `adapters/`, `schemas/`, `prompts/`, `migrations/`, `config/` ni `docs/specs/SPEC-00-fundacional.md`.
  - En `tests/fakes/` solo puedes **añadir**, sin romper nada.
  - Si necesitas un cambio de backend o de contrato, **para** y escríbelo como propuesta.
- **Kanban:**
  - Cambia solo el estado de tus filas (T-24, T-28, T-31 y las PA que cierres).
  - Añade tu propia fila al registro diario.
  - No toques el tablero resumen.
  - **Numera tus propuestas en tu rango: PA-150…PA-199.**
- **Seguridad:**
  - Invoca el grafo **siempre** con `new_conversation_config` o `resume_config`.
  - El contenido de Jira, del RAG y del LLM nunca va a `st.html` ni a `unsafe_allow_html`.
  - Solo `publish` escribe en Jira, y la UI nunca llama a métodos de escritura.
  - Deja `JIRA_PUBLISH_MODE=simulation`.
  - No leas ni muestres el `.env`.
  - Ni secretos ni datos personales reales.
  - Los logs no registran prompts ni contenido.
- **LLM:**
  - Las pruebas automáticas usan fakes.
  - No lances pruebas `integration` con LLM ni generes con el LLM real sin preguntarme: desde el 2026-10-01 solo se usan modelos locales de Ollama (`config/models.yaml`), que en CPU son lentos.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - **Sin fusionar en `PreProduccion` ni en `main`.** Haz `git push -u origin ses-ui` y avísame: la sesión principal revisa y fusiona.

Empieza por el punto 1 y preséntame el plan antes de escribir código.
