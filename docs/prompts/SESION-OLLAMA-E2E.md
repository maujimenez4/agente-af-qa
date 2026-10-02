# SESIÓN OLLAMA · Ronda 3: validar los arreglos antes de elegir el modelo

Pega como mensaje en la sesión de Ollama (carpeta principal, rama `PreProduccion`) todo lo que hay debajo de la línea. Antes, trae lo último: `git pull origin PreProduccion`.

---

Tu comparativa de los cinco modelos fue muy útil. La principal ha organizado así lo que sigue:
- Tus dos causas comunes (IDs de RN copiados del corpus y `sources` vacío) y la opción de desactivar el razonamiento las implementa la **sesión Modelos (T-58)**, en paralelo contigo. No las hagas tú en el código.
- **Antes de elegir el modelo**, comprobamos con tu script que esos arreglos funcionan de verdad. Así T-58 sabe qué priorizar y la fase 2 se decide con datos.

## Fase 1b · Medir con los arreglos aplicados solo en tu script (sin tocar el repositorio)
Mismo caso que antes (necesidad de reservas, mismo RAG, tope de 2500). En el script, **no en `prompts/`**, añade al prompt de sistema de `generate_story` estas dos instrucciones:
1. «Numera las reglas `RN-01`, `RN-02`… y los criterios `CA-01`, `CA-02`…, aunque las fuentes usen otros identificadores; el identificador del documento (p. ej. `RN-RES-01`) va dentro de la descripción.»
2. «`sources` no puede ir vacío: cita al menos una fuente del contexto con su `ref` copiado literalmente.»

Mide:
- **`qwen3:1.7b` sin razonamiento**: prueba `extra_body={"reasoning_effort": "none"}` y, si no surte efecto, `extra_body={"think": False}`. Apunta cuál funciona contra el endpoint OpenAI de Ollama: T-58 lo necesita.
- **`phi4-mini`** con las dos instrucciones.
- Si sobra tiempo, **`qwen3:4b-instruct` sin razonamiento** como referencia de calidad.

Guarda las salidas en bruto en `docs/pruebas/salidas/` con el sufijo `-r3`. Después, dame la misma tabla que la vez anterior, con dos columnas más: «¿Pasa a la primera?» y «Reintentos evitados por los arreglos». Cierra con tu recomendación de modelo principal y de respaldo, y con los valores propuestos de `request_timeout_s` y `max_output_tokens`.

## Fase 2 · Aplicar el modelo (cuando yo lo confirme y T-58 esté fusionada)
- `config/models.yaml`:
  - las cadenas de cada tarea con el modelo elegido y su respaldo;
  - la opción para desactivar el razonamiento, en el formato que defina T-58;
  - `request_timeout_s` y `max_output_tokens` con los valores medidos.
- `docker-compose.yml`: `OLLAMA_CONTEXT_LENGTH` solo si hace falta (8192 bastó).
- `uv run pytest -m "not integration"` en verde: hay pruebas que leen `config/models.yaml`.
- Commit solo de `config/models.yaml`, `docker-compose.yml` y `docs/pruebas/salidas/`: `Modelos: <modelo> en local con topes medidos [RNF-09, RNF-10]`.

## Fase 3 · Prueba de punta a punta
Con el modelo nuevo:
1. lecturas reales;
2. pruebas `integration` con LLM;
3. `eval/e2e_local.py`, escenarios (a) a (f);
4. la API real a mano: `uv run python -m api` y los pasos de `docs/api/README.md` con `curl` o el Swagger de `/api/docs`; ya no la UI de Streamlit;
5. el informe `docs/pruebas/E2E-local-2026-10-02.md`.

Commit: `E2E: prueba de punta a punta con modelos locales [RNF-09, RNF-10]`.

## Reglas
- **Solo creas o cambias:**
  - el script de medición (fuera del repositorio o en `eval/`);
  - `eval/e2e_local.py`;
  - `docs/pruebas/`;
  - y en la fase 2, `config/models.yaml` y `docker-compose.yml`.

  No toques `core/`, `adapters/`, `api/`, `app/`, `web/`, `schemas/`, `prompts/` ni `docs/KANBAN.md`.
- No leas ni muestres el `.env`. `JIRA_PUBLISH_MODE=simulation` siempre.
- No mates procesos globales: si Ollama se cuelga, `docker compose restart ollama`.
- Commits sin push. Avísame al terminar cada fase.

Empieza por la fase 1b y dame la tabla antes de cambiar nada.
