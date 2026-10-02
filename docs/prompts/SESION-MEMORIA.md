# SESIÓN UI · Ronda 5: T-35, prueba cruzada (el área B prueba el área A)

> Este archivo era el prompt de la sesión Memoria/Modelos (T-32, T-58, ya fusionadas). Ahora lo usa la **sesión UI**.

Tu T-28 ya está fusionada en `PreProduccion`. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-ui origin/PreProduccion
cd .claude/worktrees/ses-ui
uv sync
uv run pytest -m "not integration"          # en verde, con 50 xfailed (los de T-34)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-ui`**, recién puesta al día desde `PreProduccion`. Tus T-28, T-31 y la pantalla de T-48 ya están fusionadas.

**En esta ronda haces T-35: la prueba cruzada del área A, con mirada de fuera.** Es el espejo de T-34, que hizo la sesión Jira sobre el área B (mira `tests/unit/test_cross_b_*.py` y las PA-211…PA-224 como ejemplo del formato). La pestaña Memoria en Streamlit queda aparcada.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`; contratos, API y composición.
- **Modelos:** `ses-flujo`, con T-54, en `core/graph/`, `core/conversations.py`, `core/qa/` y una migración nueva.
- **Jira:** `ses-jira`, corrigiendo los defectos de T-34 en `core/rag/`, `core/memory/`, `core/quality.py`, `core/guided_start.py` y `adapters/embeddings|vectorstore/`.
- **Ollama:** medición de modelos y `config/models.yaml`.

## `/tarea T-35` [RNF-19]
**Solo pruebas nuevas e informe: no cambies el código del área A.**

- **Alcance:**
  - `adapters/jira/` (búsqueda con `nextPageToken`, ADF, escritura, errores y reintentos);
  - `adapters/testmgmt/` (subtareas, adjuntos, idempotencia, `record_execution`);
  - `adapters/llm/` (salida estructurada, reparación de IDs de T-58, `schema_hints`, respaldo y 429, tiempo de espera);
  - `adapters/auth/` (contraseñas, tiempo constante);
  - `core/context/` (JQL seguro, presupuesto de contexto);
  - `core/state_machine.py`, `core/audit.py`, `core/artifact_state.py` y `core/approvals.py` (registro de aprobaciones);
  - `core/impact/` (diff y análisis de impacto);
  - `core/graph/execution.py` (T-47);
  - `api/` (sesión, CSRF, propiedad, SSE, `/executions`).
- **Fuera del alcance:** `core/graph/nodes.py`, `core/graph/state.py` y `core/conversations.py` (los está cambiando T-54).
- **Cómo:**
  - `test-writer` para las pruebas que falten frente a los RF, RNF y requisitos (en `api/`, también `docs/api/requisitos-parte-2.md`);
  - `spec-checker` para comparar con la SPEC-00 y el contrato `docs/api/openapi.yaml`;
  - las pruebas van en archivos nuevos `tests/unit/test_cross_a_*.py`.
- **Si encuentras un fallo:**
  - marca la prueba con `xfail(strict=True)`, con el archivo y la línea;
  - anótalo como propuesta.

  No lo corrijas: lo decide la principal.
- **Informe** en tu fila del registro diario: qué cubriste, los fallos (con su PA) y lo que queda sin cubrir.

## Reglas
- **Solo creas:** `tests/unit/test_cross_a_*.py` (y, para añadir, `tests/fakes/`). No toques código de producción, `app/`, `web/`, los contratos ni la SPEC.
- **Kanban:** cambia solo T-35 (a 🔄 y luego ✅) y añade tu fila al registro. No toques el tablero. **Propuestas en PA-161…PA-199.**
- **Seguridad:** no leas el `.env`; datos ficticios; nada contra Jira ni LLM reales (las pruebas `integration` que añadas se saltan sin credenciales).
- **Cuidado con los hilos:** cierra los `graph.stream` y no dejes generadores abiertos (ya viste el bloqueo en `test_graph.py`).
- **Antes del commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commit:** `T-35: prueba cruzada del área A por el área B [RNF-19]`. **Sin fusionar:** `git push origin ses-ui` y avísame.

Empieza por `/tarea T-35` y preséntame el plan antes de escribir pruebas.
