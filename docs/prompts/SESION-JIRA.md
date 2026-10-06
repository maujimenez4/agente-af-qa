# SESIÓN JIRA · Ronda 12: la aprobación de una publicación simulada no puede valer para el modo real (PA-41)

Tu ronda 11 (skill `/auditoria`) ya está fusionada. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-aprobacion origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-aprobacion`**, creada desde `PreProduccion`. Tu ronda 11 ya está fusionada.

**Objetivo: PA-41 (principio 1, aprobación humana).** Hoy, al publicar en **simulación**, `_publish_approved` (`core/graph/nodes.py`) no gasta la aprobación: queda vigente «para publicar de verdad cuando se active `live`», sin caducidad. Si el modo real se activa días después, esa aprobación antigua bastaría para escribir en Jira sin que nadie vuelva a revisar la HU. Hay que resolverlo **antes de cualquier publicación real**: el usuario prepara un ensayo en el sandbox AFQP.

Lee la fila **PA-41** de `docs/KANBAN.md`, T-25 y PA-140/141 (registro de aprobaciones), `core/approvals.py` (`ApprovalLedger`: `record`, `find`, `consume`, `spend`, `publishing`, `was_published`), `_publish_approved` en `core/graph/nodes.py`, y cómo lo cuentan las UI. «La aprobación sigue vigente…» aparece en el Resultado simulado de `docs/specs/UI.md` (§4.7, punto 6 de §5), en `app/` (Streamlit) y en `web/`.

## Qué decidir (propónlo en el plan)
- **Opción A (la que yo prefiero, más simple y segura):** una publicación simulada **gasta** la aprobación, como una real. Queda marcada como «usada en simulación». Para publicar de verdad hace falta otra aprobación humana con el modo real activo. `was_published` sigue siendo falso para una simulada, así que no se genera memoria.
- **Opción B:** la aprobación guarda el modo en que se dio (`simulation` o `live`), y `publishing`/`find` solo la aceptan si coincide con el modo actual. Más flexible, pero cambia el formato guardado del registro: hay que leer los registros antiguos sin modo como `simulation`.
- En cualquier caso:
  - **Nunca** se escribe en Jira con una aprobación dada en simulación.
  - La auditoría dice qué pasó.
  - Lo que ya está guardado se lee sin error.
  - La conversación simulada no se puede «republicar» en real sin pasar otra vez por la revisión humana. Comprueba cómo sería ese camino en la API (`/approve` en una conversación ya `simulated`) y propónlo.

## Reglas
- **Autorizado:** `core/approvals.py` y `_publish_approved` en `core/graph/nodes.py`, solo para PA-41. Sin tocar la lógica de escritura en Jira ni `spend`/`unspend` (PA-141).
- **Textos:**
  - corrige «La aprobación sigue vigente…» en `app/` (Streamlit) y en los mensajes de la API si los hay;
  - **en `web/` y en `docs/specs/UI.md` no:** son del responsable de `web/`. Dime el texto nuevo en tu mensaje final y yo se lo paso.
- **No toques** `schemas/` ni `adapters/`. Si cambia la forma de algo del contrato de la API, solo añade campos opcionales, y regenera el contrato con `uv run python -m api.export_openapi`.
- **Pruebas (fakes):**
  - simular y luego intentar publicar en real con la misma aprobación → rechazado, sin escritura en Jira;
  - con una aprobación nueva en real → publica;
  - los registros guardados antes del cambio se leen;
  - la auditoría de cada caso;
  - una prueba `integration` del registro en PostgreSQL si cambia lo que se guarda (como `tests/unit/test_ledger_concurrency.py`). **No la ejecutes:** la lanza la principal.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-41 con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-243…PA-249** si quedan libres; si no, **PA-410…PA-419**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-aprobacion` y avísame.

Empieza presentándome el plan (opción A o B, cómo se republica en real una conversación simulada y qué cambia en lo guardado) antes de escribir código.
