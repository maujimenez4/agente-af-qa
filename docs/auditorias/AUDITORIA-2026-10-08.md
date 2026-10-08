# Auditoría del proyecto · 2026-10-08

- **Rama y commit:** `PreProduccion` @ `912d2b6`
- **Alcance:** repositorio completo (excepto `.claude/worktrees/`, `node_modules/`, `.venv/` y artefactos)
- **Capas:** 1 (automática) + dimensiones: principios, corrección, seguridad, llm-rag, pruebas, frontend
- **Ejecutada por:** sesión principal · rango de propuestas PA-450…PA-469

## Resumen

| Gravedad | Capa 1 | Capa 2 | Total |
|---|---|---|---|
| Alta | 0 | 1 | 1 |
| Media | 0 | 11 | 11 |
| Baja | 0 | 31 | 31 |

La capa 2 dio 46 hallazgos. **En la segunda pasada se refutaron 3**, que no figuran abajo:
- el fake de `link`, porque el único llamador pasa siempre «relates to»;
- el borrado de revisiones de calidad sin desempate, porque la recién insertada siempre es la más reciente;
- la memoria descartada sin aviso, porque las memorias miden de 240 a 960 tokens y los descartes se registran.

La revisión rebajó la gravedad de 8.

**Lo más importante:** el único hallazgo alto es que una **segunda suite de QA de la misma HU no llega a Jira, pero se da por publicada**. Los CP vuelven a numerarse desde CP-01 y la idempotencia de PA-05 los confunde con los de la suite anterior. No se encontró **ningún camino que escriba en Jira sin aprobación humana**, y la capa automática sale limpia.

## Capa 1 · Comprobaciones automáticas

Recuento por regla (`uv run python .claude/skills/auditoria/checks.py`):

| Regla | Gravedad | Hallazgos |
|---|---|---|
| jira-write | alta | 0 |
| core-concrete-import | alta | 0 |
| inline-prompt | media | 0 |
| log-sensitive-field | alta | 0 |
| silent-except | media | 0 |
| redos | media | 0 |
| env-read | alta | 0 |
| web-dangerous-html | alta | 0 |
| web-dynamic-url | alta | 0 |
| web-storage-secret | alta | 0 |
| web-eval | media | 0 |

Sin hallazgos.

## Capa 2 · Principios

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| media | `core/graph/nodes.py:681-694` (y `:708`) | La edición manual (`_edit`, RF-32) solo valida el esquema, `FIXED_ON_EDIT` y que haya cambio. No aplica `suite_errors` (cobertura, citas y datos personales, `core/qa/validation.py:108-113`), y `publish` tampoco vuelve a validar. | Una suite o una HU editada a mano puede publicarse con un email o un DNI, con un caso que apunte a CA-99 o con una fuente que no estaba en el contexto. Rompe los principios 3 y 4. | En `_edit`, aplicar las mismas validaciones que a la salida del modelo y rechazar con `ReviewRejectedError`. | confirmado |
| media | `core/functional/writer.py:150-157` | Las HU (crear, evolucionar, estructurar) solo se validan por citas; nada busca datos personales ni secretos, y la suite y la memoria sí. | Un email copiado de Jira se publica, y después `memorize` falla (`MemorySynthesisError`) con la HU ya en Jira. | Aplicar `personal_data_kind` y el detector de secretos a la `UserStory` en `StoryWriter._run`, con reintento o rechazo. | confirmado |
| baja | `core/memory/seed_demo.py:76-81` | `--forzar` sobrescribe `<P>-9001.md` y `<P>-9002.md` sin comprobar que sean de ejemplo. | Se puede perder una memoria real con esas claves; solo en desarrollo y con `--forzar`. | Sobrescribir solo los archivos con la marca `FICTITIOUS`. | plausible |
| baja | `tests/unit/test_cross_a_execution.py:905` (y `:926`) | El fixture usa un IBAN de ejemplo público con dígito de control válido y un dominio `.es` registrable. | Es higiene: no son datos de una persona, pero el resto de fixtures usa `ES00…` y dominios reservados. | Usar `ES00 0000 …` y un dominio `.example` o `-test.es`. | plausible |

## Capa 2 · Corrección

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| alta | `adapters/testmgmt/jira_native.py:186-191`, `:214-220`; `core/graph/nodes.py:810-816`; `core/qa/writer.py:364-368` | La idempotencia de `publish_suite` (PA-05) solo compara el prefijo `[CP-XX]`. Una suite nueva de la misma HU (otra conversación de QA) vuelve a empezar en CP-01. Sus casos se toman por existentes, no se crea nada y el artefacto pasa a `PUBLISHED` con las claves antiguas. | El contenido aprobado no llega a Jira y la app lo da por publicado; la trazabilidad CA→CP queda falsa. Es uso normal: la HU evoluciona y se rehacen sus pruebas. | Limitar la idempotencia al artefacto (etiqueta o huella con id y versión) y tratar como conflicto un CP reutilizado con otro contenido. | confirmado |
| media | `adapters/jira/tracker.py:221-231`; `core/graph/nodes.py:822-836`; `api/service.py:694-703` | Si el PUT de `update_story` va bien y falla el comentario del diff, la auditoría `interrupted` no guarda `jira_keys`. Tras reiniciar, la conversación se ve «aprobada» sin error ni resultado. | La HU modificada en Jira no consta en la auditoría (RNF-13), y la persona puede repetir la publicación. | Auditar la clave ya escrita y mostrar un error si la fila está en `approved` sin publicación terminada. | confirmado |
| media | `core/graph/nodes.py:231-249`, `:514-516`; `core/impact/versions.py:121-126` | Al iterar, `generate` guarda la versión N+1 y después audita. Si la auditoría falla, `/retry` genera otro contenido para N+1 y `versions.save` lanza `VersionConflictError` en cada reintento. | La conversación se queda sin salida, porque tampoco se puede descartar. | Hacer `generate` idempotente: reutilizar la versión guardada o auditar antes de guardar. | plausible |
| baja (antes media) | `api/executions.py:146-169`; `core/graph/execution.py:339-385` | Si el registro de ejecución escribe en Jira y luego falla la auditoría, tras reiniciar se muestra «nada se ha escrito en Jira». | El mensaje es falso; repetir el registro casi no duplica nada (PA-208). | Calcular el estado desde `state_store[thread]["execution"]`. | confirmado |
| baja (antes media) | `api/service.py:586-592`, `:611`; `api/cancel.py:27-29`; `core/graph/nodes.py:579-583` | Una conversación en error no se puede descartar (409 `not_in_review`), aunque los mensajes de cancelación y del tope de rechazos dicen «descarta la conversación». | El texto engaña y la fila se queda en error en la lista. | Permitir descartar desde error o corregir los textos. | confirmado |
| baja | `adapters/testmgmt/jira_native.py:313-334`, `:481-485` | `record_execution` no comenta si la huella coincide con la del último comentario: una ejecución posterior idéntica no deja comentario (diseño de PA-208). | Se pierde una línea del historial de ejecuciones. | Incluir el `thread_id` en la huella. | confirmado |
| baja | `core/handoff.py:254-271`; `core/approvals.py:275-277` | Si una publicación real falla tras escribir, la aprobación queda gastada solo en memoria. Tras reiniciar, `hand_off` crea una entrega «sin publicar» de una HU que sí está en Jira. | QA recibe la HU como no publicada. | Persistir `spent` antes de escribir. | confirmado |
| baja | `adapters/llm/fallback.py:153-158` frente a `api/service.py:262-266` | El aviso diario del log cuenta desde las 00:00 UTC y la UI desde las 00:00 de Madrid. | Las cifras no cuadran durante dos horas al día. | Pasar la zona horaria por configuración. | confirmado |
| baja | `core/conversations.py:165`, `:216` | La lista de conversaciones se ordena solo por `updated_at`, sin desempate. | El orden es inestable con marcas iguales (solo es visual). | Desempatar por `created_at` y `thread_id`. | plausible |

## Capa 2 · Seguridad

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| media | `api/app.py:262-270`, `api/sessions.py:137-156`, `api/security.py:124-125` | El login cuenta los fallos también por IP (`request.client.host`), y `success()` nunca limpia la clave de la IP. Detrás del proxy de Vite o de Docker, todas las personas comparten esa IP. | Cinco fallos sumados de cualquiera bloquean el login de todos 300 s, y la espera se dobla hasta 40 min. Una prueba (`test_api_app.py:519-524`) da por bueno ese bloqueo. | No contar la IP del proxy de confianza (o leer la IP real) y limpiar `ip_key` en `success()`, o usar una ventana deslizante. | confirmado |
| baja (antes media) | `app/views/login.py:24-44`, `app/session.py:132-143`, `.streamlit/config.toml` | En Streamlit (plan B) el contador de intentos es por pestaña, y el servidor atiende en todas las interfaces. | Se salta el límite, pero con contraseñas aleatorias de 16 caracteres y argon2 la fuerza bruta no es viable. | Limitador por proceso y por usuario, y `server.address = "127.0.0.1"`. | plausible |
| baja | `api/sessions.py:21-28`, `:55-68`; `api/security.py:105-111` | La sesión guarda una copia fija del usuario: dar de baja a alguien (`core.seed_users --baja`) no corta sus sesiones abiertas. | El usuario dado de baja sigue pudiendo aprobar y publicar hasta 30 min de inactividad o 12 h. | Volver a comprobar `active` en aprobar y publicar, o en cada sesión. | confirmado |
| baja | `api/app.py:892-901`, `api/runtime.py:166-174` | `POST /quality-reviews` no limita las revisiones en curso por persona, y la cola del ejecutor no tiene tope. | Una persona puede retrasar a las demás y gastar la cuota de Groq. | Responder 429 si la persona ya tiene N revisiones en curso. | confirmado |
| baja | `core/config.py:273`, `api/app.py:1296-1298` | `app_env` es `development` por defecto, y con ese valor se publican `/api/docs` y `/api/openapi.json`. | Expone la documentación si se despliega sin cambiar el `.env`; el contrato ya es público en el repositorio. | `production` por defecto. | plausible |

## Capa 2 · LLM y RAG

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| media | `core/quality.py:125-127` | La revisión de calidad estructura la HU sin la caché compartida de PA-432 (`core/graph/nodes.py:424-428`). | Siempre gasta una llamada extra a Groq (8000 TPM), lo que acerca el 429. En casos raros, los IDs del informe pueden no coincidir con los del grafo. | Que `QualityReviewer` lea y guarde la misma caché de estructura. | confirmado |
| media | `adapters/llm/openai_compatible.py:163-171` | El reintento por validación (RNF-28) reenvía el prompt con la respuesta fallida sin pasar por la guarda de ventana. | Con el modelo local, una salida cortada de unos 2500 tokens más un prompt de más de unos 5100 superan la ventana de 10 240, y Ollama recorta en silencio (lo que PA-114 quería evitar). Es más probable en QA. Coincide con PA-440. | Estimar el reintento contra la ventana del proveedor y fallar con «no cabe» si no cabe. | plausible |
| baja (antes media) | `adapters/llm/schema_hints.py:22`, `schemas/quality.py:57` | `QualityReport` no está en `CITED_SCHEMAS`, así que su campo `sources` no es obligatorio para la gramática de Ollama. | Si la revisión de calidad cae al respaldo local, el informe puede salir sin citas y terminar en `CitationError`. | Añadir `QualityReport` a `CITED_SCHEMAS`. | plausible |
| baja | `core/impact/analysis.py:134-143` | El texto del reintento del análisis de impacto está escrito en el código y no en `prompts/`. | Incumple la convención de CLAUDE.md y RNF-18; los demás reintentos tienen su archivo. | Moverlo a `prompts/impact_retry.md` con `version:`. | confirmado |
| baja | `core/impact/analysis.py:122`, `core/memory/generator.py:244-251` | Las versiones de prompt y el modelo del impacto y de la memoria no quedan en la auditoría (solo en el log). | Trazabilidad parcial de los vínculos publicados y de la memoria. | Anotar versión y modelo en el `detail` de la auditoría. | confirmado |
| baja | `core/quality.py:98` | `PromptLimits.from_config` se llama sin `providers_of(self.c.llm)`, a diferencia del grafo. | Hoy no cambia nada; importaría con otro proveedor de ventana menor. | Pasar `providers_of(self.c.llm)`. | plausible |
| baja | `core/rag/chunking.py:24` frente a `core/context/budget.py:26` | El fragmentador estima 4 caracteres por token y el presupuesto 3. | Un fragmento «de 650 tokens» cuenta unos 887 en el presupuesto: con 2000 apenas cabe un fragmento de RAG. | Unificar la estimación o bajar `rag.chunk_tokens`. | confirmado |

## Capa 2 · Pruebas

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| media | `tests/unit/test_context_service.py:551`, `:590`; `tests/unit/test_context_window_guard.py:176`; `tests/unit/test_container.py:141` | Pruebas unitarias que cargan el `config/models.yaml` real y comprueban valores de la demo (p. ej. el presupuesto de Groq de 2000). | Ajustar la demo rompe pruebas ajenas; ya pasó con PA-441 (`docs/KANBAN.md:737`). | Usar `tests/fixtures/models.yaml` ampliado y dejar el YAML real solo en `test_config.py`. | confirmado |
| baja (antes media) | `tests/fakes/test_management.py:27-50` | El fake de `publish_suite` no es idempotente, a diferencia del real. | Solo queda sin cubrir el reintento tras un fallo parcial a nivel de grafo. | Que el fake reutilice los CP publicados y trate una vez cada `internal_id`. | plausible |
| baja | `tests/pg_temp.py:31`, `:40`; `tests/unit/test_migrations.py:98-106` | La base de datos temporal tiene un nombre fijo y se borra con `DROP DATABASE … WITH (FORCE)`. | Dos ejecuciones de integración en paralelo desde varias sesiones se la borran entre sí. | Sufijo único por ejecución. | plausible |
| baja | `tests/unit/test_cross_a_execution.py:507-520` | La prueba no tiene `assert` y confía en que un espía lance `AssertionError`. | Un `except Exception` del nodo podría tragarse el error. | Anotar las llamadas y comprobarlas al final. | plausible |
| baja | `tests/fakes/issue_tracker.py:83-88` | `update_story` del fake no actualiza el título. | Las pruebas no detectarían un título publicado perdido. | Aplicar `story_summary` al título. | plausible |
| baja | `tests/unit/`: `test_llm_fallback.py:302`, `test_rag_indexing.py:193`, `test_cross_a_execution.py:900`, `test_cross_a_jira.py:699`, `test_jira_adf.py:995`, `test_core_health.py:188` | Pruebas que dependen del reloj real: fecha calculada después de llamar al código y umbrales de tiempo de 0,5 a 0,9 s. | Pueden fallar de forma intermitente en el cambio de día o con la máquina cargada. | Inyectar fecha y reloj; en las de coste, comparar con una entrada lineal. | plausible |

## Capa 2 · Frontend

| Gravedad | Archivo:línea | Problema | Por qué importa | Corrección propuesta | Veredicto |
|---|---|---|---|---|---|
| media | `web/src/hooks/useUsage.ts:28-29`, `web/src/app/AppShell.tsx:37` | `GET /settings/usage` cada 60 s renueva la sesión (`touch=True`). | Con una pestaña abierta, la caducidad por inactividad (30 min) no llega nunca; solo queda el tope de 12 h. | Pausar la consulta sin visibilidad o actividad, o leer la sesión con `touch=False` en esa ruta. | confirmado |
| media | `web/src/screens/ChooseInJira/ChooseInJira.tsx:30-34`, `:53`, `:70`, `:86`, `:121-122`, `:231-248` | «Elegir en Jira» no tiene estado de carga y comparte un solo error entre sus cuatro cargas. | Mientras Jira responde se ve «Este proyecto no tiene épicas.»; un error desaparece si otra carga termina bien. | Distinguir «cargando» de «vacío» y llevar un error por carga. | confirmado |
| media | `web/src/api/client.ts:89`, `:107-111`; `web/src/session/SessionProvider.tsx:12-23` | Un 403 por CSRF no vuelve a pedir `/auth/me`. | Si se inicia sesión en otra pestaña, la primera recibe «Sin permiso» en cada acción, sin otra salida que recargar. | Ante un 403 en un método que modifica, pedir `/auth/me` y actualizar el token o volver al login. | plausible |
| baja (antes media) | `web/src/screens/Origin/OriginScreen.tsx:122-123`, `:344-346`, `:449` | «Reintentar» en las fuentes solo cierra la tarjeta, y mientras cargan la lista sale vacía sin indicador. | No se pueden ajustar las fuentes sin recargar, aunque «Generar» sigue funcionando. | Que «Reintentar» recargue las fuentes, y un estado de carga. | confirmado |
| baja (antes media) | `web/src/app/AppShell.tsx:128-135`, `:170-181` | `openConversation` no descarta respuestas viejas. | Pulsar A (lenta) y luego B puede mostrar A con B marcada en la lista. | Comprobar el `currentId` o usar `AbortController`. | plausible |
| baja | `web/src/app/AppShell.tsx:165-169`, `:187` | `openError` no se borra con «Nueva conversación», y su «Reintentar» solo lo cierra. | El aviso de error se queda sobre Inicio. | Borrarlo en `onNew` y que «Reintentar» vuelva a abrir la conversación. | confirmado |
| baja | `web/src/screens/Edit/StoryEditor.tsx:77-85`, `:141-143` | Quitar, Subir y Bajar pierden el foco. | Quien usa teclado o lector de pantalla tiene que volver a buscar el sitio. | Mover el foco al elemento afectado. | confirmado |
| baja | `web/src/screens/ChooseInJira/ChooseInJira.tsx:199-210`, `web/src/screens/Memory/MemoryScreen.tsx:120-127` | Los buscadores no tienen `maxLength`, y la API limita `q` a 200 y 100 caracteres. | Pegar un texto largo da 422 «Petición no válida». | Poner `maxLength` según el contrato. | confirmado |
| baja | `web/src/screens/Quality/QualityScreen.tsx:139-149` | Una revisión que falla al cargar con `not_found` o `forbidden` no ofrece ningún botón. | La pantalla no da salida, salvo la lista y el carril. | Añadir «Volver al inicio». | confirmado |
| baja | `web/src/api/events.ts:101-105`, `web/src/screens/Generating/GeneratingScreen.tsx:134` | Un 401 al abrir `/events` no avisa a la sesión, y el botón «Iniciar sesión» reintenta. | El botón no hace lo que dice. | Avisar a la sesión como hace `request()`. | plausible |
| baja | `web/src/app/AppShell.tsx:366-369` | «Reintentar» no respeta `retry_after`. | Solo produce otro `rate_limited`. | Desactivarlo durante la espera. | plausible |
| baja | `web/src/components/Modal/Modal.tsx:50-53` | El modal no marca `inert` lo que queda detrás. | Algunos lectores de pantalla pueden recorrerlo. | Reutilizar `inertBehind` de `useLayer`. | plausible |

## Clasificación pensando en la demo

Es un añadido de esta ejecución: la demo es la semana del 2026-10-12.

| Grupo | Hallazgos |
|---|---|
| **Riesgos para el guion** (evitarlos aunque no se arreglen) | **Una segunda suite de una HU que ya tiene casos** (alta): no publicar otra suite de AFQP-27 (ya tiene AFQP-29…34). **Login por IP:** pocos fallos de contraseña bloquean a todos; usar contraseñas copiadas y, si pasa, reiniciar la API (el contador vive en memoria). |
| **Arreglos rápidos** (menos de una hora, poco riesgo) | Login: limpiar la IP al entrar bien y no contarla detrás del proxy. Pruebas con su propio `models.yaml`. `maxLength` en los buscadores. Textos de «descarta la conversación». «Volver al inicio» en Calidad. «Reintentar» de las fuentes. `QualityReport` en `CITED_SCHEMAS`. `providers_of` en `QualityReviewer`. |
| **Mejoras para después de la demo** | Idempotencia de la suite por artefacto (alta, pero de diseño). Validaciones en la edición manual y datos personales en la HU. Auditoría de `update_story` parcial. `generate` idempotente. Caché de estructura en Calidad. Reintento RNF-28 contra la ventana (con PA-440). CSRF tras otro login. Carga y errores de «Elegir en Jira». Consulta de uso que renueva la sesión. |

## Propuestas para el Kanban

Altas y medias, con el siguiente número libre del rango de la sesión principal. **Pendiente de confirmación:** no se añaden al Kanban ni se corrige nada sin el visto bueno.

| PA | Gravedad | Propuesta | Origen |
|---|---|---|---|
| PA-450 | alta | Idempotencia de `publish_suite` por artefacto (etiqueta o huella con id y versión): una segunda suite de la misma HU no debe darse por publicada con los CP de la anterior. Un CP reutilizado con otro contenido cuenta como conflicto | Auditoría 2026-10-08 · corrección |
| PA-451 | media | La edición manual aplica las mismas validaciones que la salida del modelo: datos personales y secretos, CA/RN existentes y fuentes citables | Auditoría 2026-10-08 · principios |
| PA-452 | media | Detectar datos personales y secretos en las HU (`StoryWriter._run`), antes de la revisión humana | Auditoría 2026-10-08 · principios |
| PA-453 | media | Publicación parcial de `update_story` (PUT bien y comentario mal): auditar la clave escrita y mostrar error tras reiniciar | Auditoría 2026-10-08 · corrección |
| PA-454 | media | `generate` idempotente ante `/retry` tras guardar la versión (sin `VersionConflictError` sin salida) | Auditoría 2026-10-08 · corrección |
| PA-455 | media | Límite de login: no contar la IP del proxy de confianza (o leer la real) y limpiar `ip_key` al entrar bien | Auditoría 2026-10-08 · seguridad |
| PA-456 | media | La revisión de calidad usa la caché de estructura compartida (PA-432) | Auditoría 2026-10-08 · llm-rag |
| PA-457 | media | El reintento por validación (RNF-28) pasa por la guarda de ventana del proveedor; se une a PA-440 | Auditoría 2026-10-08 · llm-rag |
| PA-458 | media | Las pruebas unitarias usan `tests/fixtures/models.yaml` y no la configuración real de la demo | Auditoría 2026-10-08 · pruebas |
| PA-459 | media | La consulta de uso de la web no renueva la sesión (pausa sin visibilidad o `touch=False`) | Auditoría 2026-10-08 · frontend |
| PA-460 | media | «Elegir en Jira»: estados de carga y un error por cada carga | Auditoría 2026-10-08 · frontend |
| PA-461 | media | Ante un 403 por CSRF, la web vuelve a pedir `/auth/me` y actualiza el token o vuelve al login | Auditoría 2026-10-08 · frontend |
