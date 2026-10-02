# SESIÓN JIRA · Ronda 6: PA-114, que el contexto nunca se trunque en silencio

Tu ronda 5 ya está fusionada en `PreProduccion` (PA-208 real ✅, PA-183…PA-190, PA-195, PA-226 y PA-227). Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-jira origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
uv run pytest -m "not integration"          # en verde, con 62 xfailed (defectos de T-35 en curso)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-jira`**, recién puesta al día desde `PreProduccion`. Tu ronda 5 ya está fusionada.

**PA-187 (ReDoS del ADF) no es tuya:** está en el bloque 1 de la sesión UI.

**En esta ronda haces PA-114, prioridad alta**, que sale de la prueba real de punta a punta. Al evolucionar AFQP-3 con `qwen3:1.7b`, el agente envió 7362 tokens de entrada con un tope de salida de 2500, en una ventana de 8192. Ollama hizo *context shift*:
- descartó 4093 tokens del principio (las instrucciones y la HU de Jira);
- devolvió 200 con una salida válida.

**El agente no se entera:** la HU se escribe sin parte de su prompt. Hay que garantizar que eso no pase nunca.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** integra.
- **UI:** `ses-ui`, con los defectos de T-35 en:
  - `core/approvals.py`, `core/state_machine.py` y `core/graph/execution.py`;
  - **`core/context/`**, `core/impact/`, **`adapters/llm/`** y `adapters/auth/`.
- **Modelos:** `ses-huecos`, en `api/`, `core/quality.py`, `core/handoff.py`, `migrations/0006`, `docker-compose.yml` y `Dockerfile`.
- **Ollama:** e2e real y medición de `limits.context_token_budget` (4500/4000). **Usa el LLM en esta máquina.**

## Qué hay que construir (presenta el plan antes de tocar código)
1. **Configuración** (autorizado por la principal en `core/config.py`, solo esto):
   - un campo `limits.context_window` (tokens de la ventana del modelo, p. ej. 8192), con un valor por defecto que no rompa los `models.yaml` actuales;
   - un margen de seguridad si hace falta.

   **No cambies `config/models.yaml`:** lo hará la sesión Ollama con los valores medidos. Documenta el campo.
2. **Guarda antes de llamar al LLM**, en los escritores que generan con mucho contexto:
   - `core/functional/writer.py` (generar, evolucionar, estructurar);
   - `core/qa/writer.py` (suite);
   - y valora `core/impact/` y `core/memory/` (impacto y memoria) si pueden pasarse.

   El cálculo y la respuesta:
   - estima los tokens del mensaje completo (instrucciones + contexto + HU previa + feedback) con `core.context.budget.estimate_tokens` u otro estimador conservador;
   - comprueba que **estimado + `max_output_tokens` de la tarea ≤ `context_window`**;
   - si no cabe, recorta primero las fuentes de menos prioridad (los últimos fragmentos del RAG y después las HU relacionadas), **nunca** la HU de origen ni las instrucciones;
   - si ni así cabe, un error claro en español (`AgentError`), nunca un truncado silencioso.

   Que el recorte quede en el log (sin contenido: solo recuentos) y, si el diseño lo permite, en las fuentes que se muestran.
3. **Estimación conservadora:** la estimación por caracteres puede quedarse corta con texto en español. Mide con algún caso de prueba frente a un tokenizador real si hay uno en las dependencias, y deja un margen.
4. **Imports de `escape_data`:** de paso, cambia los de `core/qa/` a `core.text` (los de `core/impact/` son de la sesión UI).

## Reglas
- **Puedes tocar:**
  - `core/functional/` y `core/qa/`;
  - `core/memory/` (si aplica);
  - `core/config.py` (solo el campo autorizado);
  - sus pruebas.

  **No toques `core/context/` ni `adapters/llm/`**, que están en la sesión UI. Si la guarda necesita algo de ahí, **para y avísame**.
- **Kanban:** cierra PA-114 con la fecha; tu fila en el registro; propuestas en PA-228…PA-249.
- **Pruebas:**
  - con fakes, incluido el caso límite (justo cabe, no cabe y se recorta, ni recortando cabe → error) y que la HU de origen y las instrucciones nunca se recortan;
  - nada contra el LLM real.
- **CPU:** Ollama está midiendo. Solo las pruebas de lo que tocas, y la suite completa una vez al final.
- **Antes del commit:** pytest, `ruff check` y `ruff format --check` en verde; `spec-checker` CONFORME y `security-reviewer` APTO. Pide a los subagentes que no maten procesos globales.
- **Sin fusionar:** `git push origin ses-jira` y avísame.

Empieza presentándome el plan (dónde va la guarda, cómo estima y qué recorta) antes de escribir código.
