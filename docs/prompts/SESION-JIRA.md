# SESIÓN JIRA · Ronda 6: PA-114, que el contexto nunca se trunque en silencio (arreglo completo)

Tu ronda 5 ya está fusionada en `PreProduccion`. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, recién puesta al día desde `PreProduccion`. Tu ronda 5 ya está fusionada.

**En esta ronda haces PA-114, prioridad alta.** Sale de la prueba real de punta a punta. Lee antes el informe `docs/pruebas/E2E-local-2026-10-02.md`, sobre todo §6.1.

## El problema (medido)
- Evolucionar, la suite, iterar y revisar la calidad desbordan la ventana de 8192 tokens de Ollama.
- Ollama hace *context shift*: descarta ~4000 tokens del principio (instrucciones y fuentes) y **responde 200 con una salida que valida**. El agente no se entera.
- **Causa:** `core/context/budget.py` estima `caracteres / 4` (`CHARS_PER_TOKEN = 4`), pero en español con qwen3 se miden **~3,2 caracteres por token** (instrucciones 3,35; contexto 3,19; HU previa 3,02).

  El contexto «de 4108 tokens» ocupa ~5500 reales. Por eso el presupuesto de 6000 ni se alcanzaba y bajarlo a 4500 no cambiaba nada.

## Decisión del usuario: arreglo completo
1. **Estimación honesta:** `CHARS_PER_TOKEN = 3` en `core/context/budget.py`. Revisa y ajusta las pruebas que dependan del 4.
2. **Presupuesto equivalente al medido.** Ollama midió que `context_token_budget: 2500` con `/4` (unos 10 000 caracteres de contexto) cabe con margen en todas las llamadas. Con `/3` el equivalente es **~3300**.

   Cambia en `config/models.yaml` **solo** `limits.context_token_budget` (a 3300) y el valor por defecto de `core/context/service.py` (`DEFAULT_TOKEN_BUDGET`). Autorizado por la principal.
3. **Ventana configurable** (autorizado en `core/config.py`, solo esto): `limits.context_window` (tokens de la ventana del modelo), por defecto 8192, y en `config/models.yaml` con 8192.
4. **Guarda antes de llamar al LLM** en los escritores con mucho contexto: `core/functional/writer.py` (generar, evolucionar, estructurar, iterar), `core/qa/writer.py` (suite) y `core/quality.py` (revisión). Valora también `core/impact/` y `core/memory/`.
   - Estima el mensaje **completo**: instrucciones + contexto + HU previa + feedback + reintento si lo hay.
   - Comprueba que **estimado + `max_output_tokens` de la tarea ≤ `context_window`**.
   - Si no cabe, recorta primero las fuentes de menos prioridad: los últimos fragmentos del RAG y después las HU relacionadas. **Nunca** la HU de origen, la HU previa ni las instrucciones.
   - Si ni así cabe, error claro en español (`AgentError`). Nunca un truncado silencioso.
   - **Los reintentos (de citas, de cobertura) también pasan por la guarda:** son los mensajes más largos.
   - El recorte queda en el log, sin contenido (solo recuentos).
5. **Mide la estimación:** con un par de textos reales del corpus (`data/seed/corpus/`), comprueba que `/3` no se queda corto respecto a lo que midió Ollama (§6.1 del informe), y deja un margen.
6. **Imports de `escape_data`** en `core/qa/`: cámbialos a `core.text`.

## Reglas
- **Puedes tocar:**
  - `core/context/budget.py` y `core/context/service.py` (presupuesto);
  - `core/functional/writer.py`, `core/qa/`, `core/quality.py`, `core/memory/` e `core/impact/` (si aplica);
  - `core/config.py` (solo el campo autorizado) y `config/models.yaml` (solo `context_token_budget` y `context_window`);
  - sus pruebas.

  **No toques `core/functional/context.py` ni `core/functional/citations.py`:** la sesión Modelos está cambiando ahí cómo se presentan y reparan las citas. Si chocáis en `core/functional/writer.py`, avísame.
- **Kanban:** cierra PA-114 con la fecha; tu fila en el registro; propuestas en PA-228…PA-249.
- **Pruebas:** con fakes, incluido el caso límite (justo cabe; no cabe y se recorta; ni recortando cabe → error; el reintento también se recorta) y que el origen, la HU previa y las instrucciones nunca se recortan. Nada contra el LLM real.
- **Nombres en las pruebas:** no uses `secret`, `password` ni `token` como nombre de variables con valores literales, ni texto que imite una clave privada. Gitleaks los marca y el CI falla.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar:** `git push origin ses-jira` y avísame.

Empieza presentándome el plan (dónde va la guarda, cómo estima y qué recorta) antes de escribir código.
