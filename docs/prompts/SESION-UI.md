# SESIÓN MODELOS · Ronda 17: lo que encontró la auditoría en el LLM y la calidad (PA-457, PA-456)

> Encargo de la **sesión Modelos**. Tu ronda 16 (PA-442 y PA-443) ya está fusionada, y PA-445 la cerró la principal. Sale de la auditoría completa del 2026-10-08 (`docs/auditorias/AUDITORIA-2026-10-08.md`). Hay otras tres sesiones trabajando a la vez (Jira, Seguridad y UI): respeta tu zona.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-b switch -C ses-auditoria-llm origin/PreProduccion
cd .claude/worktrees/area-b
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-auditoria-llm`**, creada desde `PreProduccion`. Tu ronda 16 ya está fusionada. PA-445 (la revisión de calidad admite CA y RN nuevos en las propuestas) la hizo la principal en `core/quality.py`: léela antes de tocar ese archivo.

**Contexto:** lee el informe de la auditoría (sección «LLM y RAG») y las filas **PA-457, PA-440 y PA-456** de `docs/KANBAN.md`.

## Tareas, por prioridad (propón el plan antes de escribir código)
1. **PA-457 (incluye PA-440) · El reintento por formato no válido respeta la ventana.**
   - **El fallo:** el reintento de RNF-28 (`adapters/llm/openai_compatible.py:163-171`) reenvía el prompt con la respuesta fallida entera y `structured_retry`, sin pasar por la guarda de ventana. Con el modelo local (ventana de 10 240 y salida de 2500), una salida cortada y un prompt grande superan la ventana y Ollama recorta en silencio. Es más probable en QA.
   - **La corrección:** que el reintento estime su tamaño contra la ventana **del proveedor que lo va a recibir** y, si no cabe, falle con el error de «no cabe» (`PromptTooLargeError` o `StructuredOutputError`). Y, de PA-440, que no lleve la respuesta fallida entera: solo el error o la salida recortada.
2. **PA-456 · La revisión de calidad usa la estructura compartida.** `core/quality.py:125-127` estructura la HU con `writer.structure(origin_only)` sin la caché de PA-432 (`core/graph/nodes.py:424-428`). Que lea y guarde la misma caché: ahorra una llamada a Groq por revisión y alinea los IDs con el grafo. Reutiliza los ayudantes de PA-432; si están en `nodes.py`, muévelos a un sitio común de `core/functional/` sin cambiar el comportamiento del grafo.
3. **Si queda tiempo · dos ajustes bajos de la revisión de calidad:**
   - `QualityReport` en `CITED_SCHEMAS` (`adapters/llm/schema_hints.py:22`), para que la gramática de Ollama genere las citas si la revisión cae al modelo local; sin forzarlas cuando no hay fuentes;
   - `providers_of(self.c.llm)` en `QualityReviewer.limits` (`core/quality.py:98`), como hace el grafo.

## Reglas
- **Puedes tocar** `adapters/llm/`, `core/quality.py`, `core/functional/` (salvo `writer.py`, que lo toca la sesión Seguridad; si necesitas cambiarlo, avísame), `core/context/`, `prompts/`, lo mínimo de `core/graph/nodes.py` para mover los ayudantes de la caché (sin tocar publicar, generar ni `_edit`), y sus pruebas.
- **No toques** `web/`, `api/`, `schemas/`, `adapters/testmgmt/` ni `adapters/jira/`. El contrato no cambia.
- **Pruebas con fakes:**
  - un reintento que no cabe falla con «no cabe» sin llamar al modelo;
  - un reintento que cabe sigue funcionando;
  - el reintento ya no lleva la respuesta entera;
  - la revisión de calidad reutiliza la estructura compartida sin llamar al modelo;
  - `QualityReport` lleva `sources` como obligatorio en el esquema.
- **Prueba real:** con permiso del usuario, una revisión de calidad de AFQP-27 con Groq. Debe hacer una sola llamada al modelo si la estructura ya está guardada.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-457, PA-440 y PA-456 con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-465…PA-467**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-auditoria-llm` y avísame.

Empieza presentándome el plan antes de escribir código.
