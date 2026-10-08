# SESIÓN MODELOS · Ronda 16: la HU de origen nunca se recorta (PA-442) y modelos mixtos para la demo (PA-443)

> Encargo de la **sesión Modelos**. Tu ronda 15 (PA-432) ya está fusionada.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-modelos-mixto origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-modelos-mixto`**, creada desde `PreProduccion`. Tu ronda 15 ya está fusionada.

**Contexto:** ayer medimos Groq (nivel gratuito) frente al modelo local. Lee `docs/pruebas/medidas-groq-vs-local-2026-10-07.md` y las filas **PA-440, PA-441, PA-442 y PA-443** de `docs/KANBAN.md`.
- Con Groq, una HU baja de unos 5 minutos a 11 segundos y la calidad mejora mucho.
- Pero el nivel gratuito admite **8000 tokens por minuto** (entrada + salida prevista) en `gpt-oss-120b`: la suite apenas cabe y la iteración de una suite no cabe (413).
- **Decisión del usuario:** Groq para crear y evolucionar HU y para la calidad; Ollama local para QA. La demo es la semana que viene: tiene que quedar fiable.

## Tareas (propón el plan antes de escribir código)
1. **PA-442 · La HU de origen nunca se recorta.**
   - Hoy `fit_context` (`core/context/budget.py`, hacia la línea 130) aplica el presupuesto también al origen: `truncate_issue(issue, …)` con `is_origin`. Con `context_token_budget: 1500`, AFQP-27 (6 CA) se estructuró con solo CA-01…CA-04. Esa estructura se guardó como compartida (PA-432) y la suite «cubría todo» frente a una HU recortada, así que el bloqueo de PA-426 no saltó.
   - El presupuesto solo debe recortar **las fuentes opcionales** (otras incidencias, RAG, feedback). Si la HU de origen no cabe en la ventana del modelo, se falla con el error claro de «no cabe» (`ContextOverflowError`), nunca con una HU recortada en silencio.
   - Revisa todos los caminos que usan el origen: estructurar (`_baseline`, `origin_only`), generar HU, evolucionar, QA y calidad.
   - La huella de la estructura compartida (PA-432) debe salir del texto **sin recortar**.
2. **PA-443 · Configuración mixta en `config/models.yaml`.**
   - **Groq:**
     - `generate_story`, `evolve_story` (también estructura) y `review_story` → `openai/gpt-oss-120b`;
     - `analyze_impact`, `synthesize_memory`, `classify_source` y `nl_to_jql` → `openai/gpt-oss-20b`;
     - todas con **respaldo local** (`qwen3:1.7b`).
   - **Local:** `generate_tests` → `qwen3:1.7b` con `phi4-mini` de respaldo, como hoy.
   - **Los límites son globales y aquí chocan.** Propón cómo resolverlos:
     - el presupuesto de contexto: Groq necesita unos 2000 por su límite por minuto, y el local usaba 3300;
     - la ventana de contexto: 10 240 del local frente a 131 072 de `gpt-oss`;
     - los topes de salida: `gpt-oss` razona y su razonamiento cuenta como salida, así que no admite los topes del local (2854 de salida en una HU).

     Si hace falta un ajuste por tarea o por proveedor en `core/config.py` (congelado), dilo en el plan: está autorizado solo para esto.
   - **Esperar a Groq antes de caer al local.** Con 429 y `Retry-After` de 20 a 50 s, hoy `max_wait_s=20` hace que se pase enseguida al respaldo. Si el respaldo es el local (minutos), es mejor esperar el minuto de Groq. Propón el umbral.
   - **El 413** («no cabe en el minuto») debe pasar al respaldo sin reintentar Groq.
   - **Registra el código HTTP** en `llm_provider_failed` (hoy solo `reason: error`; PA-441). Solo el código, nunca el cuerpo.
   - **Guarda las otras dos configuraciones** como plan B, todo local y todo Groq (`config/models.groq.yaml` ya existe), y documenta en `config/` cómo se cambia con `MODELS_CONFIG_PATH`.
   - **D-14:** solo modelos open-weight y gratuitos. `gpt-oss` lo es.

## Reglas
- **Puedes tocar:**
  - `config/`, `core/context/`, `core/functional/` y lo mínimo de `core/graph/nodes.py`, sin tocar `publish` ni `_publish_approved`;
  - `adapters/llm/`, para la espera y el código HTTP;
  - y sus pruebas.

  No toques `web/`, `api/` (el contrato no cambia), `schemas/` ni `app/`.
- **Pruebas con fakes:**
  - una HU de origen larga no se recorta y, si no cabe, da el error de «no cabe»;
  - las fuentes opcionales sí se recortan;
  - la huella compartida usa el texto completo;
  - cada tarea va a su proveedor;
  - el 429 de Groq espera hasta el umbral antes de pasar al local;
  - el 413 pasa al respaldo sin reintentar;
  - el código HTTP aparece en el registro.
- **Prueba real, con permiso del usuario:**
  - una HU nueva con Groq (`af-demo`) y su revisión de calidad;
  - una suite de AFQP-27 con el local (`qa-demo`), sin aprobar ni publicar: el `.env` está en modo **live**;
  - comprueba que AFQP-27 se estructura con sus **6 CA**.

  No leas el `.env` (tiene `GROQ_API_KEY`) y no pases la batería completa mientras dure.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-442 y PA-443 con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-445…PA-447**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-modelos-mixto` y avísame.

Empieza presentándome el plan antes de escribir código.
