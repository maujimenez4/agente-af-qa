# SESIÓN MODELOS · Ronda 11: trazas en Langfuse (T-40)

> Encargo de la **sesión Modelos**. Tu ronda 10 (`ses-memoria-ui`) ya está fusionada, y PA-288 la cerró la principal.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-langfuse origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run python -m pytest -m "not integration"   # en verde, sin xfail
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-langfuse`**, creada desde `PreProduccion`. Tu ronda 10 ya está fusionada.

**Objetivo: T-40 (RNF-24, DT-09).** Cada operación del agente deja una **traza en Langfuse** con:
- los pasos del grafo;
- las llamadas al modelo, con tokens, latencia y cambios de proveedor;
- la recuperación del RAG.

El usuario la enseñará en la demo y en la presentación. El panel de métricas por modelo y tarea son los paneles de Langfuse: no se construye uno propio.

Lee:
- la fila de T-40 en `docs/KANBAN.md`;
- DT-09 en `docs/decisiones/02_investigacion_tecnologica.md`;
- cómo se registra hoy el uso del LLM (`_record_spent`, T-32) y el router (`adapters/llm/`);
- dónde se invoca el grafo (`api/`, `app/`, `mcp_server/`).

## Decisiones del usuario
- **Langfuse Cloud**, plan gratuito; los datos son sintéticos. Nada de autoalojarlo ni de añadir servicios a `docker-compose.yml`.
- **Contenido con un interruptor:** `LANGFUSE_CAPTURE_CONTENT`, que por defecto vale `false`.
  - Con `true`, la traza lleva los prompts, el contexto del RAG y las respuestas.
  - Con `false`, solo métricas: modelo, tarea, nodo, tokens, latencia y errores.
  - En los dos casos, los secretos se enmascaran siempre, con el mismo enmascarado de `core/logging`.

## Tareas
1. **Configuración** (`core/config.py`, congelado: cambio **autorizado** solo para esto):
   - `LANGFUSE_PUBLIC_KEY` y `LANGFUSE_SECRET_KEY` como `SecretStr`;
   - `LANGFUSE_HOST`, por defecto la región de la UE de Langfuse Cloud;
   - `LANGFUSE_CAPTURE_CONTENT`.

   Sin claves, Langfuse queda **desactivado**: no hace nada, no llama a la red y no avisa más de una vez. Documéntalo en `.env.example`.
2. **Trazas:**
   - **Una traza por operación** (crear, iterar, aprobar, reintentar, QA, revisión de calidad, ejecución):
     - `session_id`: el id de la conversación;
     - `user_id`: el usuario;
     - etiquetas: modo, flujo y proyecto.
   - **Un paso por nodo del grafo.** Valora la integración de Langfuse con LangChain y LangGraph (el `CallbackHandler` en `config["callbacks"]`) frente a hacerlo a mano; propón en el plan.
   - **Llamadas al modelo** como *generations*:
     - proveedor, modelo, tarea, tokens de entrada y de salida, latencia y coste 0 (modelos gratuitos);
     - cada intento de la cadena de proveedores (429 → siguiente) visible como intento fallido.

     Valora el envoltorio `langfuse.openai` frente a instrumentar el router; propón en el plan.
   - **Versión del prompt** en los metadatos (`prompts/<tarea>.md`, cabecera `version:`).
   - **RAG:** un paso con la consulta, `k`, los ids de los fragmentos y sus puntuaciones. El texto de los fragmentos, solo con el interruptor activado.
3. **Robustez:**
   - Si Langfuse falla o tarda, la operación del agente **nunca** falla ni espera: tiempo límite, errores capturados y un log sin secretos.
   - `flush` al terminar cada operación y al cerrar el proceso: la API, Streamlit y el servidor MCP.
4. **Composición:**
   - `core/container.py` también está congelado. Si necesitas un campo nuevo en `Container` (por ejemplo, un `tracer`), está **autorizado** solo para esto.
   - El núcleo depende de un `Protocol` pequeño; la implementación con el SDK de Langfuse va en un adaptador.
   - Las pruebas usan un fake.
5. **Documentación:** apartado «Trazas en Langfuse» en el `README.md`:
   - crear la cuenta y el proyecto en la región de la UE;
   - copiar las claves al `.env`;
   - activar el interruptor;
   - qué se ve en cada traza.

   Añade dos o tres consultas o vistas útiles para la demo: una HU completa paso a paso, tokens por tarea y latencia por modelo.

## Reglas
- **Dependencia nueva `langfuse`:**
  - cuarentena de una semana: la versión elegida tiene que tener más de 7 días en PyPI, salvo la excepción de vulnerabilidades;
  - verifica en PyPI la versión, la licencia y las dependencias que arrastra;
  - `uv lock` y revisa el diff: si cambia otra dependencia, justifícalo;
  - anota todo en el registro, como hizo la sesión MCP.
- **No es un proveedor de LLM** (D-14): no añadas SDKs de modelos.
- **Puedes tocar:**
  - `core/config.py` y `core/container.py` (solo lo autorizado arriba);
  - un adaptador nuevo, por ejemplo `adapters/observability/`;
  - `adapters/llm/` (solo instrumentar);
  - un módulo nuevo en `core/` para el `Protocol`;
  - `core/graph/` (solo pasar los callbacks o el tracer, sin cambiar la lógica de los nodos ni `publish`/`_publish_approved`);
  - la composición en `core/factories.py`, `api/`, `app/` y `mcp_server/`;
  - `.env.example`, `README.md`, `pyproject.toml` y `uv.lock`;
  - y sus pruebas.

  No toques `schemas/`, `config/` ni `web/`.
- **Pruebas:**
  - **sin red**;
  - sin claves → no hace nada;
  - con el fake: traza, pasos, *generations* con tokens y el intento fallido de la cadena;
  - con el interruptor desactivado no viaja ningún texto; con el interruptor activado, los secretos van enmascarados;
  - Langfuse caído o lento no rompe ni retrasa la operación.

  Una prueba `integration` contra Langfuse Cloud que se salte sin claves. **No la ejecutes**: la lanza la principal.
- **Nunca leas el `.env`.** Las claves las pone el usuario.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales. En las pruebas, valores claramente ficticios como `pk-lf-ficticia`.
- **Kanban:**
  - T-40 → ✅ con la fecha;
  - tu fila en el registro;
  - propuestas en **PA-294…PA-299**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-langfuse` y avísame.

Empieza presentándome el plan antes de escribir código. Sobre todo:
- `CallbackHandler` frente a hacerlo a mano;
- `langfuse.openai` frente a instrumentar el router;
- cómo se aplica el interruptor y el enmascarado;
- qué versión del SDK eliges.
