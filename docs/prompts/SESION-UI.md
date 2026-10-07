# SESIÓN MODELOS · Ronda 14: una suite de QA que no cubre un criterio no debe tirar 12 minutos de trabajo (PA-426)

> Encargo de la **sesión Modelos**. Tu ronda 13 (PA-331 y PA-330) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-qa-cobertura origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-qa-cobertura`**, creada desde `PreProduccion`. Tu ronda 13 ya está fusionada.

## El fallo (prueba real del usuario con la web, 2026-10-07)
Con `qa-demo`, generar la suite de una HU de AFQP con **dos criterios (CA-01 y CA-02)** terminó en `CoverageError` tras **12 minutos**:
- **Primer intento** (`generate_tests`, 316 s): `qwen3:1.7b` generó 6 casos, todos sobre CA-01 y ninguno sobre CA-02.
- **Reintento** (`tests_retry`, 338 s, con el RAG recortado): devolvió **exactamente los mismos 6 casos**, aunque el reintento le decía que faltaba CA-02.

La principal lo comprobó pasando las salidas guardadas en Langfuse por `core/qa/validation.coverage_errors`: `['criterios sin ningún caso de prueba: CA-02']`. Es la misma limitación del modelo pequeño que deja las RN sin caso (PA-122): repetir la petición entera no ayuda.

## Objetivo: PA-426
1. **Reintento dirigido.** Cuando la suite solo falla porque faltan criterios (y no por IDs inventados, falta de positivo y negativo, datos personales o citas):
   - en vez de regenerar la suite entera, pide al modelo **solo los casos de los CA que faltan**, con un prompt nuevo y corto (`prompts/tests_missing.md`, con su `version:`);
   - ese prompt lleva el texto de esos CA, sus RN y los IDs ya usados, para que numere a continuación;
   - **añade** esos casos a la suite que ya existía y valida el resultado completo.

   Es más corto, más rápido y mucho más fácil para un modelo pequeño. Si fallan otras cosas, el reintento de siempre (`tests_retry`) sigue igual.
2. **Si aun así queda algún CA sin caso, no se pierde el trabajo.**
   - La suite pasa a revisión con el aviso, en lugar de `CoverageError`: `ReviewPayload.uncovered` ya dice qué CA faltan (PA-326) y la pestaña Cobertura lo pinta.
   - **No se puede aprobar** mientras haya un CA sin caso: `approve` devuelve la revisión con `review.error`, por ejemplo «Falta al menos un caso para CA-02: pídeselo al agente antes de aprobar.».
   - La persona lo pide iterando, y PA-331 ya aplica la petición.
   - **El contrato no cambia** (`uncovered` y `review.error` ya existen).
3. **Las RN no cambian:** siguen siendo un aviso, sin bloquear (decisión del 2026-10-06).

## Reglas
- **Puedes tocar:**
  - `prompts/` (nuevo `tests_missing.md`);
  - `core/qa/`;
  - lo mínimo de `core/graph/nodes.py` para el aviso y el bloqueo al aprobar en QA, sin tocar `publish` ni `_publish_approved`;
  - y sus pruebas.

  No toques `web/`, `api/` (salvo que el bloqueo lo exija; en ese caso, sin cambiar el contrato), `schemas/` ni `adapters/`.
- **Pruebas con fakes:**
  - una suite sin CA-02 dispara el reintento dirigido y lo fusiona, con la numeración seguida;
  - si el dirigido tampoco lo cubre, la suite llega a revisión con `uncovered` y aprobarla da `review.error`;
  - con otros errores se usa el reintento de siempre;
  - iterar pidiendo «añade un caso para CA-02» permite aprobar después.
- **Prueba real:** reproduce el caso con el modelo local, una HU de AFQP con 2 o 3 CA. **Pide permiso al usuario antes** (unos 10 minutos) y no pases la batería completa mientras dure. Mira la traza en Langfuse.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - añade PA-426 como hecha con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-432…PA-434**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-qa-cobertura` y avísame.

Empieza presentándome el plan antes de escribir código.
