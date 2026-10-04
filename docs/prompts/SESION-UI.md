# SESIÓN MODELOS · Ronda 9: contrato para el frontend (PA-314, PA-316 y PA-285)

> Encargo de la **sesión Modelos**. Tu ronda 8 (`ses-pendientes`) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-contrato origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-contrato`**, creada desde `PreProduccion`. Tu ronda 8 ya está fusionada.

**En esta ronda atiendes tres peticiones del responsable del frontend en React (T-56).** Las pantallas ya existen en `web/` y esperan estas rutas. Lee el texto de cada PA en `docs/KANBAN.md` y, para ver cómo se usan, `docs/specs/UI.md` (Generando e Iterar) y `docs/api/README.md`.

## Tareas
1. **PA-314 · Detener una generación en curso:** `POST /conversations/{id}/cancel`.
   - Solo si la conversación está generando (`generating`). Si no, 409 `not_in_review` o un código nuevo coherente; propónlo en el plan.
   - Con propiedad (404 idéntico para lo ajeno y lo inexistente) y el permiso del flujo.
   - **Cómo se detiene:** la operación corre en un hilo con `graph.stream`. Propón cómo cortarla de forma segura, por ejemplo una señal de cancelación que `_run_graph` comprueba entre nodos, sin matar hilos. No podrá interrumpir una llamada al LLM ya en curso: dilo en la descripción del contrato. Se para al terminar el paso actual, sin pasar al siguiente.
   - **Estado final:** propón cuál, por ejemplo `error` con un `error.code` como `cancelled`, que se puede reintentar con `/retry`, o volver a la revisión anterior si la había (iterar).
   - **Nunca escribe en Jira:** cancelar no aprueba ni publica nada. Si la operación en curso es aprobar o publicar, no se cancela (409): la publicación tiene sus propias garantías (PA-141).
   - **QA encadenada:** si se cancela la generación de una conversación recogida sin primera versión, se aplica la regla de PA-113 (la entrega vuelve a la lista).
2. **PA-316 · Versión «Jira» de la HU para comparar en Iterar.** El frontend necesita la HU tal como está en Jira, estructurada como `UserStory`, para el selector de versiones.
   - Propón dónde se expone sin coste extra de LLM: la estructuración ya se hace una vez y queda como «versión de partida» en `artifact_state.state["baseline"]` (PA-30, PA-37).
   - Por ejemplo, un campo `jira_baseline` en `ReviewPayload` o en `ConversationOut`, o `GET /conversations/{id}/baseline`. **Nunca** se llama al LLM solo para esto.
   - Solo en las conversaciones que evolucionan una HU existente; en las de HU nueva, ausente o `null`.
3. **PA-285 · Texto del arranque guiado:** `core/guided_start.py` debe decir «HU nueva en la épica DEMO-1», como el título de la conversación (PA-317).

## Reglas
- **El frontend ya consume el contrato:** solo se añaden rutas o campos opcionales; no cambia ni se quita nada de lo existente. Regenera el contrato con `uv run python -m api.export_openapi` (sin argumentos), con ejemplos en las respuestas nuevas, y actualiza `docs/api/README.md` con un apartado «Novedades para el frontend».
- **Puedes tocar:**
  - `api/`;
  - `core/guided_start.py` (solo el texto);
  - `core/graph/` (solo si la cancelación lo necesita y sin tocar `publish` ni `_publish_approved`);
  - y sus pruebas.

  No toques `core/approvals.py`, `core/artifact_state.py` ni `core/impact/versions.py` (la sesión UI está ahí con PA-140 y PA-146), ni `adapters/`, `schemas/`, `config/`, `app/` ni `web/`.
- **Pruebas:**
  - con `fake_runtime` y fakes;
  - incluye la cancelación entre nodos (con `run_inline=False` y un fake que bloquea un nodo hasta que se cancela), que cancelar no escribe en Jira, y la versión «Jira» en una evolución y su ausencia en una HU nueva.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **Nombres en las pruebas:** sin `secret`, `password` ni `token` como nombre de variables con literales, ni textos que imiten una clave privada (gitleaks).
- **Kanban:**
  - cierra las PA con la fecha;
  - añade tu fila al registro;
  - **propuestas en PA-288…PA-299**.
- **Antes del commit:**
  - `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-contrato` y avísame.

Empieza presentándome el plan (sobre todo cómo se detiene la generación y su estado final, y dónde va la versión «Jira») antes de escribir código.
