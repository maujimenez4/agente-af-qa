# SESIÓN MODELOS · Ronda 12: contrato de QA para la web (PA-326 y PA-327)

> Encargo de la **sesión Modelos**. Tu ronda 11 (Langfuse, T-40) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-contrato-qa origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-contrato-qa`**, creada desde `PreProduccion`. Tu ronda 11 ya está fusionada.

**Contexto:** el responsable de la web en React (`web/`, T-56) está haciendo el flujo de QA. Ya están QA 1 (Origen) y QA 2 (Generando), y sigue con QA 3 · Iterar la suite (pestañas Casos, Cobertura, Datos y riesgos, Estrategia). Ha pedido dos cosas a la API. Lee sus filas **PA-326** y **PA-327** en `docs/KANBAN.md`, `docs/specs/UI.md` §6.2 y §6.3, y `docs/api/README.md`.

## Tareas
1. **PA-327 · Etiquetas de los pasos por modo.** Hoy `STEP_LABELS` (`api/service.py`) es el mismo en QA que en la HU, y Generando de una suite dice «Generar la propuesta, validar las citas y analizar el impacto».
   - Etiquetas propias de QA en `ProgressStep.label`, con los textos de UI.md §6.2 adaptados a los nodos reales.
   - **Una etiqueta nunca describe lo que el nodo no hace:** si UI.md pide 4 pasos y hay 3 nodos, el texto de `generate` en QA puede juntar lo que hace («Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y estrategia»), pero no se inventan pasos.
   - En QA, `memorize` no se ejecuta (D-07). Comprueba que no sale como paso pendiente que nunca termina.
   - También en el SSE, en `GET /conversations/{id}`, en `/take` y en los ejemplos del contrato.
2. **PA-326 · Conversación de QA en revisión, en el contrato.**
   - **Un ejemplo** de `ConversationOut` de QA en revisión: `flow: tests`, `mode: qa`, `state: in_review` y `review.artifact` con un `TestSuite` sintético (DEMO, 3 o 4 casos sobre CA-01/CA-02 y RN-01/RN-02), `review.plan` con `publish_suite` y la huella. Lo usará el MSW del frontend en lugar de inventar la forma.
   - **La matriz de cobertura** en la revisión de QA, sin IA y sin tocar `schemas/` (congelado): `TestSuite.coverage_md()` ya la calcula (es el adjunto `matriz-<CLAVE>.md`). Propón dónde va, por ejemplo `ReviewPayload.coverage_md: str | None`, solo en QA.
   - **Lo no cubierto:** la pestaña Cobertura necesita saber qué CA o RN de la HU **no** tienen caso. Investiga si la API puede dar los IDs de CA y RN de la HU de origen de forma determinista (la HU que ya cargó el grafo, la entrega de QA encadenada o la estructura de la incidencia) y propón un campo, por ejemplo `uncovered: {criteria: [...], rules: [...]}`. Si en algún origen no se puede saber sin una llamada al LLM, ese campo va `null` y se dice en el contrato. **Nunca** se llama al LLM solo para esto.

## Reglas
- **El frontend ya consume el contrato:** solo se añaden campos opcionales y ejemplos. Nada existente cambia de forma.
  - Regenera el contrato con `uv run python -m api.export_openapi`.
  - Añade filas a «Novedades para el frontend» en `docs/api/README.md`.
- **Puedes tocar:** `api/` y sus pruebas, y `docs/api/`. No toques `schemas/`, `core/`, `adapters/`, `app/` ni `web/`. Si necesitas algo de `core/`, **para y propónmelo**.
- **Pruebas** con `fake_runtime`:
  - las etiquetas de QA en el SSE y en el detalle;
  - las de la HU siguen igual;
  - `coverage_md` y lo no cubierto en una revisión de QA, y su ausencia en una de HU;
  - el ejemplo del contrato valida contra los modelos.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-326 y PA-327 con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-118…PA-124** (tu rango PA-250…PA-299 está casi lleno).
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-contrato-qa` y avísame.

Empieza presentándome el plan (las etiquetas de QA, dónde va la matriz y cómo sabes lo no cubierto en cada origen) antes de escribir código.
