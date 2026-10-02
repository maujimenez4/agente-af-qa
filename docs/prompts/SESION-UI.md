# SESIÓN UI · Ronda 2: T-31, Mixta 5, T-28 y pestaña Memoria (área B · `app/`)

Tu rama `ses-ui` ya está fusionada en `PreProduccion`. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-ui switch -C ses-ui origin/PreProduccion
cd .claude/worktrees/ses-ui
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-ui`**, recién puesta al día desde `PreProduccion`. Tu T-24 ya está fusionada (✅).

Hay **otras sesiones de Claude Code trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra y es dueña de los contratos, el grafo y la composición.
- **Jira:** `ses-jira`, con las pruebas de escritura en el sandbox y T-47.
- **T-32:** `ses-memoria`, con el contador de tokens y el endurecimiento del LLM.
- **Ollama:** la prueba real de punta a punta.

**Solo tocas lo de esta sesión**; si necesitas algo de otra, para y propónlo.

Lee antes:
- `CLAUDE.md`;
- `docs/specs/UI.md`: §4.6, §4.7 y §5 para el recibo y el resultado, §4.8 para Mixta 5, §6 para QA y §7 para los errores;
- el anexo §11 de `docs/specs/SPEC-00-fundacional.md` (versión 1.8);
- en `docs/KANBAN.md`, el registro de los días 6 y 7 y las propuestas de tu rango (PA-150…PA-199) y PA-64, PA-72, PA-73 y PA-251.

## Qué hay nuevo en `PreProduccion`
- **Publicación real:**
  - T-27 escribe la HU, el comentario del diff y los vínculos;
  - T-30 escribe los casos como subtareas, con la estrategia y la matriz como adjuntos;
  - la app ya los usa en `build_app_container`.
  - `JIRA_PUBLISH_MODE` sigue en `simulation`, y `live` está bloqueado hasta validar la escritura en el sandbox.
- **Publicación parcial de QA:** el `PublishResult.failed` de T-30 lleva **IDs de CP y nombres de adjunto** (`estrategia-<CLAVE>.md`, `matriz-<CLAVE>.md`). Volver a publicar es idempotente: no duplica lo que ya existe.
- **T-48 · revisar la calidad:** `core/quality.QualityReviewer(container).review(user, clave, excluded_sources)` → `QualityReview`, con `report` (`QualityReport`) y `evolve_feedback()`.
- **T-33 · memoria:** se genera al publicar. Si falla después de publicar, la HU queda publicada sin memoria (PA-251, lo resuelve la principal).

## Tareas, en este orden (con la skill `/tarea`)

### 1. `/tarea T-31`: recibo de aprobación y resultado [RF-31, RF-32, RNF-16]
Mixta 3 → recibo → Mixta 4, y QA 4 → QA 5:
- **Recibo:** se construye con `plan` del payload, con una casilla por operación. *Aprobar y publicar* se activa con todas marcadas y devuelve la **huella del último payload**.
- **Resultado:**
  - **simulado:** la aprobación sigue vigente y se muestran las operaciones auditadas;
  - **real:** se muestran las operaciones hechas y `published_keys`;
  - **parcial:** `errors` y *Reintentar solo los fallidos*, reanudando con la misma aprobación cuando el grafo lo permita. Si no lo permite, propónlo.
- **Errores:** el `error` de la pausa se muestra junto al recibo o al editor; un `ApprovalError` ofrece «empezar de nuevo».
- **PA-73:** las marcas «Cambiado en vN» / «Nueva» que salgan de `impact.diffs`.

### 2. Mixta 5: «Revisar la calidad» (cierra la parte de UI de T-48) [RF-18]
UI.md §4.8:
- la tarjeta de flujo «Revisar la calidad» solo para quien tenga `GENERATE_STORY` (permiso provisional, PA-100);
- **el informe se pinta campo a campo con `md_escape`:**
  - `report.summary`;
  - `report.invest_in_order()` («Bien» = `ok`, «Mejorable» = `improvable`);
  - `report.findings` con `FINDING_LABELS`, `target_id`, explicación y propuesta;
  - `report.open_questions`.
- **Nunca** pintes `to_markdown()` con `st.markdown`: ese `.md` es solo para *Descargar informe* con `st.download_button` (PA-64).
- *Evolucionar con esto* abre una conversación nueva de evolución con `initial_state(..., feedback=review.evolve_feedback())`.
- La revisión hace **dos llamadas al LLM** (lento en CPU): muestra el progreso.

### 3. `/tarea T-28`: pantallas QA 1 … QA 3 [RF-26]
UI.md §6. El modo QA del grafo ya usa `TestWriter`; la matriz sale de `suite.coverage_md()` y la estrategia de `suite.strategy_md`. El recibo y el resultado de QA siguen el patrón de T-31.

### 4. Pestaña **Memoria** (cierra T-33) [RF-36, RF-51]
Lista de memorias de `data/memory/` (o de los documentos `category='memoria'`) con su clave y su versión, y vista de solo lectura **campo a campo y escapada**. Si te falta un método de lectura del backend, propónlo.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:** `app/`, `.streamlit/` y `tests/unit/test_app_*.py`.
  - No toques `core/`, `adapters/`, `schemas/`, `prompts/`, `migrations/`, `config/` ni la SPEC.
  - En `tests/fakes/` solo puedes añadir, sin romper nada.
  - Si necesitas un cambio de backend o de contrato, **para** y escríbelo como propuesta.
- **Kanban:**
  - Cambia solo el estado de tus filas (T-31, T-28, T-33 cuando cierres la pestaña, y las PA que cierres).
  - Añade tu propia fila al registro diario.
  - No toques el tablero resumen.
  - **Propuestas en PA-153…PA-199.**
- **Seguridad:**
  - Invoca el grafo **siempre** con `new_conversation_config` o `resume_config`.
  - El contenido de Jira, del RAG y del LLM nunca va a `st.html` ni a `unsafe_allow_html`.
  - Solo `publish` escribe en Jira.
  - Deja `JIRA_PUBLISH_MODE=simulation`.
  - No leas ni muestres el `.env`.
  - Ni secretos ni datos personales reales.
  - Los logs no registran prompts ni contenido.
- **LLM:**
  - Las pruebas automáticas usan fakes.
  - Desde el 2026-10-01 solo se usan modelos locales de Ollama (`config/models.yaml`), que en CPU son lentos: no lances pruebas reales con LLM sin preguntarme.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-XX: descripción [RF-YY]`, **uno por tarea**.
  - **Sin fusionar.** Haz `git push origin ses-ui` al terminar cada tarea y avísame.

Empieza por `/tarea T-31` y preséntame el plan antes de escribir código.
