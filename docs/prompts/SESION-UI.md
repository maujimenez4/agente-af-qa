# SESIÓN MODELOS · Ronda 7: citas de Jira sin reintento (PA-281)

> Este archivo es el encargo de la **sesión Modelos**. Tu ronda 6 (`ses-huecos`) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-citas origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-citas`**, creada desde `PreProduccion`. Tu ronda 6 ya está fusionada.

**En esta ronda haces PA-281: quitar el reintento de citas de la HU nueva.** Ahora mismo cuesta ~5–6 minutos por HU en CPU.

## El problema (medido en la prueba real)
Lee antes `docs/pruebas/E2E-local-2026-10-02.md`, §5.3, y la captura `docs/pruebas/salidas/e2e-a-citas.json`.

- En 3 de 3 ejecuciones, la primera llamada de la HU nueva falla por citas y el reintento las corrige: **5,5 min perdidos por HU**.
- **Causa:** cada fuente de Jira llega como `<fuente ref="AFQP-12" tipo="jira" …>`, pero su texto empieza por «Historia · Tareas por hacer / **Épica/padre: AFQP-10**» (`core/functional/context.py`, `_jira_source`). `qwen3:1.7b` cita la clave que lee en el texto (la épica), no la del atributo `ref`.
- Los tres errores son exactamente los padres de las tres HU del contexto: AFQP-12 → AFQP-10, AFQP-2 → AFQP-1, AFQP-25 → AFQP-17. Los extractos sí son los de la HU correcta.
- El RAG no falla porque sus fragmentos no mencionan otros `DOC-NN`.

## Decisión del usuario: las dos medidas
1. **Presentación:** que el texto de cada fuente de Jira empiece por su **propia clave** (p. ej. «Clave: AFQP-12 · Historia · Tareas por hacer») y que la épica o el padre vaya al final, marcada como relación («Pertenece a la épica AFQP-10»). Así la primera clave que lee el modelo es la que debe citar.
   - Revisa que no rompe el troceado del contexto, el presupuesto ni las pruebas de `render_context`.
2. **Reparación determinista, sin LLM**, en `core/functional/citations.py`. Si una cita de Jira no existe en el contexto pero su `excerpt` coincide con el de una fuente recibida (con normalización de espacios y mayúsculas, y coincidencia suficientemente exacta), se sustituye su `ref` por la de esa fuente **antes** de decidir el reintento, como hace `repair_ids` con los IDs.
   - **Solo** sustituye si la coincidencia es inequívoca (una sola fuente). Si no, se mantiene el error y hay reintento: **nunca** se inventa trazabilidad.
   - Que el log diga cuándo se reparó, sin contenido.
   - Aplica también a las suites (`core/qa/writer.py`) si usan el mismo camino de citas.

## Reglas
- **Puedes tocar:** `core/functional/context.py`, `core/functional/citations.py`, el camino de citas de `core/qa/` y sus pruebas.
- **No toques:**
  - `core/functional/writer.py` en lo que no sea llamar a la reparación: la sesión Jira está metiendo ahí la guarda de la ventana de contexto (PA-114). Si chocáis, avísame.
  - `core/context/`, `api/`, `app/`, `web/`, `config/` ni los contratos.
- **Kanban:** añade y cierra PA-281 con la fecha; tu fila en el registro; propuestas en PA-282…PA-299.
- **Pruebas:**
  - el texto de la fuente empieza por su clave;
  - una cita a la épica con el extracto de la HU se repara sin segunda llamada al LLM;
  - una cita ambigua o sin extracto coincidente sigue provocando reintento;
  - una cita inventada sin coincidencia sigue siendo error.

  Solo fakes; nada contra el LLM real.
- **Nombres en las pruebas:** no uses `secret`, `password` ni `token` como nombre de variables con valores literales, ni texto que imite una clave privada. Gitleaks los marca y el CI falla.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar:** `git push -u origin ses-citas` y avísame.

Empieza presentándome el plan antes de escribir código.
