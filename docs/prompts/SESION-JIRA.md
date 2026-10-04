# SESIÓN JIRA · Ronda 7: cierres pendientes (PA-143, PA-228, PA-229, PA-278 y PA-280)

Tu PA-114 ya está fusionada y **verificada en el e2e real**: 0 truncados y lectura del prompt la mitad de rápida. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, puesta al día desde `PreProduccion`.

Contexto: el sistema funciona de punta a punta con el modelo local (e2e real del 2026-10-04: HU 5,3 min, evolucionar 7,8 min, suite 5,5 min, sin truncados ni OOM). Esta ronda cierra pendientes.

## Tareas (lee el texto completo de cada PA en `docs/KANBAN.md`)
1. **PA-143:** ReDoS en `_HEADING` de `adapters/jira/adf.py`. Cámbialo por `rstrip()` y sin `\s*$`, con una prueba de tiempo.
2. **PA-228:** `core/graph/nodes.py` debe pasar a `StoryWriter`, `TestWriter` e `ImpactAnalyzer` sus límites (`limits=PromptLimits.from_config(container.config)`) en vez de que los resuelvan con `get_config()`.
3. **PA-229:** `config/models.groq.yaml` necesita su `limits.context_window` real y un `context_token_budget` coherente con la estimación de 3 caracteres por token.
4. **PA-278:** `POSTGRES_HOST` y el puerto en `Settings` (autorizado en `core/config.py`, solo esto).
   - `sqlalchemy_url()` los usa (por defecto `127.0.0.1` y 5432).
   - El servicio `app` de `docker-compose.yml` pasa `POSTGRES_HOST=db` en lugar de componer `DATABASE_URL` con la contraseña sin codificar.
   - Documéntalo en el README.
5. **PA-280:** fija las imágenes base del `Dockerfile` por digest (`@sha256:…`). Consulta los digest actuales y anota en un comentario la versión a la que corresponden.

## Reglas
- **Puedes tocar:**
  - `adapters/jira/`;
  - `core/graph/nodes.py` (solo PA-228);
  - `core/config.py` (solo PA-278);
  - `config/models.groq.yaml`;
  - `docker-compose.yml` (solo el servicio `app`), `Dockerfile` y `README.md`;
  - sus pruebas.

  No toques `api/`, `app/`, `core/approvals.py`, `core/qa/`, `core/functional/`, `core/quality.py` ni `config/models.yaml`.
- **No recrees contenedores** ni cambies el `.env`.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **Nombres en las pruebas:** sin `secret`, `password` ni `token` como nombre de variables con literales, y sin textos que imiten una clave privada (gitleaks).
- **Kanban:**
  - cierra las PA con la fecha;
  - añade tu fila al registro;
  - **propuestas en PA-230…PA-249**.
- **Antes del commit:**
  - `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push origin ses-jira` y avísame.

Empieza presentándome el plan breve antes de tocar código.
