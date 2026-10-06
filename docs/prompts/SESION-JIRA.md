# SESIÓN JIRA · Ronda 13: arreglos pequeños del backend (PA-244, PA-128 y PA-339)

Tu ronda 12 (PA-41) ya está fusionada. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-backend-fixes origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-backend-fixes`**, creada desde `PreProduccion`. Tu ronda 12 ya está fusionada.

**Objetivo:** tres arreglos pequeños del backend que salieron de la auditoría y de la prueba de la web contra la API real. Ninguno bloquea la demo, pero conviene dejarlos cerrados.

## Regla principal: no chocar con la web
El responsable de `web/` está trabajando en paralelo en la web (Administración, Editar a mano y el presupuesto de tokens), y otra sesión termina `ses-web-fixes`.
- **No toques nada de `web/` ni `docs/specs/UI.md`.**
- **El contrato de la API (`docs/api/openapi.yaml`) no puede cambiar.** Regenera el contrato con `uv run python -m api.export_openapi` y comprueba que sale idéntico. Si algún arreglo lo cambiara, **para y avísame** antes de seguir.

## Tareas
1. **PA-244 · Cuatro `except Exception` que ignoran el error sin dejar rastro** (salieron de la capa 1 de `/auditoria`):
   - `api/service.py` (`_failed_ids`): un fallo de la auditoría se ve como «sin fallos»;
   - `app/conversation.py` (`_after_failure` y `_settle_approval`);
   - `core/health.py` (`_timed`): el administrador ve «Error inesperado» y no queda rastro del tipo.

   En los cuatro, registra el tipo de error con `log.warning` (`error_type`, **sin el mensaje**, que podría llevar datos) y mantén el comportamiento que ve la persona. Comprueba después con `uv run python .claude/skills/auditoria/checks.py --rule silent-except` que la regla sale a 0.
2. **PA-128 · La API sigue calculando los embeddings aunque la web cancele `POST /start/sources`.** La web ya aborta la petición al cambiar una casilla o al pulsar Generar (PA-336), pero el servidor sigue trabajando hasta el final y compite con la generación.
   - Propón cómo cortarlo en el servidor sin cambiar el contrato. Por ejemplo, comprobar `request.is_disconnected()` entre fuentes o ejecutar la búsqueda de forma cancelable.
   - Si no se puede sin complicar mucho el código, propón la alternativa más simple: por ejemplo, limitar a una consulta de fuentes en curso por persona, de forma que la nueva sustituya a la anterior.
3. **PA-339 · Al reintentar una evolución detenida durante la estructuración, `structure_story` se vuelve a llamar** (40 a 50 s de más con el modelo local).
   - Guarda la versión estructurada en cuanto exista (en el estado o en `state_store`, como la versión de partida de PA-61), para que un reintento la reutilice.
   - Solo `core/graph/` y lo mínimo, sin tocar `publish` ni `_publish_approved`.

## Reglas
- **Puedes tocar:** `api/`, `core/` (`core/health.py`, `core/guided_start.py`, `core/context/`, `core/graph/` para PA-339), `app/conversation.py` (solo PA-244) y sus pruebas. No toques `web/`, `schemas/`, `adapters/base.py` ni `mcp_server/` (lo hace la sesión MCP).
- **Pruebas con fakes:**
  - PA-244: el log con `error_type` y sin el mensaje, y el mismo resultado para la persona;
  - PA-128: una petición cancelada deja de calcular;
  - PA-339: un reintento tras detener en la estructuración no vuelve a llamar a `structure_story`.

  Nada de pruebas con el modelo real en esta ronda.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra las tres PA con la fecha (PA-128 puede no estar todavía en tu Kanban: añádela como hecha);
  - tu fila en el registro;
  - propuestas en **PA-414…PA-419**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-backend-fixes` y avísame.

Empieza presentándome el plan (sobre todo cómo cortar el cálculo en PA-128 y dónde guardar la estructura en PA-339) antes de escribir código.
