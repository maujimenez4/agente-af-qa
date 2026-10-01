> **Sustituido el 2026-10-01:** ya no se trabaja con el compañero. Su contenido pasa a `SESION-UI.md` (sesiones paralelas de Claude Code).

# PROMPT-07 · Día 7 · UI con T-52 y T-53, T-31 y T-28 (sesión del compañero)

Prepara el repositorio y pega todo lo que hay debajo de la línea como primer mensaje en Claude Code:

```bash
git fetch origin
git switch -c Dia7 origin/PreProduccion   # rama nueva: Dia6 ya está fusionada
uv sync
docker compose up -d db ollama
uv run alembic upgrade head               # llega hasta 0004 (tabla conversations)
uv run pytest -m "not integration"
```

Si en tu equipo Python sigue bloqueado por el control de aplicaciones, **avísame antes de empezar**: sin pruebas ni ruff no se puede cerrar ninguna tarea.

---

Seguimos con el proyecto "Agente de IA de Análisis Funcional y QA". Estás en la rama **`Dia7`**, creada desde **`PreProduccion`**, que es la rama de integración: todo se fusiona en ella mediante PR, **nunca en `main`**.

## Qué ha pasado con `Dia6`
La sesión principal ha fusionado tu T-24 en `PreProduccion` y ha ejecutado lo que no pudiste ejecutar tú: sobre la fusión pasan **2727 pruebas** y ruff está limpio (había 2 archivos sin formatear). Ha hecho un único cambio en `app/`:
- **`Conversation.config` incluye ahora `"user": self.user`.** Desde T-52, `build_app_container` exige saber quién actúa (`require_actor`). Sin ese campo, en la app real cada invocación del grafo fallaba con «No existe esa conversación o no es tuya». Las pruebas con fakes no lo detectaban, así que hay una prueba nueva, `test_conversation_runs_against_container_that_requires_actor`.

Además, ya están en `PreProduccion`:
- **T-52 · conversaciones persistentes:** `build_checkpointer(config)`, `container.conversations.list_for(user)`, `new_conversation_config(user)` y `resume_config(store, user, thread_id)`.
- **T-53 · arranque guiado sin IA:** `GuidedStart(container).propose(...)` y `preview_sources(origin, excluded)`.

Están descritos en el anexo §11 de `docs/specs/SPEC-00-fundacional.md` (versión 1.7) y en las filas de dependencias de `docs/specs/UI.md`.

Lee antes:
- `CLAUDE.md`;
- `docs/specs/UI.md`;
- el anexo §11 de la SPEC;
- en `docs/KANBAN.md`, las últimas filas del registro diario y las propuestas PA-47, PA-54 … PA-58 y PA-72 … PA-74.

## Tareas de esta sesión
Hazlas con la skill del proyecto, **en este orden**.

### 1. Adoptar T-52 y T-53 en la UI (sigue siendo T-24; ciérrala con esto) [RF-14, RF-20, RF-47]
Área B: `app/`.
- **Checkpointer persistente:**
  - crea **una sola vez** por proceso `build_checkpointer(config)` con `st.cache_resource`, porque abre un pool de conexiones;
  - pásalo a `build_graph(container, checkpointer=…)` en lugar de `memory_checkpointer()`;
  - si falla al arrancar (`ExternalServiceError`), muestra el mensaje de UI.md §7.
- **Conversación nueva:**
  - usa `new_conversation_config(user)`: el `thread_id` lo genera el servidor; **nunca** lo tomes de la URL ni de la persona;
  - quita el `uuid4` propio de `Conversation`, o haz que tome el `thread_id` de esa config.
- **Lista de conversaciones:**
  - `container.conversations.list_for(user)`, con título, proyecto, flujo, estado y versión; los estados y su etiqueta están en UI.md;
  - el título de la lista es solo el flujo y la clave: no muestres el texto libre de la necesidad en la lista persistente.
- **Retomar:**
  - `resume_config(container.conversations, user, thread_id)`;
  - la pausa pendiente se lee de `graph.get_state(config).tasks[*].interrupts` (no de `next`), y desde ahí se reconstruyen la vista y las versiones.
- **Arranque guiado** (Mixta 1, 2 y QA 1):
  - `GuidedStart(container).propose(texto, proyecto, modo)` sustituye a tu reconocimiento de clave con `normalize_issue_key`;
  - si `project_changed`, avisa y llama a `container.projects.choose(user, proposal.project)` (PA-47);
  - si `ignored_projects` no está vacío, avisa de que esas claves son de otro proyecto;
  - la tarjeta «HU parecida» necesita la épica y el número de CA y RN: llama a `get_issue` (PA-56).
- **Panel «Antes de generar»:**
  - `preview_sources(origin, excluded)` con casillas;
  - la fila `required` no se puede desmarcar;
  - las desmarcadas van en `excluded_sources` de `initial_state`.

  Quita el apaño de desmarcar después de la primera versión.
- **PA-74:** prueba de humo con `streamlit.testing.v1.AppTest` (login con fakes y navegación hasta Mixta 3).
- **Revisión de seguridad de la fusión** (APTO, pero corrígelo aquí):
  - **MEDIO:** `app/conversation.py` `message_for` muestra `str(exc)` de cualquier `ValueError`; un `ValueError` de una librería llegaría a la UI con texto interno. Usa una lista blanca: `AgentError`, `ReviewRejectedError` y `ApprovalError` de `core`, y los `ValueError` de `core/projects`, `core/graph/state` y `app/origin`. El resto, `UNEXPECTED`.
  - **BAJO:** límite de intentos de login por sesión (`app/views/login.py`).
  - **BAJO:** `md_escape` en el `format_func` del selector de proyecto (`app/views/inicio.py`).
  - **BAJO:** quita el texto «llegará con T-52» de la barra lateral.

### 2. `/tarea T-31`: recibo de aprobación y resultado [RF-31, RF-32, RNF-16]
Mixta 3 → recibo → Mixta 4 (UI.md §4.6, §4.7 y §5):
- el recibo se construye con `plan` del payload: una casilla por operación;
- *Aprobar y publicar* se activa con todas marcadas y devuelve la huella del último payload;
- el resultado puede ser simulado (la aprobación sigue vigente) o real;
- el `error` de la pausa se muestra junto al recibo o al editor;
- un `ApprovalError` ofrece «empezar de nuevo».

Incluye las marcas «Cambiado en vN» / «Nueva» de PA-73 que salgan del diff (`impact.diffs`). Lo que necesite datos que el grafo no da, como la versión *Jira* en el selector o el presupuesto de tokens, déjalo propuesto.

### 3. Si terminas: `/tarea T-28`, pantallas QA 1 … QA 3
UI.md §6. El backend ya está: el modo QA del grafo usa `TestWriter`; la matriz sale de `suite.coverage_md()` y la estrategia de `suite.strategy_md`. El recibo y el resultado de QA (QA 4 y QA 5) siguen el patrón de T-31.

## Reglas para que la fusión sea limpia
- **No toques:**
  - `core/` (salvo `core/rag/`, `core/functional/`, `core/qa/` y `core/memory/`), `adapters/` ni `schemas/`;
  - los contratos congelados ni `core/factories.py`.

  Si la UI necesita algo del backend, **para** y déjalo propuesto (PA) o avísame.
- **Kanban:**
  - Cambia solo el estado de las filas de T-24, T-28 y T-31 y de las PA tuyas que cierres.
  - Añade tu propia fila al registro diario (día 7).
  - No toques el tablero resumen.
  - Sigue numerando tus propuestas desde **PA-75**.
- **Seguridad:**
  - Invoca el grafo **siempre** con `new_conversation_config` o `resume_config`.
  - El contenido de Jira, del RAG y del LLM nunca va a `st.html` ni a `unsafe_allow_html`.
  - Deja `JIRA_PUBLISH_MODE=simulation`.
  - Solo `publish` escribe en Jira.
  - Ni secretos ni datos personales reales.
  - Los logs no registran prompts ni contenido.
- **Cuota de Groq:**
  - Las pruebas usan fakes.
  - Si pruebas la app a mano con el LLM real, que sean pocas generaciones y avísame de cuántas.
  - No lances pruebas `integration` con LLM sin preguntarme.
- **Antes de cada commit:** `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde, más `spec-checker` CONFORME y `security-reviewer` APTO. **No subas una tarea como hecha sin haber ejecutado las pruebas.**
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - Sube la rama con `git push -u origin Dia7` y abre un PR por tarea contra `PreProduccion`.

Empieza por el punto 1 (cierre de T-24) y preséntame el plan antes de escribir código.
