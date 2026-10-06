# SESIÓN MODELOS · Ronda 13: iterar en QA aplica el cambio pedido (PA-331) y presupuesto rápido en Origen (PA-330, API)

> Encargo de la **sesión Modelos**. Tu ronda 12 (PA-326 y PA-327) ya está fusionada. El responsable de `web/` está ausente: el usuario ha decidido terminar los pendientes con sesiones.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-qa-iterar origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-qa-iterar`**, creada desde `PreProduccion`. Tu ronda 12 ya está fusionada.

**Contexto:** la prueba de la web contra la API real (`docs/pruebas/WEB-API-2026-10-05.md`) encontró dos cosas de backend. Lee sus filas **PA-331** y **PA-330** en `docs/KANBAN.md`.

## Tareas
1. **PA-331 · Iterar en QA no aplica el cambio pedido** (prioridad alta para la demo). Al pedir un cambio a una suite, la v2 sale sin el cambio: `prompts/generate_tests.md` (v2) no menciona el bloque `<feedback>`, y `TestWriter` (`core/qa/`) regenera desde la HU sin la suite anterior. Mira cómo lo resuelve la HU (`prompts/evolve_story.md`, `previous=` y `feedback=` en `core/functional/`) y haz lo equivalente en QA:
   - **La suite actual** va al prompt delimitada como datos (por ejemplo `<suite_actual>`). Nueva versión del prompt (`version:`).
   - **El feedback** va como petición de la persona, **no como instrucciones** que anulen las reglas (inyección).
   - **Los IDs de los casos que no cambian se mantienen** (CP-01… igual), para que «Nuevo en vN» y la comparación de versiones tengan sentido.
   - **Presupuesto de tokens:** la suite anterior entra en la ventana. Usa `fit_context` y los límites de `PromptLimits` como el resto, y cuenta qué pasa si no cabe.
   - **Una RN sin caso:** decide con el usuario si se exige al menos un caso por RN (hoy solo por CA). Propónlo en el plan; no lo cambies sin confirmación.
2. **PA-330 (solo la parte de la API) · Presupuesto rápido en Origen.** Hoy marcar o desmarcar una fuente vuelve a pedir `POST /start/sources`, que tarda de 2 a 10 s. Propón la opción más barata de estas dos:
   - devolver los `tokens` estimados de cada fuente y, en `budget`, los fijos y el límite, para que la web recalcule al instante;
   - o cachear unos minutos el contexto reunido por origen y recalcular solo el presupuesto.

   Solo añade campos opcionales al contrato. La parte de la web la hará otra sesión.

## Reglas
- **Puedes tocar:**
  - `prompts/generate_tests.md` (y `tests_retry.md` si hace falta);
  - `core/qa/`;
  - lo mínimo de `core/graph/nodes.py` para pasar la suite anterior al escritor, sin tocar `publish` ni `_publish_approved`;
  - `api/` y `docs/api/` (PA-330);
  - y sus pruebas.

  No toques `schemas/`, `adapters/`, `app/` ni `web/`.
- **Pruebas con fakes:**
  - el prompt de una iteración de QA lleva la suite anterior y el feedback delimitados;
  - los IDs que no cambian se conservan;
  - un feedback con órdenes («ignora las reglas») no quita casos negativos;
  - la suite anterior se recorta si no cabe;
  - PA-330: los campos nuevos.
- **Prueba real con el modelo local:** una iteración de QA tarda unos 4 o 5 minutos. **Pide permiso al usuario antes de lanzarla.** Con permiso, comprueba con una suite real de AFQP que la v2 recoge el cambio pedido (por ejemplo, «añade un caso de excepción para cuando el catálogo no responde»). Mira la traza en Langfuse.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-331 (y PA-330 si aplica, indicando que falta la web) con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-122…PA-124**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-qa-iterar` y avísame.

Empieza presentándome el plan antes de escribir código. Sobre todo:
- cómo entra la suite anterior en el prompt;
- qué pasa si no cabe;
- la pregunta de las RN;
- qué opción eliges para PA-330.
