# API del agente para el frontend (T-55)

`openapi.yaml` es el **contrato** entre el frontend en React (`web/`, T-56) y el backend. Se genera desde el código (`api/`) y no se edita a mano:

```bash
uv run python -m api.export_openapi
```

Si necesitas otro dato o un endpoint distinto, propónlo (`PA-3XX`) a la sesión principal: no lo inventes en el frontend.

## API simulada (sin Python ni Docker)
Con Node.js:

```bash
npx @stoplight/prism-cli mock docs/api/openapi.yaml -p 4010
# http://127.0.0.1:4010/api/v1/...
```

**Comportamiento de Prism:**
- Valida cada petición contra el contrato y responde con el **ejemplo** de cada respuesta.
- **Respuestas de error:** se piden con la cabecera `Prefer`. Ejemplos: `Prefer: code=404` y `Prefer: code=429`.
- **Sesión:** Prism exige la cookie `afqa_session` en todas las rutas salvo `POST /auth/login`, y además `X-CSRF-Token` en las que modifican algo (POST, PUT, DELETE). En desarrollo vale cualquier valor; por ejemplo, el `csrf_token` del ejemplo de `/auth/login`.
- **Limitaciones:** no guarda estado ni emite eventos en vivo, así que lo que no simula se cubre así:
  - **SSE** (`GET /conversations/{id}/events`): simúlalo en el frontend con MSW o con temporizadores, o usa el sondeo de `GET /conversations/{id}`.
  - **Estado entre pasos** (generando → en revisión → simulado): los ejemplos son fijos. Para recorrer el flujo, MSW con un pequeño estado en memoria, construido con los ejemplos del contrato.

## API real (con Python, Docker y el `.env`)
```bash
docker compose up -d db && uv run alembic upgrade head
uv run python -m api        # 127.0.0.1:8000, un solo proceso y sin access log
```
- Se compone en la **primera petición** (contenedor, checkpointer de PostgreSQL, Jira y Ollama). Si falla (BD caída, `.env` inválido), cada petición responde 503 con el motivo y se reintenta en la siguiente.
- **Un solo proceso** (sin `--workers`): las sesiones viven en memoria. Si la API se reinicia, hay que volver a iniciar sesión; las conversaciones siguen en PostgreSQL.
- Sin access log de uvicorn (`python -m api` lo desactiva; con `uvicorn` a mano, añade `--no-access-log`): registra la query string (p. ej. lo buscado). La API registra su propia línea por petición (método, ruta de la plantilla, estado, duración y persona).
- `/api/docs` (Swagger) y `/api/openapi.json` solo con `APP_ENV=development`.
- **Mismo origen:** el frontend llama a `/api/...` a través del proxy de Vite (`server.proxy: {"/api": "http://127.0.0.1:8000"}`, **sin** `changeOrigin: true`: la API compara `Origin` con `Host`), así que no hace falta CORS. Si se sirve desde otro origen, ponlo en `API_ALLOWED_ORIGINS`.
- Una petición sin `Origin` ni `Referer` (cliente que no es navegador) se acepta: el token CSRF sigue siendo obligatorio. Detrás de un proxy, el límite de login por IP ve la IP del proxy (no se confía en `X-Forwarded-For`).
- La cookie es `Secure`: el navegador la acepta en `http://localhost`. Para otro host sin HTTPS en desarrollo, `API_INSECURE_DEV_COOKIE=true` (solo con `APP_ENV=development`).
- Ajustes nuevos en `.env.example`, sección «API para el frontend».

## Reglas para el frontend
- **Sesión:**
  - `POST /auth/login` deja una **cookie HttpOnly** (`afqa_session`, SameSite=Strict) que el frontend no ve, y devuelve `csrf_token`.
  - Toda petición que modifica algo (POST, PUT, DELETE) lleva la cabecera **`X-CSRF-Token`** con ese valor.
  - Al recargar la página, `GET /auth/me` devuelve el token de la sesión.
  - Nada de tokens en `localStorage`.
- **Operaciones largas** (crear conversación, iterar, aprobar, revisar la calidad):
  - responden **202** de inmediato;
  - el avance llega por **SSE** (`/events`) o consultando el estado;
  - con el modelo local en CPU pueden tardar minutos: enseña el progreso por pasos (`progress`);
  - mientras una operación está en curso, otra sobre la misma conversación da 409 `not_in_review`;
  - `data` de cada evento `progress` es un `ProgressStep` completo (`node`, `label` y `state`): `label` se muestra tal cual;
  - el SSE se cierra tras `result` de una conversación terminada (simulada, publicada o descartada): ciérralo también en el cliente para que `EventSource` no reconecte. Máximo 3 flujos abiertos por persona (429 `too_many_streams`).
- **Aprobar:**
  - se envía **exactamente** la `fingerprint` del último `review`;
  - una respuesta no válida (huella antigua, edición inválida) **no da error HTTP**: la revisión sigue y trae el motivo en `review.error`;
  - un **409** se distingue por `error.code`:
    - `approval_rejected`: el registro de aprobaciones la rechazó; hay que ofrecer «empezar de nuevo»;
    - `not_in_review`: la conversación no está en revisión; hay que actualizar el estado.
- **Panel «Antes de generar» (PA-102):** `POST /start/sources` devuelve `{sources, budget}`; `budget.used`/`budget.limit` son tokens estimados frente a los disponibles, y `dropped_sources` las fuentes que no caben y no se enviarán al LLM.
- **Ficha de una HU (PA-104):** `GET /issues/{key}` añade `test_cases` (subtareas CP en Jira; `null` si no se pudo consultar) y `published_by_agent` (`null` si no se sabe).
- **QA encadenada (T-54):**
  - `POST /conversations/{id}/handoff` (analista): pasa a QA la HU aprobada, simulada o publicada; repetirlo es idempotente;
  - `GET /qa/handoffs` (rol QA): HU pendientes, de cualquier analista, de los proyectos visibles;
  - `POST /qa/handoffs/{id}/take` (rol QA, id de 32 hex): la recoge una sola persona (si no, 409 `handoff_unavailable`) y responde 202 con la conversación de QA generando;
  - sin clave de Jira (HU aprobada en simulación), los casos se generan y revisan, pero aprobarlos deja `review.error`: hay que publicar antes la HU y volver a pasarla a QA.
- **Registrar la ejecución (QA 6, T-47):**
  - `POST /executions` con la HU (su suite tiene que estar publicada en Jira) devuelve los casos y un registro vacío en revisión;
  - `PUT /executions/{id}/results` guarda el borrador (no escribe en Jira) y devuelve una `fingerprint` nueva;
  - un resultado no válido no da error HTTP: llega en `review_error`;
  - `POST /executions/{id}/approve` con la `fingerprint` exacta escribe en Jira, y devuelve `recorded` o `partial` (con `outcome.failed`); en modo simulación (por defecto) no escribe nada y devuelve `simulated`;
  - el resultado lo elige la persona; un `fallo` exige evidencia;
  - solo el rol QA (`publish_tests`).
- **Texto de Jira, del RAG y del LLM:** siempre como texto, nunca como HTML. `report_markdown` es solo para descargarlo.
- **Errores:** siempre `{"error": {"code", "message", "retry_after"}}`, con `message` en español y listo para mostrar. `code` es una lista cerrada (`ErrorCode` en el contrato, PA-306). Los fallos de la generación llegan en `ConversationOut.error` o en `QualityReviewOut.error`, con su propio código:
  - `citation_failed`, `coverage_failed`, `quality_failed` e `invalid_model_output`: el modelo no dio una salida válida;
  - `provider_timeout`: el modelo no respondió a tiempo;
  - `rate_limited`, con `retry_after`: los proveedores están en su límite;
  - `service_unavailable`: todos los proveedores fallaron;
  - `publish_failed`: Jira rechazó la publicación. Una publicación **parcial** no es un error: llega en `result.errors` (ver «Estados de una conversación»).
- **Consumo de hoy** (anillo del carril): `GET /settings/usage` devuelve `tokens_today` y `warning_threshold`. Es el consumo de **toda la instalación** (`scope: "global"`): el registro de uso no guarda la persona. Incluye el `422` de validación, que nunca devuelve lo enviado.
- **Estados de una conversación:**
  - **en la lista** (`ConversationSummary.status`): `started`, `in_review`, `approved`, `simulated`, `published` y `discarded`;
  - **en el detalle** (`ConversationOut.state`): `generating` en lugar de `started` (el grafo está trabajando), los demás iguales, y además `error` (falló la última operación);
  - una publicación parcial (PA-324): una **suite** con casos que no se pudieron crear queda en `approved`, con `result.errors` y `result.failed_ids`; una **HU** ya escrita con algún vínculo fallido queda en `published`, con `result.errors`. Trata los dos estados.
- **Flujo y origen:**
  - `flow=need` admite un origen `need` o `epic`;
  - `evolve` y `tests` admiten solo `story`;
  - `tests` no admite texto libre.

  Las opciones de `POST /start/propose` traen el `origin` listo.

## Novedades para el frontend
Todo lo nuevo **solo añade** rutas, campos opcionales o valores de `ErrorCode`: lo existente no cambia. Regenera los tipos desde `openapi.yaml`.

| Desde | Qué | Cómo se usa |
|---|---|---|
| Ronda 12 (PA-327) | Etiquetas de los pasos por modo en `ProgressStep.label` | En QA, «Recuperar la HU de origen», «Recuperar el contexto (Jira, documentos y memoria)», «Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y estrategia» y «Publicar (o simular la publicación de) los casos de prueba en Jira». **En QA la lista de pasos tiene 4, no 5:** `memorize` no aparece, porque en QA no se guarda memoria (D-07). No cuentes con un número fijo de pasos: pinta los que lleguen en `progress` (también en el SSE y en `/take`). En la HU no cambia nada |
| Ronda 12 (PA-326) | `ReviewPayload.coverage_md` y `ReviewPayload.uncovered` (`{criteria, rules}`), opcionales | Pestaña Cobertura de Iterar la suite. `coverage_md`: la matriz CA/RN × CP, la misma que se adjunta como `matriz-<CLAVE>.md`; píntala como texto o descárgala. `uncovered`: los CA y RN de la HU de origen sin ningún caso. **`null` = «no se sabe»** (no se pudo leer la HU de origen sin llamar al LLM): no digas «todo cubierto»; **listas vacías = «todo cubierto»**. Lo normal es `criteria: []` (la suite no se genera sin un caso por CA) y, a veces, alguna RN. En una revisión de HU, los dos son `null`. Sin coste de LLM |
| Ronda 12 (PA-326) | Ejemplo `components.examples.ConversationQaInReview` | Una `ConversationOut` de QA en revisión (`flow: tests`, `mode: qa`, `state: in_review`) con una suite sintética de DEMO-3 (4 casos sobre CA-01/CA-02 y RN-01/RN-02), `review.plan` con `publish_suite`, la huella, `coverage_md`, `uncovered` y los 4 pasos de QA. Está en `components.examples` (no en el `example` de una ruta, que no cambia): para el MSW, `generate.mjs` tiene que copiarlo a `examples.json` (PA-118) |
| 2026-10-05 (PA-318) | `SettingsOut.jira_browse_url` (`string` o `null`) | «Abrir DEMO-3 en Jira» y los enlaces a las claves publicadas: `{jira_browse_url}{clave}`. Siempre `https://<sitio>/browse/`; `null` sin sitio configurado. Pásalo igualmente por `safeHref` |
| 2026-10-05 (PA-319) | Operación `{"op": "comment", "key": …}` en `review.plan`, justo después de `update_story` | El comentario con la tabla de cambios ya no hay que deducirlo: es su propia casilla del recibo. No cambia la huella |
| 2026-10-05 (PA-324) | Aclaración del estado tras una publicación parcial | Suite con casos sin crear → `approved`; HU escrita con algún vínculo fallido → `published`. En los dos, `result.errors` |
| Ronda 10 (T-33) | `GET /memories?project=&q=&limit=` → `MemorySummary[]` y `GET /memories/{key}` → `MemoryOut` | Pestaña «Memoria»: las memorias de las HU publicadas de los proyectos que ve la conexión, más recientes primero; `q` busca en la clave y en el texto. Cada una trae `title` (el objetivo, como mucho 120 caracteres), `version`, `updated_at` e `indexed` (si está en el RAG). En el detalle, `memory` se pinta campo a campo **como texto** (lo escribió el LLM) y `markdown` es solo para descargarlo. Lista vacía: «Aún no hay memorias. Se generan al publicar una HU en Jira (modo real).» El mismo 404 `not_found` si no existe, si es de un proyecto que no se ve o si la clave no es válida. Los tres roles pueden leer; no llama al LLM ni escribe nada. Datos de ejemplo en local: `uv run python -m core.memory.seed_demo` |
| Ronda 10 (T-29 mínima) | `POST /admin/connections/test` → `ConnectionsTestOut` y `GET /admin/models` → `AdminModelsOut` | Página **Administración**, solo para `admin` (los demás roles: 403 `forbidden`). «Probar conexiones» devuelve una fila por servicio (`service`, `ok`, `detail`, `duration_ms`): Jira, PostgreSQL (con la revisión de Alembic), `Modelos · <proveedor>` y Embeddings; pinta ✅/❌, el detalle y el tiempo. Tarda como mucho unos 5 s; lleva CSRF y admite **una prueba cada 10 s por persona** (429 `rate_limited` con `retry_after`). Un proveedor sin clave sale como «Sin configurar.». `GET /admin/models`: cadena de modelos por tarea y modelo de embeddings, de cada proveedor **solo el host**, y `override` si la sesión eligió otro modelo. No escribe en Jira ni genera texto |
| Ronda 9 (PA-314) | `POST /conversations/{id}/cancel` → 202 `ConversationOut` | Botón «Detener» en Generando e Iterar. Mientras termina el paso en curso, `cancel_requested=true` («Deteniendo…»); **una llamada al LLM ya en curso no se corta**. Al acabar: `state=error` con `error.code=cancelled` (ofrece «Reintentar» con `/retry`) o, si el siguiente paso era la revisión, `state=in_review` con la propuesta ya generada y `cancel_requested=false`. Aprobar o publicar no se cancelan: 409 `not_cancellable` (también si no está generando). Nunca escribe en Jira |
| Ronda 9 (PA-316) | `ConversationOut.jira_baseline` (`UserStory` o `null`) | Versión «Jira» del selector de versiones en Iterar: la HU tal como está en Jira, estructurada. Solo al evolucionar una HU existente; `null` en una HU nueva, en QA, antes de la primera versión y tras publicar o descartar. No cuesta ninguna llamada al LLM |
| Ronda 9 (PA-285) | Texto del arranque guiado | La opción de una épica dice «HU nueva en la épica DEMO-1», como el título de la conversación |
| Ronda 8 (PA-276) | `POST /conversations/{id}/retry` → 202 `ConversationOut` | Botón «Reintentar» cuando `state=error` (también tras `cancelled`): repite el paso que falló. 409 `not_in_error` si no está en error o si lo que falló es aprobar o publicar (nunca se escribe dos veces en Jira); en QA encadenada, 409 `handoff_unavailable` si la HU volvió a la lista |
| Ronda 8 (PA-317) | Título «HU nueva en la épica DEMO-1» | Las conversaciones ya guardadas conservan el título anterior |
| Ronda 6 (PA-103, PA-272) | `GET /quality-reviews` → `QualityReviewSummary[]` | Revisiones de calidad de la persona, guardadas: júntalas con `GET /conversations` por `updated_at` y pinta «Informe listo» con `state=done`. El informe, con `GET /quality-reviews/{id}` |

## Estado
| Parte | Contenido | Estado |
|---|---|---|
| 1 | Contrato completo, ejemplos y API simulada | Hecho (las rutas reales responden 501) |
| 2 | API real sobre el contenedor y el grafo, sesión, CSRF y SSE | Hecha (revisiones de calidad guardadas desde PA-272) |
| QA encadenada | `/conversations/{id}/handoff`, `/qa/handoffs` y `/qa/handoffs/{id}/take` | Hecha (T-54 y PA-105) |

**Aún no están en el contrato.** Se añadirán con su tarea; mientras, la pantalla queda «disponible pronto»:
- reintentar solo los fallidos (PA-05);
- auditoría e historial;
- pestaña Memoria (T-33).

Requisitos de seguridad de la parte 2: `docs/api/requisitos-parte-2.md`.
