# SESIÓN OLLAMA · Ronda 2: elegir un modelo local más rápido y repetir la prueba de punta a punta

Pega como mensaje en la sesión de Ollama (carpeta principal, rama `PreProduccion`) todo lo que hay debajo de la línea. Antes, trae lo último: `git pull origin PreProduccion`.

---

Tu diagnóstico fue muy útil: con `qwen3:4b-instruct` en CPU (~3,5 tokens/s) una HU tardó casi 19 min en una llamada y el reintento no cabía en 8192 de contexto.

**Ya está en `PreProduccion`:**
- **`limits.request_timeout_s`** (600 s) en `config/models.yaml`.
- **`limits.max_output_tokens`** por tarea: HU 2500, suite 3000, revisión 2000, impacto 800, memoria 1200, clasificar y JQL 200. Se envía como `max_tokens` a la API.
- **`JIRA_PUBLISH_MODE=live`** ya no está bloqueado, pero seguimos en `simulation`.

**Decisión del usuario:** **probar un modelo local más pequeño** para que la demo sea viable con CPU.

## Fase 1 · Elegir el modelo (mide y documenta; no cambies código)
1. **Candidatos** (ajusta según lo que haya en Ollama): `qwen3:1.7b`, `qwen2.5:3b-instruct`, `llama3.2:3b` y `phi4-mini`, más `qwen3:4b-instruct` como referencia con el tope nuevo. Descárgalos con `docker compose exec ollama ollama pull <modelo>`.
2. **Mismo caso para todos:** `StoryWriter.generate` con la necesidad de ejemplo del corpus y su contexto real del RAG. Hazlo con un script de un solo uso que **guarde la salida en bruto** en `docs/pruebas/salidas/` (sin secretos) y lo apunte:
   - tokens/s y tiempo total;
   - tokens de salida;
   - si el JSON es válido a la primera o necesita reintento;
   - si las citas son correctas o salta `CitationError`;
   - una valoración breve de la calidad en español: CA en Gherkin con sentido y sin repetirse.
3. **Ventana de contexto:** si el reintento sigue sin caber, prueba `OLLAMA_CONTEXT_LENGTH=16384` en `docker-compose.yml` y anota la RAM.
4. **Antes de cambiar nada, avísame con una tabla comparativa y tu recomendación.**

## Fase 2 · Aplicar el modelo elegido (cuando yo lo confirme)
- Cambia en `config/models.yaml` las cadenas de las tareas al modelo elegido. Puedes dejar `qwen3:4b-instruct` como respaldo en las tareas que lo necesiten.
- Ajusta `request_timeout_s`, `max_output_tokens` y, si hace falta, `OLLAMA_CONTEXT_LENGTH`, con los valores medidos.
- `uv run pytest -m "not integration"` debe seguir en verde: hay pruebas que leen `config/models.yaml`. Haz commit solo de `config/models.yaml` y `docker-compose.yml`.

## Fase 3 · Prueba de punta a punta (como en la ronda anterior)
Retoma los pasos 3 a 7 del encargo anterior:
- lecturas reales;
- pruebas `integration` con LLM;
- `eval/e2e_local.py` con los escenarios (a) a (f);
- la UI a mano;
- el informe `docs/pruebas/E2E-local-2026-10-02.md`.

Con el modelo nuevo debería llevar minutos por escenario, no horas.

## Reglas
- **Solo creas o cambias:**
  - `config/models.yaml` y `docker-compose.yml` (fase 2);
  - `eval/e2e_local.py`;
  - `docs/pruebas/` (informe y salidas en bruto).

  No toques `core/`, `adapters/`, `app/`, `web/`, `schemas/`, `prompts/` ni `docs/KANBAN.md`.
- No leas ni muestres el `.env`.
- `JIRA_PUBLISH_MODE=simulation` siempre.
- No mates procesos globales: si Ollama se cuelga, `docker compose restart ollama`.
- **Commits:**
  - fase 2: `Modelos: <modelo elegido> en local con topes medidos [RNF-09, RNF-10]`;
  - fase 3: `E2E: prueba de punta a punta con modelos locales [RNF-09, RNF-10]`;
  - sin push. Avísame.

Empieza por la fase 1 y dame la tabla comparativa antes de cambiar nada.
