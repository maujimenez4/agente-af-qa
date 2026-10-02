# T-54 · flujo unido HU → QA (ronda 4: la hace la sesión Modelos)

**Pégalo en la sesión Modelos**, que ya terminó T-58 (fusionada). La sesión UI no llegó a recibir este encargo en dos rondas: sigue con las pantallas de Streamlit (T-48 fusionada; T-28 a medias en `ses-ui`), así que T-54 cambia de sesión. Es lo más urgente: la API (T-55) tiene sus rutas de QA encadenada respondiendo 501 hasta que T-54 esté lista.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-flujo origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
uv run pytest -m "not integration"          # debe salir en verde antes de empezar
```

---

Trabajas en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-flujo`**, creada desde `PreProduccion`. Tu T-58 ya está fusionada. Tu tarea ahora es **T-54: flujo unido HU → QA**, una petición de dirección. Antes la tenía otra sesión, que no llegó a empezarla.

Hay **otras sesiones trabajando a la vez**:
- **Principal:** `PreProduccion`. Integra; dueña de la API (`api/`, T-55 ya hecha) y de los contratos. Cuando fusione T-54 conectará `/conversations/{id}/handoff` y `/qa/*` (PA-105) a tu diseño: deja en tu informe las funciones de servicio que debe llamar la API (listar entregas, pasar a QA y recoger).
- **UI:** `ses-ui`, terminando las pantallas de QA en Streamlit (T-28, plan B) en `app/`. No toques `app/`.
- **Jira:** `ses-jira`, con la prueba cruzada T-34 (solo pruebas nuevas).
- Tú ya conoces `core/qa/` y `core/functional/` por T-58: puedes tocar `core/qa/` si T-54 lo necesita (por ejemplo, para que `TestWriter` reciba la HU encadenada).
- **Ollama:** medición de modelos locales.
- **Responsable del área B:** frontend en React (`web/`, rama `area-b`).

## Qué pide T-54
Que cuando se apruebe o publique una HU **no haya que empezar de nuevo para hacer sus pruebas**: la salida del flujo funcional (la HU aprobada) es la entrada del flujo de QA.

Decisiones ya tomadas (`docs/KANBAN.md`, «Decisiones del día 6», 2026-10-02):
- **D-01 se mantiene:** el analista funcional no genera pruebas. Su conversación ofrece **«Pasar a QA»** y la HU aprobada aparece lista en la lista de QA, para **cualquier** usuario con el rol QA. Quien la recoge abre una conversación de QA con esa HU.
- **QA usa la HU aprobada tal cual:** sin releer Jira y **sin volver a estructurarla con el LLM**. Hoy `_write_suite` llama a `_baseline` (`StoryWriter.structure`); con la HU encadenada, esa llamada sobra.
- **Solo se encadena desde una versión aprobada o publicada que conste en el servidor**, nunca desde un contenido que llegue de la UI o de la API. La HU se carga por `artifact_id` y versión desde `core/impact/versions.StoryVersionStore` (`get(artifact_id, version)`; la tabla `artifacts` tiene su estado) o desde el registro de aprobaciones. Se comprueba que esa versión esté aprobada o publicada.
- **En simulación la HU no tiene clave de Jira:** los casos se pueden generar y revisar, pero **publicarlos exige que la HU esté publicada** (con clave). `publish` en modo QA tiene que rechazarlo con un mensaje claro si no hay clave.
- **Trazabilidad:** la suite referencia la HU de origen, el `artifact_id` y la versión, y la auditoría lo registra.

## Lo que tienes que diseñar (preséntalo en el plan antes de tocar nada)
1. **Entrega a QA («Pasar a QA»):** dónde se guarda (por ejemplo, una tabla `qa_handoffs` con migración `0005`), cómo la lista un usuario QA y cómo se recoge (quién, cuándo, una sola vez).
2. **Origen de QA encadenado:** cómo llega la HU aprobada al grafo. Por ejemplo, un campo en el estado inicial con la referencia (`artifact_id` y versión), y el grafo carga la HU del servidor. Cuida:
   - `validate_origin` cuando no hay clave de Jira en simulación;
   - `PublishTarget` y la huella;
   - el serializador del checkpointer, que admite una lista explícita de tipos;
   - las conversaciones de T-52 (título y estado).
3. **`_write_suite` con la HU encadenada:** sin llamar a `structure` (una llamada menos al LLM).
4. **`publish` en modo QA con HU sin clave:** error claro, sin escribir nada.

## Permisos de esta sesión
Puedes tocar `core/graph/`, `core/conversations.py`, un módulo nuevo `core/handoff.py` (o el nombre que propongas), `migrations/versions/0005_*.py` y sus pruebas. Lo autoriza la principal para esta tarea.

**No toques:**
- `schemas/`, `adapters/base.py`, `adapters/errors.py`, `core/config.py` ni `core/container.py`. Si el diseño necesita cambiar un contrato, **para** y escríbelo como propuesta: la principal lo hace.
- `app/`, `web/`, `adapters/` ni la SPEC. Al cerrar, deja en tu informe el texto para el anexo §11.

## Reglas
- Flujo `/tarea T-54`:
  1. leer;
  2. marcar 🔄;
  3. **plan y confirmación**;
  4. implementar;
  5. `test-writer`;
  6. `pytest` y `ruff` en verde;
  7. `spec-checker` CONFORME y `security-reviewer` APTO;
  8. marcar ✅.
- **Pruebas:**
  - con los fakes de `tests/fakes/`, incluido el flujo completo: HU aprobada → pasar a QA → un usuario QA la recoge → suite → aprobar → publicar;
  - publicar debe rechazarse si la HU no tiene clave;
  - las pruebas con PostgreSQL de la migración llevan la marca `integration`.
- **Kanban:**
  - cambia solo la fila de T-54 y añade tu fila al registro diario;
  - **propuestas en PA-266…PA-299** (las de tu rango de Modelos).
- **Seguridad:**
  - nada escribe en Jira salvo `publish` con aprobación;
  - la HU encadenada sale **siempre** del servidor;
  - ni secretos ni datos personales;
  - los logs no llevan contenido.
- **LLM:** solo fakes en las pruebas. El modelo local es lento: no lances pruebas reales sin preguntar.
- **Subagentes:** pídeles que no maten procesos globales.
- **Commits:**
  - formato `T-54: descripción [RF-14, RF-22]`;
  - **sin fusionar**: haz `git push -u origin ses-flujo` y avísame.

Empieza por `/tarea T-54` y preséntame el plan (sobre todo los puntos 1 y 2) antes de escribir código.
