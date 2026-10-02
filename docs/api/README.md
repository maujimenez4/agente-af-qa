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
  - `publish_failed`: Jira rechazó la publicación. Una publicación **parcial** no es un error: llega en `result.errors`, con el estado `approved`.
- **Consumo de hoy** (anillo del carril): `GET /settings/usage` devuelve `tokens_today` y `warning_threshold`. Es el consumo de **toda la instalación** (`scope: "global"`): el registro de uso no guarda la persona. Incluye el `422` de validación, que nunca devuelve lo enviado.
- **Estados de una conversación:**
  - **en la lista** (`ConversationSummary.status`): `started`, `in_review`, `approved`, `simulated`, `published` y `discarded`;
  - **en el detalle** (`ConversationOut.state`): `generating` en lugar de `started` (el grafo está trabajando), los demás iguales, y además `error` (falló la última operación);
  - una publicación parcial queda en `approved`, con `result.errors` y `result.failed_ids`.
- **Flujo y origen:**
  - `flow=need` admite un origen `need` o `epic`;
  - `evolve` y `tests` admiten solo `story`;
  - `tests` no admite texto libre.

  Las opciones de `POST /start/propose` traen el `origin` listo.

## Estado
| Parte | Contenido | Estado |
|---|---|---|
| 1 | Contrato completo, ejemplos y API simulada | Hecho (las rutas reales responden 501) |
| 2 | API real sobre el contenedor y el grafo, sesión, CSRF y SSE | Hecha (las revisiones de calidad viven en memoria del proceso, PA-103) |
| QA encadenada | `/conversations/{id}/handoff` y `/qa/handoffs` | **Provisional** hasta que T-54 cierre su diseño |

**Aún no están en el contrato.** Se añadirán con su tarea; mientras, la pantalla queda «disponible pronto»:
- registro de la ejecución (QA 6, T-47);
- reintentar solo los fallidos (PA-05);
- auditoría e historial;
- pestaña Memoria (T-33);
- administración (T-29);
- revisiones de calidad en la lista de conversaciones;
- presupuesto de tokens del panel de fuentes;
- si la HU ya tiene casos en Jira (tarjeta de QA 1).

Requisitos de seguridad de la parte 2: `docs/api/requisitos-parte-2.md`.
