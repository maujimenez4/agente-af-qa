# SESIÓN JIRA · T-27 y T-30: escritura en Jira (área A · `adapters/jira/`, `adapters/testmgmt/`)

Prepara un worktree propio y abre Claude Code **en esa carpeta**. Pega como primer mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa): se reutiliza el worktree area-a
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

Las pruebas `integration` contra tu sandbox de Jira necesitan tu `.env` en esta carpeta: cópialo tú (está en `.gitignore`).

---

Trabajas en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`** (worktree propio). Hay **otras sesiones de Claude Code trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra, es dueña de los contratos, del grafo y de la composición.
- **UI:** `ses-ui`, en `app/`.
- **Memoria:** `ses-memoria`, en `core/memory/`.
- **Ollama:** modelos locales (`qwen3:4b-instruct` y `bge-m3`), ya configurados en `config/models.yaml`.

**Solo tocas lo de esta sesión**; si necesitas algo de otra, para y propónlo.

Lee antes:
- `CLAUDE.md`, sobre todo el principio 1: **solo el nodo `publish` escribe en Jira**;
- en `docs/specs/SPEC-00-fundacional.md`: §4 (`IssueTracker`, `TestManagement`), §8 (ADF, reintentos solo en lecturas, publicación parcial) y el anexo §11 (contratos de T-25, T-50 y T-51);
- en `docs/decisiones/01_declaraciones_proyecto.md`: D-09 (Jira nativo, sin Xray), R-05 (prefijo `[HU-XX]` / `[CP-XX]` en el título) y RF-04, RF-05, RF-06, RF-30 y RNF-13;
- en `docs/KANBAN.md`, las propuestas PA-05, PA-46 y PA-49.

## Estado de partida
- `adapters/jira/tracker.py`, `JiraCloudTracker`:
  - **lecturas hechas:** `get_issue`, `search` con `/rest/api/3/search/jql` y `nextPageToken`, `list_projects`, `list_epics` y `list_children`, con backoff ante 429/5xx;
  - **escrituras con `NotImplementedError`:** `create_story(story, epic_key, project)`, `update_story(key, story, diff_comment_md)` y `link(from_key, to_key, link_type, comment_md)`.
- `adapters/jira/adf.py` tiene `adf_to_text`; falta `markdown_to_adf`.
- `adapters/testmgmt/` está vacío. Hoy la app usa `core/factories.PendingTestManagement`.
- El nodo `publish` (`core/graph/nodes.py`) ya llama a estos métodos con la operación aprobada. Su plan está en la auditoría: `update_story`/`create_story` con `project`, `link` «relates to» y `publish_suite`.

## Tareas, en este orden (con la skill `/tarea`)

### 1. `/tarea T-27`: `markdown_to_adf`, `create_story`, `update_story` y `link` [RF-04, RF-05, RF-06]
- **`markdown_to_adf(md)`** (SPEC §8): títulos, párrafos, listas, tablas, negrita y bloques de código.
  - **PA-49:** el contenido llega de una HU editada a mano o generada por el LLM, así que no es fiable. Escapa `|` y los saltos de línea en las celdas, y en los enlaces admite solo `http(s)`. Nada de HTML.
  - Pruebas de ida y vuelta con `adf_to_text`.
- **`create_story(story, epic_key, project)`:**
  - crea la HU en `project`, con título `[HU-XX] …` (R-05) y la descripción en ADF a partir de la plantilla de `UserStory` (CA en Gherkin, RN, alcance…), con la épica como `parent`;
  - **PA-46:** comprueba que la clave devuelta es de `project`; si no, `PublishError`.
- **`update_story(key, story, diff_comment_md)`:** actualiza título y descripción y añade el comentario del diff en ADF (RF-05).
- **`link(...)`:** vínculo «relates to» con comentario opcional.
- **Errores:**
  - las **escrituras no se reintentan** (§8: backoff solo en lecturas);
  - envuelve en `adapters/errors.py` (`PublishError`, `AuthenticationError`, `NotFoundError`, `RateLimitError`), con mensajes en español y sin cuerpos de respuesta ni cabeceras.
- **Tipo de incidencia:** si hace falta configurar el nombre del tipo («Story» / «Historia»), **no toques `core/config.py`**. Propónlo y, mientras, usa una constante en el adaptador.
- **Pruebas unitarias** con `httpx.MockTransport`: el cuerpo de cada petición, los errores y que no se escriba nada fuera de estos métodos.

### 2. `/tarea T-30`: `JiraNativeTests` en `adapters/testmgmt/` [RF-30, RF-06, RNF-13]
- **`publish_suite(suite) -> PublishResult`:**
  - cada CP es una subtarea de la HU con la etiqueta `caso-prueba` y el título `[CP-XX] …`;
  - el tipo de subtarea sale de `Settings.jira_test_subtask_type`: recíbelo por el constructor;
  - la estrategia (`suite.strategy_md`) y la matriz (`suite.coverage_md()`) van como adjuntos `.md` de la HU;
  - **publicación parcial (RNF-13):** uno a uno, y devuelve `created` y `failed`.
- **PA-05 · idempotencia:** al reintentar, no duplica las subtareas que ya existen. Usa `list_cases(story_key)`, que busca por la etiqueta, y el `[CP-XX]` del título.
- **`list_cases(story_key)`.**
- **Composición:** `core/factories.py` es de la sesión principal. No lo toques. Indica en tu informe cómo se construye `JiraNativeTests`, y la principal la cableará en `build_app_container` al fusionar.

## Pruebas reales contra Jira (sandbox)
- Márcalas con `@pytest.mark.integration` y que **además se salten salvo con `JIRA_WRITE_TESTS=1`**, porque escriben en Jira.
- **No las ejecutes sin preguntarme antes.** Cuando lo autorice:
  - usa un proyecto de pruebas;
  - deja constancia de las claves creadas;
  - y, si se puede, bórralas o márcalas al terminar.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:** `adapters/jira/`, `adapters/testmgmt/`, `tests/unit/test_jira_*.py`, `tests/unit/test_testmgmt*.py`, `tests/unit/test_adf*.py` y `tests/integration/test_jira_*`.
  - No toques `core/`, `app/`, `schemas/`, `adapters/base.py`, `adapters/errors.py`, `prompts/`, `config/` ni la SPEC.
  - En `tests/fakes/` solo puedes añadir, sin romper nada.
  - Si necesitas cambiar un contrato, **para** y propónlo.
- **Kanban:**
  - Cambia solo el estado de tus filas (T-27, T-30, PA-05, PA-46 y PA-49).
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Numera tus propuestas en PA-200…PA-249.**
- **Seguridad:**
  - Los tokens, solo vía `SecretStr` y `core/config.py` (los recibe el adaptador ya resueltos).
  - Nunca registres `Authorization` ni cuerpos de respuesta.
  - Nada escribe en Jira salvo estos métodos, llamados desde `publish`.
  - Ni secretos ni datos personales en pruebas o fixtures.
- **LLM:** esta sesión no lo necesita; no lo llames.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`.
  - **Sin fusionar.** Haz `git push -u origin ses-jira` y avísame.

Empieza por `/tarea T-27` y preséntame el plan antes de escribir código.
