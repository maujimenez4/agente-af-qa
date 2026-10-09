# SESIÓN JIRA · Ronda 15: el nombre FAQ en el backend (PA-479, PA-480, PA-481)

> Encargo de la **sesión Jira**. Tu ronda 14 (PA-450, PA-453, PA-454) ya está fusionada. La web ya llama al asistente «FAQ» (PA-478, `docs/diseno/faq/README.md`); esta ronda lleva el nombre a lo que no es la web.

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/area-a switch -C ses-faq-backend origin/PreProduccion
cd .claude/worktrees/area-a
uv sync
# Windows bloquea las extensiones compiladas de SQLAlchemy (PA-338): usa su versión en Python puro
find .venv/Lib/site-packages/sqlalchemy -name "*.pyd" -exec sh -c 'mv "$1" "$1.bloqueado"' _ {} \;
uv run python -m pytest -m "not integration"   # en verde
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-faq-backend`**, creada desde `PreProduccion`. Tu ronda 14 ya está fusionada.

**Contexto:** el asistente se llama **FAQ** (Qaracter es la marca). La web ya lo usa (PA-478) con el nombre en una sola constante (`web/src/text/assistant.ts`). Lee `docs/diseno/faq/README.md` y las filas **PA-479, PA-480 y PA-481** de `docs/KANBAN.md`.

## Tareas (propón el plan antes de escribir código)
1. **Una constante en el backend** para el nombre del asistente (por ejemplo `ASSISTANT_NAME = "FAQ"` en un módulo pequeño de `core/`), usada en todo lo de abajo. Si dirección cambia el nombre, una línea.
2. **PA-479 · Jira.** La cabecera del comentario que se publica al evolucionar una HU dice «**Cambios propuestos por el agente y aprobados**» (`_diff_comment_md`, `core/graph/nodes.py`). Pasa a «Cambios propuestos por FAQ y aprobados».
   - Revisa los demás textos que el agente escribe en Jira (adjuntos de estrategia y matriz, descripción de HU nuevas, comentarios de ejecución) y cambia los que digan «el agente».
   - **No añadas nombres de personas** al texto de Jira: la autoría ya queda en la auditoría. Si crees que conviene «aprobado por <usuario>», proponlo aparte.
   - **Sin tocar la lógica de `publish`:** solo textos.
3. **PA-480 · Servidor MCP.** Los textos que ve el asistente (instrucciones de `mcp_server/server.py` y descripciones de herramientas) pasan a hablar de «FAQ».
   - **No cambies `SERVER_NAME = "agente-af-qa"`:** es la clave de la configuración `.mcp.json` de quien ya lo usa y del README.
   - Si el SDK de MCP permite un nombre visible aparte de la clave, úsalo con «FAQ · Qaracter»; si no, solo los textos.
4. **PA-481 · Streamlit.** `page_title="Agente AF y QA"` (`app/main.py`) pasa a «FAQ · Qaracter», y los textos visibles de `app/` que digan «el agente», si los hay, a «FAQ».
5. **Documentación:**
   - el README, donde habla del asistente (sin cambiar los comandos ni la clave del MCP);
   - la fila de la SPEC-00 si nombra estos textos.

## Reglas
- **Puedes tocar** `core/graph/nodes.py` (solo textos de lo que se publica), `adapters/testmgmt/` y `adapters/jira/` (solo textos), un módulo nuevo de `core/` para la constante, `mcp_server/`, `app/`, `prompts/` (solo si un prompt pide escribir «el agente» en lo publicado), el README y sus pruebas.
- **No toques** `web/`, `api/`, el contrato ni `schemas/`.
- **Principio 1:** nada nuevo escribe en Jira. Solo cambia el texto de lo que ya se escribe con aprobación.
- **Pruebas con fakes:**
  - el comentario del diff lleva «por FAQ»;
  - los adjuntos y textos publicados sin «el agente»;
  - las instrucciones del MCP nombran a FAQ;
  - el título de Streamlit;
  - cambiar la constante cambia los textos.

  Adapta las pruebas existentes que comprueban los textos antiguos, sin borrar ninguna.
- **Sin pruebas reales** contra Jira ni con el LLM.
- **Windows:** si `pytest` está bloqueado, usa `uv run python -m pytest`.
- **gitleaks:** sin `secret`, `password` ni `token` como nombre de variables con literales.
- **Kanban:**
  - cierra PA-479, PA-480 y PA-481 con la fecha;
  - tu fila en el registro;
  - propuestas nuevas en **PA-482…PA-484**.
- **Antes del commit:**
  - pytest, `ruff check` y `ruff format --check` en verde;
  - el contrato sin cambios (`uv run python -m api.export_openapi`);
  - `spec-checker` CONFORME y `security-reviewer` APTO.
  - Pide a los subagentes que no maten procesos globales.
- **Sin fusionar.** Haz `git push -u origin ses-faq-backend` y avísame.

Empieza presentándome el plan antes de escribir código.
