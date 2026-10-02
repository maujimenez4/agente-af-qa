# SESIÓN MEMORIA → T-32 · Ronda 2: contador de tokens y endurecimiento del LLM (área A · `adapters/llm/`)

Tu rama `ses-memoria` ya está fusionada (T-33, backend). En esta ronda la sesión cambia de tarea. Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-memoria origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-memoria`**, recién puesta al día desde `PreProduccion`. Tu T-33 (backend) ya está fusionada: la app usa `LLMMemoryGenerator`. **En esta ronda haces T-32.**

Hay **otras sesiones de Claude Code trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra y es dueña de los contratos y del grafo.
- **UI:** `ses-ui`, en `app/`.
- **Jira:** `ses-jira`, en `adapters/jira/` y `adapters/testmgmt/`.
- **Ollama:** la prueba real de punta a punta con los modelos locales.

**Solo tocas lo de esta sesión.**

Lee antes:
- `CLAUDE.md`;
- `docs/specs/SPEC-00-fundacional.md`: §4 (`LLMProvider`, `LLMResult`/`StructuredResult`), §6 (tabla `llm_usage`), §7 (configuración y selector RF-42), §8 (LLM gratuitos, reintentos y logging) y el anexo §11;
- en `docs/decisiones/01_declaraciones_proyecto.md`: RF-43, RF-44, RNF-02, RNF-12, RNF-27 y RNF-28;
- en `docs/KANBAN.md`: PA-15, PA-16 y PA-67.

## Estado de partida
- **`adapters/llm/`:**
  - `OpenAICompatibleProvider` (JSON Schema o modo JSON, validación pydantic y un reintento);
  - `FallbackLLMProvider` (cadena por tarea y aviso diario de tokens);
  - `ModelRouter` (selector RF-42);
  - `usage.py`, con `UsageRecord`, `InMemoryUsageRecorder` y `SqlUsageRecorder` sobre `llm_usage`.
- **El registro de uso no está conectado en la app:** `build_app_container` llama a `build_llm_provider(config, router=router)` **sin `recorder`**, así que no se guarda nada en `llm_usage`.
- **Tiempo de espera:** desde hoy es configurable. Está en `limits.request_timeout_s` de `config/models.yaml` (600 s en local) y la principal ya lo pasa al cliente del SDK.
- **Modelos:** solo locales de Ollama (`qwen3:4b-instruct`), lentos en CPU; el coste estimado es 0, pero los tokens y la latencia sí importan.

## Tareas (con la skill `/tarea T-32`) [RF-43, RNF-12, RNF-02]
1. **Contador de tokens y coste (RF-43), parte de backend:**
   - Conecta el registro de uso en la app. **Autorizado por la principal solo esto en `core/factories.py`:**
     - una función `build_usage_recorder(config)` (`SqlUsageRecorder` sobre la BD del `.env`);
     - pasarla a `build_llm_provider` dentro de `build_app_container`.

     El resto de `core/factories.py` no lo toques.
   - Consultas de lectura para la UI en un módulo nuevo, **`core/usage.py`**: tokens y coste estimado por día, por tarea, por modelo y por proveedor, y las últimas llamadas.
   - Si el registro puede llevar el `artifact_id` o el `thread_id` sin tocar los contratos, propón cómo; **no cambies `adapters/base.py`**.
   - La parte visible es de la sesión UI: deja en tu informe la API exacta que debe usar.
2. **Reintentos y cadena de respaldo (RNF-12, RNF-27, RNF-28):**
   - revisa que un 429 respete `retry-after` y el umbral, y que se pase al siguiente de la cadena;
   - que un tiempo de espera agotado se trate como fallo del proveedor y pase al siguiente, sin repetir en bucle;
   - **PA-16:** desactivar JSON Schema solo ante un 400 por `response_format`, no ante cualquier 400;
   - **PA-67:** exponer el motivo del cambio de proveedor (límite, tiempo de espera, error) para el aviso de la UI.
3. **Mensajes de error:** todos los errores del LLM llegan a la UI en español y sin datos internos (cuerpos de respuesta, URLs con credenciales, `input_value` de pydantic).
   - **PA-15:** proponer `StructuredOutputError` en `adapters/errors.py`. Ese archivo está congelado: escribe la propuesta y la principal lo mueve.
4. **Revisión de logs (RNF-02):** recorre todo el repositorio buscando registros que puedan llevar prompts, contenido de HU o de documentos, cabeceras `Authorization` o secretos. Comprueba que el enmascarado de `core/logging.py` cubre los secretos de la configuración.
   - Corrige lo que esté en tus archivos.
   - Lo de otras áreas, anótalo como propuesta con el archivo y la línea.

## Reglas comunes a todas las sesiones
- **Solo tus archivos:**
  - `adapters/llm/`, `core/usage.py` (nuevo) y `tests/unit/test_llm*.py`, `tests/unit/test_usage*.py`;
  - en `core/factories.py`, **solo** lo autorizado arriba;
  - en `tests/fakes/`, solo añadir.

  No toques `core/graph/`, `core/config.py`, `adapters/base.py`, `adapters/errors.py`, `app/`, `schemas/`, `config/` ni la SPEC.
- **Kanban:**
  - Cambia solo el estado de tu fila (T-32) y de las PA que cierres (PA-16, PA-67).
  - Añade tu fila al registro diario.
  - No toques el tablero resumen.
  - **Propuestas en PA-253…PA-299.**
- **Seguridad:**
  - No leas ni muestres el `.env`.
  - Los logs no llevan prompts, contenido ni secretos.
  - Las claves, solo vía `SecretStr`.
- **LLM:**
  - Las pruebas usan fakes y `httpx.MockTransport` o un cliente simulado.
  - No lances pruebas reales con el LLM sin preguntarme: el modelo local en CPU tarda minutos por llamada.
- **Antes de cada commit:**
  - `uv run pytest -m "not integration"`, `uv run ruff check .` y `uv run ruff format --check .` en verde;
  - subagentes `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Commits:**
  - Formato `T-32: descripción [RF-43, RNF-12, RNF-02]`.
  - **Sin fusionar.** Haz `git push origin ses-memoria` y avísame.

Empieza por `/tarea T-32` y preséntame el plan antes de escribir código.
