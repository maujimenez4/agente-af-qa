# SESIÓN MODELOS · Ronda 8: citas en la calidad, reintentar y retoques (PA-282, PA-283, PA-276, PA-317 y PA-279)

> Encargo de la **sesión Modelos**. Tu PA-281 ya está fusionada y **verificada en el e2e real**: la HU nueva cita bien a la primera, sin reintento, en 5,3 min.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-pendientes origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-pendientes`**, creada desde `PreProduccion`.

## Tareas (lee el texto completo de cada PA en `docs/KANBAN.md`)
1. **PA-282:** `core/quality.py` aplica `repair_citations` como la HU y la suite.
2. **PA-283:** una cita a la épica con el extracto de la HU es «válida» y no se corrige.
   - Si el extracto de una cita de Jira está claramente en **otra** fuente de Jira y no en la citada, se corrige a esa fuente, con las mismas garantías de PA-281: coincidencia inequívoca y de longitud mínima; si no, no se toca.
   - Nunca se inventa trazabilidad.
3. **PA-276:** `POST /conversations/{id}/retry` para reintentar una conversación en `error` desde su último checkpoint (`graph.stream(None, config)`).
   - Con propiedad (404 idéntico), permiso del flujo y 409 si no está en error.
   - Si es de QA encadenada, la regla de PA-113 se mantiene.
   - Contrato regenerado con `uv run python -m api.export_openapi`, sin argumentos.
4. **PA-317:** `conversation_title()` da «HU nueva en la épica DEMO-1» en lugar de «Nueva HU en DEMO-1». Las filas ya guardadas no se migran.
5. **PA-279:** conservación de las revisiones de calidad (RGPD).
   - Un plazo configurable de días, con un valor por defecto prudente (p. ej. 90), y su purga. Propón dónde se ejecuta: al arrancar la API y con un comando.
   - Borrado de las de una persona cuando se la da de baja (`active=False` en el seed de usuarios).
   - Documéntalo.

## Reglas
- **Puedes tocar:**
  - `core/quality.py`, `core/functional/citations.py`, `core/qa/` (solo el camino de citas) y `core/conversations.py` (solo el título);
  - `api/` (PA-276 y, si hace falta, la purga de PA-279);
  - `core/seed_users.py` (baja, PA-279);
  - y sus pruebas.

  En `core/config.py` solo el campo del plazo de PA-279 (autorizado). No toques `core/approvals.py`, `core/artifact_state.py`, `core/impact/`, `adapters/`, `app/`, `core/graph/nodes.py` ni `config/`.
- **El frontend en React consume el contrato:** PA-276 solo añade una ruta; no cambies las existentes.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **Nombres en las pruebas:** sin `secret`, `password` ni `token` como nombre de variables con literales, ni textos que imiten una clave privada (gitleaks).
- **Kanban:**
  - cierra las PA con la fecha;
  - añade tu fila al registro;
  - **propuestas en PA-284…PA-299**.
- **Antes del commit:**
  - `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-pendientes` y avísame.

Empieza presentándome el plan (sobre todo PA-283 y PA-276) antes de escribir código.
