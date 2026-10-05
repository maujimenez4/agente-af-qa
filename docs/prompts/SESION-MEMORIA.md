# SESIÓN UI · Ronda 7: robustez del núcleo (PA-140, PA-142, PA-145, PA-146 y PA-277)

> Encargo de la **sesión UI**. Tu ronda 6 (defectos de T-35) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-ui origin/PreProduccion
cd .claude/worktrees/ses-ui
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-ui`**, puesta al día desde `PreProduccion`.

Contexto: el sistema ya funciona de punta a punta con el modelo local. El e2e real del 2026-10-04 pasa sin truncados, sin reintentos de citas y sin OOM (`docs/pruebas/E2E-local-2026-10-02.md`). Esta ronda es de **robustez**: ninguna PA cambia el comportamiento visible.

## Tareas (lee el texto completo de cada PA en `docs/KANBAN.md`)
1. **PA-140:** escritura atómica del registro de aprobaciones **entre procesos**. Propón en el plan una de dos opciones:
   - escritura condicional en `ArtifactStateStore` (una revisión dentro del estado y `UPDATE … WHERE revision = …`);
   - o `SELECT … FOR UPDATE`.

   Que un cambio de otro proceso (p. ej. `consumed=True`) nunca se pierda. Si toca el protocolo `ArtifactStateStore` (`core/artifact_state.py`), está autorizado; mantén el almacén en memoria compatible.
2. **PA-146:** serializa la comprobación de versión de `StoryVersionStore.save` (`SELECT … FOR UPDATE` sobre la fila de `artifacts`).
3. **PA-145:** el aviso de presupuesto diario también se evalúa tras registrar los tokens de una llamada fallida (`adapters/llm/fallback.py`).
4. **PA-142:** el detector de datos personales de `core/qa/validation.py` tiene coste cuadrático. Usa el enfoque que ya tiene `core/graph/execution.py` y que haya un único detector común.
5. **PA-277:** la UI de Streamlit usa el almacén persistente de revisiones de calidad (`QualityReviewStore`, como la API) y su lista.

## Reglas
- **Puedes tocar:**
  - `core/approvals.py`, `core/artifact_state.py` y `core/impact/versions.py`;
  - `adapters/llm/fallback.py`;
  - `core/qa/validation.py`, `core/graph/execution.py` (solo para compartir el detector) y un módulo común nuevo si hace falta;
  - `app/` (PA-277);
  - sus pruebas.

  No toques `api/`, `core/functional/`, `core/context/`, `adapters/jira/`, `config/` ni `schemas/`.
- **Pruebas:**
  - las de concurrencia entre procesos o con PostgreSQL llevan la marca `integration` y usan bases de datos temporales; se pueden ejecutar (Postgres está levantado);
  - pruebas de tiempo para PA-142.
- **Windows:** si `pytest` está bloqueado por la directiva de aplicaciones, usa `uv run python -m pytest`.
- **Nombres en las pruebas:** no uses `secret`, `password` ni `token` como nombre de variables con valores literales, ni texto que imite una clave privada (gitleaks).
- **Kanban:**
  - cierra las PA con la fecha;
  - añade tu fila al registro;
  - **propuestas en PA-147…PA-149, después PA-150+ libres**.
- **Antes del commit:**
  - `uv run python -m pytest -m "not integration"`, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push origin ses-ui` y avísame.

Empieza presentándome el plan (sobre todo PA-140) antes de escribir código.
