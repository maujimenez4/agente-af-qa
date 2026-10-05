# SESIÓN JIRA · Ronda 10: Administración mínima (T-29) con la prueba de conexiones

Tu ronda 9 ya está fusionada. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-admin origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-admin`**, creada desde `PreProduccion`. Tu ronda 9 ya está fusionada.

**Objetivo: T-29 mínima.** Es una página de **Administración**, solo para el rol `admin` (`MANAGE_CONNECTIONS` y `MANAGE_MODELS` en `core/permissions.py`; usuario de ejemplo `admin-demo`).
- **Entra:** probar las conexiones y ver los modelos por tarea, **solo lectura**.
- **No entra:** la carga y la gestión de documentos (T-43) ni la gestión de usuarios.

Lee la fila de T-29 en `docs/KANBAN.md`, RF-01, RF-07, RF-40 y RF-41, `docs/specs/UI.md` (Administración y los mensajes que remiten a «Revisa las conexiones en Administración») y cómo está hecha una ruta en `api/`.

## Tareas
1. **Prueba de conexiones** (un servicio en `core/`, por ejemplo `core/health.py`), con un resultado por servicio:
   - **Jira:** una lectura barata, como `list_projects` o `myself`; nunca una escritura.
   - **PostgreSQL:** `SELECT 1` y la revisión de Alembic aplicada frente a `head`.
   - **Ollama** (o el proveedor de cada cadena): que responde y que los modelos de `config/models.yaml` **están descargados** (listar modelos). **Sin generar texto:** la prueba no gasta tokens ni carga un modelo en memoria.
   - **Embeddings:** que el modelo de embeddings está disponible, por el mismo camino, sin embeddear.
   - Cada comprobación lleva su **tiempo límite** (unos pocos segundos) y se ejecutan en paralelo; un fallo no impide las demás.
   - Resultado: `{service, ok, detail, duration_ms}`. `detail` va en español y sin secretos: nada de tokens, cabeceras, cadenas de conexión con contraseña ni trazas. Basta con el host, sin usuario. Los errores, envueltos como siempre (`adapters/errors.py`).
2. **API**, en un módulo propio `api/admin.py` con su `APIRouter` (prefijo `/admin`, solo `admin`; los demás roles reciben 403 con el código existente). En `api/app.py` solo se añade el router a la lista que se incluye: la sesión Modelos está tocando el mismo archivo en paralelo.
   - `POST /admin/connections/test` → la lista de resultados, con un límite de frecuencia por persona (por ejemplo, una cada 10 s; 429 con `retry_after`). Es POST porque hace llamadas externas, y lleva CSRF.
   - `GET /admin/models` → cadena de modelos por tarea (proveedor y modelo; las URL, solo con el host) y el proveedor activo por tarea si el router lo sabe. Sin claves.
   - Ejemplos en las respuestas y apartado en «Novedades para el frontend» de `docs/api/README.md`.
3. **Streamlit (plan B):** página **Administración** en `app/` (vista nueva en `app/views/`), visible solo para `admin`. Tiene el botón «Probar conexiones», con una fila por servicio (✅/❌, detalle y tiempo), y la tabla de modelos por tarea.
4. **Servidor MCP:** no se toca.

## Reglas
- **Solo añade:** rutas nuevas y campos opcionales; nada existente cambia.
- **Contrato:** regenéralo con `uv run python -m api.export_openapi`. Si al fusionar choca con el de la sesión Modelos, lo regenera la principal.
- **Puedes tocar:**
  - `core/health.py` (nuevo);
  - `api/admin.py`, la línea del router en `api/app.py` y `api/models.py` (solo añadir);
  - `app/` (vista y navegación);
  - `docs/api/`;
  - y sus pruebas.

  Si necesitas un método nuevo en un `Protocol` de `adapters/base.py` (congelado), como `ping` o `list_models`, **para y propónmelo** en el plan. No toques `core/graph/`, `schemas/`, `config/` ni `web/`.
- **Pruebas** con fakes:
  - todo bien;
  - un servicio caído y otro que agota el tiempo (los demás siguen);
  - modelo no descargado;
  - `detail` sin secretos (con un fake que lanza un error que contiene una cadena ficticia tipo clave);
  - 403 para `functional` y `qa`;
  - 429 por frecuencia;
  - ninguna llamada de generación al LLM.
- Las pruebas reales llevan `@pytest.mark.integration` y se saltan sin `.env`; **no las ejecutes**, las lanza la principal.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales, ni textos que imiten una clave privada.
- **Kanban:**
  - T-29 → ✅ con la fecha, anotando que es la versión mínima;
  - tu fila en el registro;
  - propuestas en **PA-235…PA-249**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-admin` y avísame.

Empieza presentándome el plan (sobre todo cómo compruebas Ollama y los embeddings sin generar, y si necesitas tocar algún `Protocol`) antes de escribir código.
