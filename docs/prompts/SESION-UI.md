# SESIÓN MODELOS · Ronda 10: pestaña Memoria (cierre de T-33)

> Encargo de la **sesión Modelos**. Tu ronda 9 (`ses-contrato`) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-memoria-ui origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-memoria-ui`**, creada desde `PreProduccion`. Tu ronda 9 ya está fusionada.

**Objetivo: cerrar T-33 (👀).** El backend de la memoria ya existe: al publicar una HU, el nodo `memorize` (`core/graph/nodes.py`) genera `data/memory/<CLAVE>.md` y lo reindexa en el RAG como `memoria-<CLAVE>` (categoría `memoria`, prioritaria, RF-51). Lo que falta es **verla**: la pestaña **Memoria** (RF-36, RF-37 y RF-38; permiso `VIEW_MEMORY`, que tienen los tres roles; `docs/specs/UI.md`).

Lee la fila de T-33 en `docs/KANBAN.md`, `core/memory/`, el modelo `Memory` de `schemas/` y cómo está hecha una ruta de solo lectura en `api/` (por ejemplo `GET /quality-reviews`).

## Tareas
1. **Servicio de lectura** (sin LLM y sin escribir nada): listar las memorias y leer una a partir de `container.memory_dir`.
   - Valida la clave con `JIRA_KEY` y que la ruta resuelta quede dentro de `memory_dir`, como hace `memorize`.
   - Solo las memorias de los **proyectos que ve la conexión**.
   - Datos de cada memoria: clave, proyecto, título, fecha de la última actualización y si está indexada en el RAG. Indexada se comprueba por `memoria-<CLAVE>` en el vector store; si eso exige un método nuevo en `adapters/base.py` (congelado), **para y propónmelo**.
2. **API**, en un módulo propio `api/memories.py` con su `APIRouter` (prefijo `/memories`). En `api/app.py` solo se añade el router a la lista que se incluye: la sesión Jira está tocando el mismo archivo en paralelo.
   - `GET /memories?project=&q=&limit=` → lista de resúmenes.
   - `GET /memories/{key}` → la memoria estructurada y su markdown, que se entrega solo para descargar (como `report_markdown`).
   - Propiedad y errores como el resto: 404 idéntico para lo que no existe y para lo de un proyecto no visible.
   - Ejemplos en las respuestas nuevas y apartado en «Novedades para el frontend» de `docs/api/README.md`.
3. **Streamlit (plan B)**: pestaña **Memoria** en `app/` (vista nueva en `app/views/`) con la lista, el buscador y el detalle. El texto del LLM se muestra como texto, nunca como HTML ni markdown interpretado sin escapar.
   - Lista vacía: «Aún no hay memorias. Se generan al publicar una HU en Jira (modo real).»
4. **Datos de ejemplo:** en simulación no se genera ninguna memoria. Para ver la pantalla en desarrollo, propón en el plan cómo sembrar una o dos memorias **ficticias** (por ejemplo, un script en `scripts/` o un fixture), sin tocar Jira.

## Reglas
- **Solo añade:** rutas nuevas y campos opcionales; nada existente cambia.
- **Contrato:** regenéralo con `uv run python -m api.export_openapi`. Si al fusionar choca con el de la sesión Jira, lo regenera la principal.
- **Puedes tocar:**
  - `api/memories.py`, la línea del router en `api/app.py` y `api/models.py` (solo añadir);
  - `core/memory/` (solo lectura nueva);
  - `app/` (vista y navegación);
  - `docs/api/`;
  - y sus pruebas.

  No toques `core/graph/`, `adapters/`, `schemas/`, `config/` ni `web/`.
- **Pruebas** con `fake_runtime` y fakes:
  - lista y detalle;
  - proyecto no visible y clave no válida o con `../` (404 idéntico);
  - vacío;
  - los tres roles pueden leer;
  - no se llama al LLM.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - T-33 → ✅ con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-288…PA-299**. Por ejemplo, una herramienta MCP `ver_memoria` es una propuesta, no se implementa.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-memoria-ui` y avísame.

Empieza presentándome el plan (sobre todo cómo sabes si está indexada y cómo se siembran las memorias de ejemplo) antes de escribir código.
