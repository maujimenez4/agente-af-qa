# SESIÓN OLLAMA · Prueba real de punta a punta con modelos locales

Pega como mensaje en la sesión de Ollama (trabaja en la carpeta principal, rama `PreProduccion`) todo lo que hay debajo de la línea.

---

Ahora toca **la prueba real de punta a punta** del agente con los modelos locales de Ollama. Tu objetivo es **medir y documentar**, no arreglar: si algo falla, lo diagnosticas, lo anotas y me avisas; la sesión principal corrige el código.

## Contexto (ya está en `PreProduccion`)
- **`config/models.yaml` es ya la variante local:** `qwen3:4b-instruct` para todas las tareas y `bge-m3` para los embeddings, sin respaldo en la nube. La de Groq está en `config/models.groq.yaml`.
  - Si el `.env` tiene `MODELS_CONFIG_PATH=config/models.local.yaml`, pídeme que quite esa línea (yo edito el `.env`, tú no lo leas).
- **El grafo completo funciona con fakes:** origen, contexto, generación, revisión humana con huella, publicación (en `JIRA_PUBLISH_MODE=simulation` no escribe en Jira) y memoria.
- **Ya hechos:**
  - conversaciones persistentes (`core/factories.build_checkpointer`, `core/conversations`);
  - arranque guiado (`core/guided_start`);
  - revisión de calidad (`core/quality.QualityReviewer`);
  - modo QA con `TestWriter`;
  - generador de memoria (T-33, pendiente de fusionar).
- **Sospecha principal:** `adapters/llm/openai_compatible.py` corta cada llamada a los **60 s** (`_DEFAULT_TIMEOUT_S`). Con `qwen3:4b-instruct` en CPU, una HU completa en JSON puede tardar más. Confírmalo o descártalo lo primero.

## Pasos (en orden; para en el primero que falle y avísame)
1. **Entorno:**
   - `docker compose --profile local-llm up -d db ollama`;
   - comprueba que `docker compose exec ollama ollama list` muestra `qwen3:4b-instruct` y `bge-m3`;
   - ejecuta `uv run alembic upgrade head` (debe llegar a `0004_conversations`) y `uv run pytest -m "not integration"` (en verde).
2. **Una llamada mínima al LLM local:** `uv run pytest -m integration tests/integration/test_llm_live.py -s`. Anota el tiempo.
   - Después mide **una salida estructurada grande** (una `UserStory`) con un script de un solo uso, sin guardarlo en el repo, y anota cuánto tarda.
   - Si pasa de 60 s, **para y avísame**: haré configurable el tiempo de espera. No lo cambies tú.
3. **Lecturas reales** (sin LLM): `uv run pytest -m integration tests/integration/test_jira_live.py tests/integration/test_context_live.py`.
   - Si el sandbox de Jira no tiene el seed (T-15, importable por CSV desde `data/seed/jira/`), avísame.
4. **Pruebas reales con LLM**, una a una, anotando el tiempo de cada una:
   - `tests/integration/test_functional_live.py`;
   - `tests/integration/test_impact_live.py`;
   - `tests/integration/test_qa_live.py`.
5. **Punta a punta con el grafo real:** crea `eval/e2e_local.py`, con `__main__` y un argumento para elegir el escenario.
   - **Composición:** `build_config()`, `model_router(config)`, `build_app_container(config, router=router)`, `build_checkpointer(config)` y `build_graph(container, checkpointer=...)`, con `new_conversation_config(user)` y `initial_state(...)`. Usuarios: los de demo (`af-demo`, `qa-demo`); no hace falta login.
   - **Escenarios:**
     - (a) **necesidad nueva** en el proyecto de `JIRA_PROJECT_KEY`;
     - (b) **evolucionar** una HU del seed;
     - (c) **QA** sobre esa HU;
     - (d) **iterar** una vez con feedback y aprobar;
     - (e) **`QualityReviewer`** sobre una HU del seed;
     - (f) **`GuidedStart.propose`** con un texto que nombre una clave en minúsculas.
   - **Qué imprimir de cada escenario:**
     - nodos recorridos y **tiempo por nodo**;
     - versión, número de CA y RN, fuentes citadas, `plan` y tokens (`model_used`);
     - aprobación con la huella del payload;
     - en la auditoría, un `publish` con `simulated=true`;
     - el estado en `container.conversations.list_for(user)`.
   - **Prohibido:** nunca `live`. Ninguna escritura en Jira.
6. **La UI a mano:** `uv run streamlit run app/main.py`. Recorre login → nueva necesidad → generar → iterar con el usuario `af-demo`; las contraseñas de demo las tengo yo. Anota lo que no funcione.
7. **Informe:** escribe `docs/pruebas/E2E-local-2026-10-01.md` con:
   - entorno (CPU, RAM, versión de Ollama);
   - resultado y tiempo de cada paso;
   - calidad de las salidas: si las HU citan bien, si el JSON es válido a la primera o necesita reintentos, y si hay errores de cobertura o de citas;
   - los fallos con su traza resumida, sin secretos, y tu diagnóstico;
   - propuestas de mejora.

## Reglas
- **Trabajas en la carpeta principal, en `PreProduccion`, la misma que la sesión principal.** Solo creas `eval/e2e_local.py` y `docs/pruebas/E2E-local-2026-10-01.md`.
  - No toques `core/`, `adapters/`, `app/`, `schemas/`, `prompts/`, `config/`, `migrations/` ni `docs/KANBAN.md`.
  - Si una corrección es necesaria, descríbela en el informe y avísame.
- No leas ni muestres el `.env`. En el informe no van claves, tokens ni URLs con credenciales.
- `JIRA_PUBLISH_MODE=simulation` siempre: nada escribe en Jira.
- No mates procesos globales (nada de `taskkill` ni `pkill`). Si Ollama se queda colgado, reinícialo con `docker compose restart ollama`.
- **Al terminar:**
  - `uv run ruff check eval/e2e_local.py` y `uv run ruff format eval/e2e_local.py`;
  - commit **solo** de esos dos archivos, con el mensaje `E2E: prueba de punta a punta con modelos locales de Ollama [RNF-09, RNF-10]`;
  - sin push. Avísame con el resumen.

Empieza por los pasos 1 y 2 y dime los tiempos antes de seguir.
