# SESIÓN MODELOS · Ronda 5: preparar la demo (T-36, parte 1)

> Este archivo era el encargo de T-54 (ya fusionada). Ahora es el de la **sesión Modelos**.

Tu T-54 ya está fusionada en `PreProduccion`, y la API ya la usa (PA-105). Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-demo origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # en verde, con 50 xfailed (los de T-34)
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-demo`**, creada desde `PreProduccion`. Tus T-58 y T-54 ya están fusionadas.

**En esta ronda preparas la demo (T-36, parte 1).**

**Contexto:** con el modelo local en CPU (`qwen3:1.7b`, unos 6 tok/s) una HU tarda unos 5–6 min y el flujo HU → QA completo, 15–20 min. Por eso la demo se hará sobre todo con **conversaciones preparadas de antemano** (generadas de verdad con el modelo local y guardadas en el checkpointer), y en directo solo uno o dos pasos cortos. Si el usuario decide otra cosa (acelerar con la GPU o usar un modelo en la nube para la demo), la principal te lo dirá.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`; contratos, API y composición.
- **Ollama:** fase 3, la prueba real de punta a punta. **Usa el LLM en esta misma máquina.**
- **UI:** `ses-ui`, con T-35 (solo pruebas).
- **Jira:** `ses-jira`, corrigiendo los defectos de T-34 en `core/rag/`, `core/memory/`, `core/quality.py` y `core/guided_start.py`.
- **Responsable del área B:** frontend en React (`web/`).

## Tareas
1. **`README.md` de instalación desde cero**, probado paso a paso en tu worktree sin usar el `.env` real:
   - requisitos;
   - `uv sync`;
   - `docker compose up -d db ollama`;
   - `uv run alembic upgrade head` (hasta la 0005);
   - descargar los modelos de `config/models.yaml` (`qwen3:1.7b`, `phi4-mini`, `bge-m3`);
   - indexar el corpus;
   - crear los usuarios locales;
   - copiar `.env.example`;
   - arrancar la API (`uv run python -m api`) y Streamlit;
   - pruebas.

   Sin secretos ni valores reales: solo los placeholders de `.env.example`. Si el `README.md` actual ya tiene partes, complétalo en lugar de rehacerlo.
2. **Guion de la demo** (`docs/demo/GUION.md`), unos 15 minutos sobre los 8 pasos de la presentación. Incluye:
   - nueva necesidad;
   - fuentes;
   - generar e iterar;
   - recibo y aprobar en simulación;
   - **pasar a QA** (lo que pidió dirección, T-54);
   - suite y aprobar;
   - registrar la ejecución (T-47);
   - revisar la calidad;
   - memoria en `live` en el sandbox.

   Para cada paso: qué se muestra, qué se dice, qué conversación preparada se abre o qué se hace en directo, y el plan B si algo falla (por ejemplo, Ollama caído o Jira sin red). Datos 100 % sintéticos del corpus y del proyecto de pruebas.
3. **Script de preparación** (`eval/demo_prepare.py`). Ejecuta, sobre la composición real (API o grafo con `build_app_container`), las conversaciones del guion hasta el punto en que se retoman en directo, y deja un resumen (`docs/demo/preparadas.md`) con los ids, el estado, el modelo usado y el tiempo de cada una.
   - Siempre en `JIRA_PUBLISH_MODE=simulation`, salvo el paso de memoria, que el guion hace en el sandbox `AFQP` y solo con autorización expresa del usuario.
   - Idempotente: si ya existe una conversación preparada con el mismo nombre, no la repite.
   - **No lo ejecutes contra el LLM real sin preguntarme, y nunca mientras la sesión Ollama esté en su fase 3** (comparten la CPU y se falsearían sus tiempos). Pruébalo con los fakes: `--fake` o equivalente, con pruebas unitarias.
4. **Lista de comprobación previa a la demo** (`docs/demo/CHECKLIST.md`): servicios, modelos cargados (`keep_alive`), migraciones, corpus indexado, usuarios, conversaciones preparadas, modo `simulation` y red.

## Reglas
- **Solo creas o cambias:** `README.md`, `docs/demo/`, `eval/demo_prepare.py` y sus pruebas (`tests/unit/test_demo_prepare.py`).
  - Nada de `core/`, `api/`, `app/`, `adapters/`, `config/`, `prompts/`, `schemas/` ni `migrations/`.
  - Si el script necesita algo de esas capas que no existe, **para y escríbelo como propuesta**.
- **Kanban:**
  - Pon T-36 a 🔄, con la nota «parte 1: README, guion y preparación».
  - Añade tu fila al registro diario.
  - No toques el tablero.
  - **Propuestas en PA-270…PA-299.**
- **Seguridad:** no leas ni muestres el `.env`; nada de secretos en el README ni en el guion; datos sintéticos.
- **LLM:** solo fakes en las pruebas. Nada real sin preguntarme.
- **Antes del commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commit:** `T-36 (parte 1): README de instalación, guion de la demo y preparación de conversaciones`. **Sin fusionar:** `git push -u origin ses-demo` y avísame.

Empieza presentándome el plan (sobre todo el guion por pasos y cómo prepara las conversaciones el script) antes de escribir.
