# SESIÓN SEGURIDAD (antes MCP) · Ronda 6: login, validaciones y pruebas de la auditoría (PA-455, PA-458, PA-451, PA-452)

> Encargo de la **sesión Seguridad**: es la antigua sesión MCP, con otra carpeta. Sale de la auditoría completa del 2026-10-08 (`docs/auditorias/AUDITORIA-2026-10-08.md`). Hay otras tres sesiones trabajando a la vez (Jira, Modelos y UI): respeta tu zona.

La carpeta `ses-mcp` se borró en la limpieza. Crea una nueva y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git worktree add .claude/worktrees/ses-seguridad -b ses-auditoria-seguridad origin/PreProduccion
cd .claude/worktrees/ses-seguridad
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Estás en el proyecto "Agente de IA de Análisis Funcional y QA", en la rama **`ses-auditoria-seguridad`**, creada desde `PreProduccion`.

**Contexto:** la auditoría del 2026-10-08 encontró hallazgos de seguridad, principios y pruebas. Lee el informe (secciones «Seguridad», «Principios» y «Pruebas») y las filas **PA-455, PA-458, PA-451 y PA-452** de `docs/KANBAN.md`.

## Tareas, por prioridad (propón el plan antes de escribir código)
1. **PA-455 · El límite de login bloquea a todos detrás del proxy.**
   - **El fallo:** el login cuenta los fallos también por IP (`request.client.host`, `api/security.py:124-125`), y `success()` nunca limpia la clave de la IP (`api/app.py:262-270`, `api/sessions.py:137-156`). Con el proxy de Vite o Docker todos comparten IP: 5 fallos de cualquiera bloquean a todos, con una espera que se dobla hasta 40 min.
   - **La corrección:** no contar la IP cuando la petición viene de un proxy de confianza (configurable, con el valor por defecto actual de Vite), o leer la IP real de una cabecera que fija ese proxy. Además, limpiar `ip_key` al entrar bien.
   - **Las pruebas:** `tests/unit/test_api_app.py:519-524` da por bueno el bloqueo actual. Reescríbela con el comportamiento nuevo.
   - **Es lo más urgente:** en la demo podría dejar a todos sin acceso.
2. **PA-458 · Las pruebas no leen la configuración real de la demo.** `tests/unit/test_context_service.py:551`, `:590`, `test_context_window_guard.py:176` y `test_container.py:141` cargan `config/models.yaml` y comprueban valores de la demo. Pásalas a `tests/fixtures/models.yaml`, ampliado con límites por proveedor, y deja solo en `test_config.py` lo que comprueba el YAML real.
3. **PA-451 · La edición manual pasa las mismas validaciones que la salida del modelo.** En `_edit` (`core/graph/nodes.py:681-694`), aplica:
   - en suites: `suite_errors` de `core/qa/validation.py` (datos personales, CA/RN existentes y fuentes citables);
   - en HU: `citation_errors` y la detección de datos personales.

   Si falla, rechaza con `ReviewRejectedError` y un motivo claro en español. **Toca solo `_edit`**: la sesión Jira trabaja en publicar y generar del mismo archivo.
4. **PA-452 · Datos personales y secretos en las HU.** En `StoryWriter._run` (`core/functional/writer.py:150-157`), aplica `personal_data_kind` y el detector de secretos de la memoria a los textos de la `UserStory`, con reintento como en `TestWriter` y, si persiste, un error claro antes de la revisión humana.

## Reglas
- **Puedes tocar** `api/app.py` (solo login), `api/sessions.py`, `api/security.py`, `core/config.py` (solo para la lista de proxies de confianza; autorizado), `core/graph/nodes.py` (**solo `_edit`**), `core/functional/writer.py`, `core/qa/validation.py`, `core/personal_data.py`, `tests/` y `tests/fixtures/`.
- **No toques** `web/`, `schemas/`, `adapters/`, `core/quality.py` ni `api/service.py`. El contrato (`docs/api/openapi.yaml`) no cambia; si necesitas un código de error nuevo, avísame antes.
- **Datos sintéticos** en todas las pruebas: emails `@example.com` o `-test.es` e IBAN `ES00…`.
- **Pruebas con fakes**, una por criterio, positivas y negativas.
- **Sin pruebas reales con LLM.**
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra las PA hechas con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-468…PA-470**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-auditoria-seguridad` y avísame.

Empieza presentándome el plan antes de escribir código.
