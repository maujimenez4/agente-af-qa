# SESIÓN UI · Ronda 6: corregir los defectos de la prueba cruzada T-35

> Este archivo era el prompt de la sesión Memoria/Modelos y después el de T-35. Ahora es el siguiente encargo de la **sesión UI**.

Tu T-35 ya está fusionada en `PreProduccion` (794 pruebas, 87 `xfail` estrictos, PA-161…PA-199). Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-ui origin/PreProduccion
cd .claude/worktrees/ses-ui
uv sync
uv run pytest -m "not integration"          # en verde, con 137 xfailed (T-34 y T-35)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-ui`**, recién puesta al día desde `PreProduccion`. Tu T-35 ya está fusionada.

**En esta ronda corriges los defectos que encontraste.** La principal te autoriza a tocar el código de esas PA, incluido `core/approvals.py`, que es de la principal.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`; la API (`api/`). **PA-161, PA-162 y PA-163 las hace la principal:** no las toques.
- **Jira:** `ses-jira`, corrigiendo los defectos de T-34 en `core/rag/`, `core/memory/`, `core/quality.py`, `core/guided_start.py`, `adapters/embeddings|vectorstore/` y **`core/context/service.py`** (solo `NOT_STORIES`).
- **Modelos:** `ses-demo`, con el README y el guion de la demo (solo documentación y `eval/`).
- **Ollama:** fase 3, la prueba real de punta a punta. **Usa el LLM en esta misma máquina:** ejecuta la suite completa pocas veces.

## Orden de trabajo
**Bloque 1 · aprobación humana y seguridad (principio 1), lo primero:**
- **Registro de aprobaciones** (`core/approvals.py`):
  - PA-171 (registro que no es un objeto: falla cerrado con `ApprovalError`);
  - **PA-172** (reabrir una aprobación consumida);
  - **PA-173** (segundo `consume`);
  - **PA-174** (dos instancias sobre el mismo almacén: releer antes de decidir o una comprobación atómica);
  - PA-175 (`offer` fija el destino antes de validar).

  **Todo debe fallar cerrado.**
- PA-176: `transition` con tipos inválidos da `InvalidTransitionError`.
- **PA-187:** ReDoS en `_TABLE_SEPARATOR` del ADF. Comprueba que el texto más largo permitido se procesa en milisegundos.
- **PA-178:** evidencia de la ejecución con datos que parecen personales o secretos. Recházala en la revisión con un mensaje claro, como hace la validación de la suite con los datos personales.
- PA-179: auditar el `publish` de la ejecución aunque falle el guardado final.
- **PA-177 no es un defecto:** es una decisión de diseño de la principal. El registro de la ejecución termina en `publish`, así que en simulación consume su aprobación (en `live` se registra de nuevo). **Invierte esa prueba** para que fije este comportamiento, y cierra la PA como «Decisión: comportamiento intencionado».

**Bloque 2 · errores en español y robustez de los adaptadores:**
- Jira: PA-183, PA-184, PA-185, PA-186, PA-188, PA-189, PA-190 y PA-195.
- LLM: PA-191, PA-192, PA-193 y PA-194.
- Autenticación: PA-164 y PA-196.

**Bloque 3 · contexto, impacto y versiones:**
- PA-165, PA-167 y PA-197: `core/context/`. **Ojo:** la sesión Jira toca `NOT_STORIES` en `core/context/service.py` por PA-223. Para no pisaros, haz PA-166 en último lugar y, si coincidís en el archivo, avísame.
- PA-168, PA-169, PA-170, PA-180 y PA-181: `core/context/jql.py`.
- PA-182, PA-198 y PA-199: `core/impact/`.

## Cómo
- Por cada PA, quita el `xfail` de sus pruebas (o inviértelas si fijaban un comportamiento) y corrige el código hasta que pasen.
- Si una corrección necesita cambiar un contrato (`schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py`), **para y escríbelo como propuesta**.
- Un commit por bloque: `T-35: corrige PA-1XX… [RF-YY]`.
- Cierra cada PA en el Kanban con la fecha.

## Reglas
- **Puedes tocar:**
  - `core/approvals.py`, `core/state_machine.py`, `core/graph/execution.py` y `core/artifact_state.py`;
  - `core/context/` (con la salvedad de arriba) y `core/impact/`;
  - `adapters/jira/`, `adapters/testmgmt/`, `adapters/llm/` y `adapters/auth/`;
  - sus pruebas y `tests/unit/test_cross_a_*.py`.

  No toques `api/`, `app/`, `web/`, `core/graph/nodes.py`, `core/handoff.py`, `config/` ni los contratos.
- **Kanban:** cambia solo las PA que cierres y añade tu fila al registro. No toques el tablero. **Propuestas nuevas en PA-140…PA-149** (el rango PA-161…PA-199 está lleno).
- **Seguridad:** no leas el `.env`; datos ficticios; los logs no llevan contenido ni secretos.
- **LLM:** solo fakes.
- **Antes de cada commit:**
  - pruebas de los módulos tocados, y la suite completa solo al cerrar cada bloque;
  - `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO al terminar cada bloque.
  - Pide a los subagentes que no maten procesos globales y que lancen pytest de uno en uno.
- **Sin fusionar.** Haz `git push origin ses-ui` al terminar cada bloque y avísame.

Empieza por el bloque 1 y preséntame el plan breve antes de tocar código.
