# SESIÓN MCP · Ronda 4: Administración mínima y Revisar la calidad en la web (T-56)

> Encargo de la **sesión MCP**. Tu prueba de la web contra la API (`ses-web`) ya está fusionada. El responsable de `web/` está ausente: el usuario ha decidido terminar los pendientes con sesiones. En paralelo, la sesión UI arregla fallos de la web (rama `ses-web-fixes`).

Pon el worktree al día y abre Claude Code **en esa carpeta**. Pega como mensaje todo lo que hay debajo de la línea.

```bash
# desde la carpeta del repositorio (agente-af-qa)
git fetch origin
git -C .claude/worktrees/ses-mcp switch -C ses-web-admin origin/PreProduccion
cd .claude/worktrees/ses-mcp/web
npm ci
npm test
```

---

Sigues en el proyecto "Agente de IA de Análisis Funcional y QA", ahora en la rama **`ses-web-admin`**, creada desde `PreProduccion`. Tu ronda anterior (`ses-web`) ya está fusionada.

**Objetivo:** dos pantallas de la web en React que faltan para la entrega, una detrás de otra. Commit y push al terminar cada una.

Lee:
- `web/README.md`, `web/DESIGN-DECISIONS.md` y `web/HANDOFF.md`;
- `docs/specs/UI.md`;
- `docs/api/README.md`;
- el issue de seguimiento del responsable (resumido abajo).

## Bloque 1 · Administración mínima (decidida por el usuario para la entrega)
- **Solo el rol `admin`.** El administrador no ve las tarjetas de flujo (D-01); los demás roles no ven la zona y, si llegan a ella, reciben 403 con su tarjeta.
- **Contenido (solo lo que tiene API):**
  - **Probar conexiones:** `POST /admin/connections/test` → `ConnectionsTestOut`, con una fila por servicio (`service`, `ok`, `detail` y `duration_ms`). Lleva CSRF. Una prueba cada 10 s por persona; un 429 trae `retry_after`, así que enseña la cuenta atrás.
  - **Modelos por tarea, solo lectura:** `GET /admin/models` → `AdminModelsOut`: la cadena por tarea con proveedor, modelo y host, el override de la sesión si lo hay, y el modelo de embeddings.
  - **Modo de publicación, solo lectura:** `publish_mode` de `GET /settings`, con el aviso «Simulación: no se escribe nada en Jira».
  - **Usuarios, documentos e historial**, como «disponible pronto».
- **Diseño:** la parte de Ajustes de la página «Propuesta v2» del lienzo (la que cita UI.md para T-29), adaptada al estilo de la «Propuesta mixta». Si no tienes acceso al lienzo, usa los componentes y el estilo de las pantallas existentes, y apunta la diferencia como PA para UI.md.
- **Cliente:** añade al **final** de `web/src/api/client.ts` los métodos `adminConnectionsTest` y `adminModels`, más sus tipos en `types.ts` y su línea en `client.contract.ts`. Solo añadir.

## Bloque 2 · Revisar la calidad (Mixta 5)
- **La API ya existe:**
  - la revisión INVEST de una HU se arranca como dice `docs/api/README.md` (busca «Revisar la calidad» y `/quality-reviews`);
  - la lista, con `GET /quality-reviews`, que se junta con `GET /conversations` por `updated_at` y pinta «Informe listo» con `state=done`;
  - el informe, con `GET /quality-reviews/{id}`.
- **La pantalla**, según UI.md (Mixta 5): solo lectura, sin restricciones ni conversación. Informe INVEST, hallazgos y preguntas abiertas, con sus fuentes; el Markdown del informe solo para descargar.
- **Es una operación larga** (minutos con el modelo local): progreso, y nada se publica.

## Reglas
- **Coordinación con la sesión UI** (rama `ses-web-fixes`), que toca el 401 en `client.ts`, `Publishing`, Generando, Iterar, la Estrategia y el alto de la app:
  - tú añades al final de `client.ts` y en el carril o `AppShell` solo lo necesario para tus zonas;
  - no toques las pantallas que arregla ella.
- **Puedes tocar:** `web/` y sus pruebas. No toques `api/`, `core/` ni `app/`. Si la API no da algo que la pantalla necesite, **para y propónmelo** (PA).
- **Pruebas (Vitest con MSW, deterministas):**
  - Admin: solo `admin`; la prueba de conexiones con todo bien, con un servicio caído y con un 429 con cuenta atrás; los modelos; el modo de publicación.
  - Calidad: arrancar, el progreso, el informe, la lista con «Informe listo» y los errores.
  - En el MSW, los ejemplos del contrato.
- **Verificación:** `npm run lint`, `npx tsc -b`, `npm test` (dos veces) y `npm run api:check` en verde. Mira los tamaños de ventana (1024, 1280 y 1440) con Edge sin interfaz y un perfil nuevo.
- **Al final, una prueba corta contra la API real** en el equipo del usuario: Administración con `admin-demo` (probar conexiones no gasta tokens) y una revisión de calidad con `af-demo`. La revisión **sí** usa el modelo local, unos minutos: **pide permiso antes**.
  - El usuario inicia sesión; tú nunca ves las contraseñas.
  - No levantes Docker con `docker compose` desde el worktree: crea otro proyecto. Arranca los contenedores existentes con `docker start`.
  - SQLAlchemy: renombra sus `*.pyd` del `.venv` del worktree si hace falta (PA-338).
- **No mates procesos globales.** Pídeselo también a los subagentes.
- **Kanban:**
  - fila en el registro;
  - propuestas en **PA-400…PA-409** (tu rango PA-320…PA-339 está lleno).
- **Antes de cada commit:** `spec-checker` CONFORME y `security-reviewer` APTO.
- **Sin fusionar.** Haz `git push -u origin ses-web-admin` al terminar cada bloque y avísame.

Empieza presentándome el plan del bloque 1 antes de escribir código.
