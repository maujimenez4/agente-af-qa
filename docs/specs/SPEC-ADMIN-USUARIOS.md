# SPEC-ADMIN-USUARIOS · Gestión de usuarios en Administración

| Campo | Valor |
|---|---|
| Versión | 1.0 · borrador para revisión (2026-10-14) |
| Propietario | Sesión Seguridad (redacta) · sesión principal (aprueba contrato y RF) |
| PA | PA-486 |
| Responde a | RF-45, RF-46, RF-52 (propuesto), D-01, D-05, RNF-01, RNF-02, RNF-05, RNF-06, RNF-12, RNF-23; PA-279, PA-284, PA-286, PA-287 |
| Estado | Especificación. **No hay código**: rutas, modelos y nombres nuevos son una propuesta |

> Convención: lo que **ya existe** se cita con su ruta (`archivo:línea`). Lo que se propone va marcado como **(nuevo)**. Los ejemplos usan datos ficticios y placeholders (`TU_CONTRASEÑA`).

---

## 1. Objetivo y alcance

Que la persona con rol `admin` gestione las cuentas de FAQ desde **Ajustes** en la web, sin usar el comando `python -m core.seed_users`, y sin que ninguna contraseña quede guardada en claro, en logs ni en respuestas que se puedan repetir.

### Entra en v1.1
1. Listar los usuarios con su rol y su estado (activo o de baja).
2. **Alta** de un usuario con un rol. FAQ genera una contraseña aleatoria y la muestra **una sola vez**.
3. **Cambio de rol** de otra persona.
4. **Reinicio de contraseña**: contraseña nueva aleatoria, mostrada una sola vez.
5. **Baja** (desactivar), con el inventario de lo que se borra **antes** de confirmar (RGPD, PA-286).
6. **Reactivación** de una cuenta dada de baja, con contraseña nueva mostrada una sola vez.
7. Cierre inmediato de las sesiones de una persona al darla de baja o cambiar su rol (PA-287).
8. Auditoría de cada acción en `audit_log`, sin contraseñas ni hashes.

### No entra (v1.1)
- SSO o proveedor de identidad corporativo (D-05; fuera de alcance en las declaraciones, §3.3).
- Que cada persona cambie su propia contraseña (autoservicio): propuesta **PA-496**.
- Renombrar usuarios o borrarlos físicamente de la tabla `users`: la baja desactiva.
- Auditar los inicios de sesión (PA-27) e historial de accesos.
- Gestión de usuarios en Streamlit (plan B, `app/`): solo se adapta para que respete las bajas (§6, A-08).
- Roles nuevos: siguen siendo `functional`, `qa` y `admin` (D-01, `CHECK ck_users_role`).

## 2. Trazabilidad

| Referencia | Texto (resumen) | Relación |
|---|---|---|
| RF-45 | Autenticar usuarios locales (contraseña con hash) — ✅ | Se mantiene: argon2 y `LocalAuthProvider.authenticate` |
| RF-46 | Gestionar los tipos de usuario y sus permisos — ✅ (por comando) | Se amplía a la web |
| **RF-52 (nuevo, propuesto)** | «Gestionar cuentas desde Administración: alta, rol, baja, reactivación y reinicio de contraseña» · EP-08 · v1.1 · Should | **Pendiente de la principal** |
| D-01 | Tres tipos de usuario; el administrador configura y no genera | Solo `admin` gestiona usuarios; los demás no ven la tarjeta |
| D-05 | Autenticación simple con usuarios locales | Sin SSO |
| RNF-01 / RNF-02 | Secretos fuera del código y nunca en logs, trazas ni respuestas | La contraseña solo viaja en la respuesta del alta o del reinicio |
| RNF-05 | Acceso según el tipo de usuario | `Permission.MANAGE_USERS` (`core/permissions.py:23`) |
| RNF-06 | Solo datos sintéticos en desarrollo y demo | Ejemplos y pruebas con usuarios ficticios |
| RNF-12 / RNF-23 | Errores claros; logs estructurados | Mensajes en español; logs sin contenido |
| PA-279 / PA-284 / PA-286 / PA-287 | Retención, baja de cualquier persona, inventario RGPD, sesiones tras la baja | §6 |

## 3. Estado actual

| Pieza | Qué hay | Qué falta |
|---|---|---|
| Tabla `users` | `migrations/versions/0001_initial.py:55-64`: `id`, `username` (único), `password_hash`, `role` (CHECK `functional`/`qa`/`admin`), `active`, `created_at` | `updated_at` (opcional, §4.4) |
| Proveedor | `adapters/auth/local.py:51` `LocalAuthProvider`: `authenticate` (l. 66-88, tiempo constante, rehash, rol desconocido falla cerrado) y `save_user` (l. 90-114, **upsert**) | Listar, obtener, crear sin pisar, cambiar rol, activar/desactivar y contar admins |
| Protocolo | `adapters/base.py:182-184` `AuthProvider` con solo `authenticate` | Un protocolo de administración (**nuevo** `UserAdmin`, §4.4) |
| argon2 | `PasswordHasher()` sin parámetros (`local.py:56`): argon2id, `time_cost=3`, `memory_cost=64 MiB`, `parallelism=4` (argon2-cffi 25.1.0, `uv.lock`) | — (se mantiene) |
| Contraseñas | `adapters/auth/seed.py:19-24`: `generate_password()` con `secrets.choice`, 16 caracteres de 62 símbolos | — (se reutiliza) |
| Validación | `USERNAME_RE` (`local.py:33`), 12-256 caracteres (`:34-35`) | Sus `ValueError` saldrían como 500: `adapters.auth.local` no está en `SAFE_VALUE_ERROR_MODULES` (`api/errors.py:31-39`). La API debe validar antes (§4.2) |
| Comando | `core/seed_users.py`: crea los usuarios de demo; `--baja` solo para `af-demo`, `qa-demo` y `admin-demo` (PA-284), con efecto colateral de crear inactivo uno no sembrado | Se mantiene para la demo; la gestión real pasa a la web |
| Permisos | `MANAGE_USERS` en `core/permissions.py:23`, solo `admin` | **No lo usa ninguna ruta** |
| Bloqueo por intentos | `api/sessions.py:115-169` `LoginLimiter` (5 intentos, 300 s, espera progresiva, PA-455/PA-470) | — (se mantiene) |
| Sesiones | `api/sessions.py:32-102` `SessionStore`; la sesión guarda una **copia fija** del `User` (`ApiSession.user`, l. 21-29) | Cerrar las sesiones de una persona y volver a comprobar `active` y rol (PA-287) |
| Auditoría | `core/audit.py:17` `AuditAction` = `create`, `iterate`, `approve`, `publish`, `discard`; CHECK `ck_audit_log_action` en `0001_initial.py:102-121` | Acciones de usuarios (**requiere migración** del CHECK, §6.6) |
| Baja (RGPD) | `core/seed_users.deactivate` borra las revisiones de calidad (`core/quality.py` `delete_for`) | Borrar conversaciones no publicadas, checkpoints y la preferencia de proyecto; no existen métodos de borrado por persona en `conversations` ni en `last_projects` |
| Rutas | `api/admin.py`: solo `POST /admin/connections/test` y `GET /admin/models` | `/admin/users` |
| Web | `web/src/screens/Admin/AdminScreen.tsx:280-301` `SoonCard`: «Usuarios y roles» con «Disponible pronto» y `SoonButton` «Gestionar usuarios» (`adminText.ts:29-35`) | La tarjeta real |
| MCP | `mcp_server/__main__.py:42-46` construye el `User` desde `MCP_USER`/`MCP_ROLE` **sin consultar `users`** | Propuesta **PA-497** (§6.7) |

## 4. API propuesta

**No se toca `api/` ni el contrato en esta ronda.** Todo cuelga de `APIRouter(prefix="/admin")` (`api/admin.py:40`), bajo `/api/v1`, con el patrón ya existente:

```python
session = session_for(request)          # sesión; en POST/PATCH además origen y X-CSRF-Token
require(session.user, Permission.MANAGE_USERS)
```

### 4.1 Rutas

| Método y ruta | Qué hace | Respuesta |
|---|---|---|
| `GET /admin/users` | Lista de usuarios | 200 `UsersOut` |
| `POST /admin/users` | Alta con contraseña generada | 201 `UserCreatedOut` (contraseña **una vez**) |
| `PATCH /admin/users/{username}` | Cambia el rol | 200 `UserOut` |
| `POST /admin/users/{username}/password` | Reinicia la contraseña | 200 `PasswordOut` (**una vez**) |
| `GET /admin/users/{username}/offboarding` | Inventario de lo que se borrará al darla de baja | 200 `OffboardingPreview` |
| `POST /admin/users/{username}/deactivate` | Baja: desactiva, cierra sesiones y borra lo del inventario | 200 `OffboardingOut` |
| `POST /admin/users/{username}/activate` | Reactiva con contraseña nueva | 200 `PasswordOut` (**una vez**) |

`{username}` sigue `USERNAME_RE` (`adapters/auth/local.py:33`); otro formato → 422 `invalid_request` antes de tocar la base de datos.

### 4.2 Modelos (pseudocódigo pydantic; modelos **nuevos** en `api/models.py`, que ya existe)

```python
Username = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9._-]{2,49}$")]
Role = Literal["functional", "qa", "admin"]

class UserRow(BaseModel):          # nunca lleva hash ni contraseña
    username: Username
    role: Role
    active: bool
    created_at: datetime

class UsersOut(BaseModel):
    users: list[UserRow]           # orden: activos primero, luego por username

class UserCreateIn(BaseModel):     # sin campo de contraseña: la genera FAQ
    username: Username
    role: Role

class PasswordOut(BaseModel):
    user: UserRow
    password: str                  # 16 caracteres de `generate_password()`; se muestra una vez
    shown_once: Literal[True] = True

class UserCreatedOut(PasswordOut): ...

class UserRoleIn(BaseModel):
    role: Role

class OffboardingPreview(BaseModel):
    username: Username
    conversations_to_delete: int   # conversaciones no publicadas (§6.5)
    quality_reviews_to_delete: int
    kept: list[Literal["published_conversations", "audit_log", "qa_handoffs"]]
    fingerprint: str               # huella del inventario: si cambia antes de confirmar, 409

class DeactivateIn(BaseModel):
    fingerprint: str               # la de la vista previa que vio la persona

class OffboardingOut(BaseModel):
    user: UserRow                  # active = False
    deleted_conversations: int
    deleted_quality_reviews: int
    closed_sessions: int
```

Validar en el modelo (no en `save_user`) evita que los `ValueError` de `adapters.auth.local` lleguen como 500.

### 4.3 Errores

Se reutilizan los `ErrorCode` existentes (`api/models.py:39-74`) y se proponen **dos nuevos** (cambio de contrato de la principal):

| HTTP | `code` | Cuándo | Mensaje |
|---|---|---|---|
| 401 | `unauthenticated` | Sin sesión | «Inicia sesión para continuar.» |
| 403 | `forbidden` | Sin `MANAGE_USERS`, sin CSRF u origen no permitido, o cambiar el **propio** rol o darse de baja a sí mismo | «No tienes permiso para realizar esta acción.» / «No puedes cambiar tu propio rol ni darte de baja.» |
| 404 | `not_found` | El usuario no existe | «No existe el usuario «x».» |
| 409 | `user_exists` **(nuevo)** | Alta de un nombre ya usado (activo o de baja) | «Ya existe el usuario «x». Si está de baja, reactívalo.» |
| 409 | `last_admin` **(nuevo)** | El cambio dejaría el sistema sin ningún `admin` activo | «Tiene que quedar al menos un administrador activo.» |
| 409 | `operation_failed` | El inventario cambió entre la vista previa y la confirmación | «La información de la baja ha cambiado. Revísala y vuelve a confirmar.» |
| 422 | `invalid_request` | Nombre o rol con formato no válido | «El nombre de usuario debe tener entre 3 y 50 caracteres: minúsculas, números, punto, guion o guion bajo.» |
| 429 | `rate_limited` | Más de 10 acciones de escritura por minuto y admin (§6.3) | «Espera unos segundos antes de seguir.» con `retry_after` |
| 503 | `service_unavailable` | Base de datos no disponible (`ExternalServiceError` de `local.py:129-137`) | «No se pudo acceder a la base de datos de usuarios.» |

Los mensajes nunca repiten la contraseña ni dicen si un nombre existe a quien no es admin (solo `admin` llega a estas rutas).

### 4.4 Piezas internas (propuesta)

- **(nuevo)** protocolo `UserAdmin` en `adapters/base.py` (sección congelada: lo cambia la principal):
  `list_users()`, `get_user(username)`, `create_user(username, password, role)` (falla si existe; **no** upsert), `set_role(username, role)`, `set_active(username, active, password)`, `set_password(username, password)` y `count_active_admins()`.
- **(nuevo)** su implementación en `adapters/auth/local.py`. Toda escritura de usuarios toma `pg_advisory_xact_lock(<constante>)` al empezar la transacción y la comprobación del último admin se hace dentro de ella (`SELECT count(*)` tras el bloqueo; `FOR UPDATE` no admite agregados). Así dos peticiones simultáneas no dejan el sistema sin admin.
- **(nuevo)** `UserExistsError` en `adapters/errors.py` (congelado), mapeado a 409 `user_exists` en `api/errors.py`.
- **(nuevo)** `SessionStore.drop_user(username) -> int` en `api/sessions.py`: cierra las sesiones de esa persona, **sus SSE abiertos** y marca como cancelados sus trabajos pendientes en `Runtime` (los que aún no han empezado a publicar), y devuelve cuántas sesiones cerró.
- **(nuevo)** comprobación de `active` y rol en cada petición autenticada, dentro de `SessionStore.get` (así la cubren tanto `current_session` como `SessionGuardMiddleware`, que llama a `rt.sessions.get` directamente), con una consulta ligera por `username`; si la cuenta está de baja, 401 `unauthenticated` y se cierra la sesión; si el rol cambió, la sesión se cierra (vuelve a iniciar sesión con el rol nuevo).
- **(nuevo)** el nodo `publish` (`core/graph/nodes.py`) comprueba que la persona sigue activa y con el permiso de publicar **justo antes** de escribir en Jira, para que una generación ya confirmada no publique tras una baja o un cambio de rol.
- **(nuevo)** servicio de baja en `core/` (p. ej. `core/offboarding.py`): calcula el inventario y la huella, y ejecuta los borrados (§6.5). Necesita métodos de borrado por persona que **no existen** hoy en el almacén de conversaciones, en el checkpointer y en `last_projects`.
- Opcional: columna `users.updated_at` en la misma migración (§6.6).

## 5. Flujo en la web

Coherente con UI.md §10 (Ajustes, solo admin) y el estilo de la «Propuesta mixta». La tarjeta «Usuarios y roles» deja de ser «Disponible pronto» (`web/src/screens/Admin/adminText.ts:29-35`; cambian `AdminSoon.pa431.test.tsx` y `AdminScreen.test.tsx`).

### 5.1 Tarjeta «Usuarios y roles»
- Tabla: **Usuario** · **Rol** («Analista funcional», «QA», «Administrador») · **Estado** («Activo» / «De baja», con `Badge`) · **Acciones**.
- Acciones por fila: *Cambiar rol*, *Reiniciar contraseña*, *Dar de baja* (activas) o *Reactivar* (de baja). En la fila propia, *Cambiar rol* y *Dar de baja* están desactivadas con la nota «No puedes cambiar tu propio rol ni darte de baja.».
- Botón *Añadir usuario*.
- Estados: cargando (esqueleto), vacío imposible (siempre hay al menos el admin), error con `ErrorCard` y *Reintentar*.

### 5.2 Alta
- Diálogo «Añadir usuario»: **Usuario** (ayuda: «Entre 3 y 50 caracteres: minúsculas, números, punto, guion o guion bajo.») y **Rol**.
- Al crear: diálogo **«Contraseña de {usuario}»** con el texto «Cópiala ahora y entrégala por un canal seguro: no se volverá a mostrar.», el valor en un campo de solo lectura con *Copiar* y la casilla «Ya la he guardado», que habilita *Cerrar*.
- Al cerrar, la contraseña se borra del estado de React. Nunca se guarda en `localStorage`, `sessionStorage`, la URL ni el registro de la consola.

### 5.3 Cambio de rol
- Diálogo «Cambiar el rol de {usuario}» con el rol nuevo y el aviso «Se cerrarán sus sesiones abiertas: tendrá que volver a iniciar sesión.».
- Errores: `last_admin` → «Tiene que quedar al menos un administrador activo.».

### 5.4 Reinicio de contraseña
- Confirmación «Reiniciar la contraseña de {usuario}» → «Se generará una contraseña nueva y se cerrarán sus sesiones.» → el mismo diálogo de una sola vez de 5.2.

### 5.5 Baja (con inventario previo)
1. Al pulsar *Dar de baja*, la web pide `GET /admin/users/{username}/offboarding`.
2. El diálogo muestra el inventario **antes** de confirmar:
   «Se borrarán **N conversaciones en curso** y **M revisiones de calidad** de {usuario}. Lo publicado y la auditoría se conservan. Sus sesiones se cerrarán.»
3. *Dar de baja* envía la huella. Si el inventario cambió (409 `operation_failed`), el diálogo se recarga con el nuevo y avisa.
4. Resultado: la fila pasa a «De baja» y un aviso resume lo borrado.

### 5.6 Reactivación
- «Reactivar a {usuario}» → «Se generará una contraseña nueva.» → diálogo de una sola vez.

## 6. Seguridad y privacidad

### 6.1 Amenazas y mitigaciones

| # | Amenaza | Mitigación |
|---|---|---|
| A-01 | La contraseña se filtra (logs, auditoría, trazas, caché, historial, red) | Se genera con `secrets` (`adapters/auth/seed.py:23-24`, 16 caracteres, ~95 bits) y solo viaja en la respuesta de alta, reinicio o reactivación. `Cache-Control: no-store` ya va en todas las respuestas (`api/security.py` `SECURITY_HEADERS`). El log solo lleva `user`, `action`, `target` y `duration_ms`; nunca el cuerpo (`RequestLogMiddleware` no registra cuerpos). No hay ruta para volver a leerla. La web no la persiste (5.2). Fuera de localhost, solo por HTTPS y con la cookie `Secure` (RNF-03; `api_cookie_secure`, `core/config.py`) |
| A-02 | Se adivina o se rompe una contraseña | argon2id (`local.py:56`), bloqueo por intentos con espera progresiva (`api/sessions.py` `LoginLimiter`, PA-455/PA-470); contraseñas aleatorias de 16 caracteres; mínimo 12 y máximo 256 en `save_user` |
| A-03 | Un admin se quita su propio rol o se da de baja y deja el sistema sin admin | 403 para cambios sobre uno mismo; 409 `last_admin` si quedaría a cero, comprobado en la misma transacción (4.4) |
| A-04 | La cuenta dada de baja o con el rol cambiado sigue con sesiones abiertas, SSE o trabajos en marcha (PA-287) | `drop_user` al momento (sesiones, SSE y trabajos pendientes), comprobación de `active` y rol en cada petición y en `publish` antes de escribir en Jira (4.4) |
| A-05 | CSRF o petición desde otro origen | `session_for` + `SessionGuardMiddleware` (`api/security.py`) en todas las rutas de escritura |
| A-06 | Escalada: alguien sin `MANAGE_USERS` usa las rutas | `require(..., MANAGE_USERS)` en cada ruta; la web oculta la tarjeta por rol (`web/src/app/AppShell.tsx:65`), pero la API decide |
| A-07 | Abuso o error en bucle (altas o reinicios masivos) | Límite de 10 escrituras por minuto y admin (429 `rate_limited`), con un limitador como `ConnectionTestLimiter` (`api/admin.py:43-59`) |
| A-08 | Streamlit (plan B) o el servidor MCP ignoran la baja | Streamlit: comprobar `active` **y el rol** al usarse la sesión (`app/session.py`, área B). MCP: **limitación conocida** hasta PA-497 (sigue actuando como `MCP_USER` dado de baja, solo lectura); se recomienda hacer PA-497 antes de implementar esta spec (§9) |
| A-10 | El admin conoce la contraseña que genera y nadie la cambia: la auditoría de quién aprobó o publicó pierde valor como prueba de autoría | **Riesgo aceptado en v1.1** (P-01): contraseña entregada por un canal seguro y auditoría del reinicio; se recomienda subir la prioridad de PA-496 (autoservicio y `must_change_password`) |
| A-09 | Datos personales reales en nombres de usuario | El formato `USERNAME_RE` no impide un nombre real; en demo y pruebas, solo nombres ficticios (RNF-06). La auditoría guarda el `username` como identificador de la cuenta |

### 6.2 Política de contraseñas
- Siempre generadas por FAQ: 16 caracteres de `[A-Za-z0-9]` con `secrets`. No se aceptan contraseñas elegidas por el admin en v1.1.
- Mínimo 12 y máximo 256 ya validados en `save_user` (`local.py:34-35`).
- Se entregan a la persona por un canal seguro fuera de FAQ; el cambio por la propia persona es PA-496.

### 6.3 Límites
- Escrituras de usuarios: 10 por minuto y admin. Lecturas sin límite propio.

### 6.4 Bloqueo por intentos
- Sin cambios: `LoginLimiter` por usuario y por IP (PA-455, PA-469, PA-470). Una baja no toca el limitador; un reinicio de contraseña sí llama a `signed_in` del usuario para que no arrastre bloqueos de la contraseña anterior.

### 6.5 Baja e inventario RGPD (PA-279, PA-284, PA-286)

| Dato | Al dar de baja |
|---|---|
| `users` | `active=false` y contraseña aleatoria nueva que no se muestra (como `core/seed_users.deactivate`); la fila se conserva para poder reactivar |
| Sesiones de la API | Se cierran (`drop_user`) |
| `quality_reviews` | Se borran (`delete_for`, ya existe) |
| Conversaciones **no publicadas** (estados `started`, `in_review`, `discarded`, `simulated`) y sus checkpoints de LangGraph | Se borran (métodos **nuevos**) |
| Conversaciones `approved` (pueden tener escrituras parciales, PA-324) y `published` | Se conservan (trazabilidad de lo escrito en Jira) |
| `user_last_project` | Se borra (método **nuevo**) |
| `audit_log` | Se conserva (trazabilidad, principio 4); guarda el `username`, nunca contenido |
| `qa_handoffs` | Se conservan (refieren HU publicadas) |
| `llm_usage` | Sin usuario: no aplica |
| `document_jobs.uploaded_by` y documentos que subió (SPEC-ADMIN-DOCUMENTOS) | Se conservan: el documento es de la organización; el trabajo se purga a los 90 días |
| Logs con el campo `user` | Fuera de FAQ: dependen de la rotación del sistema donde se despliegue; documentar el plazo en el despliegue |

- El inventario se calcula en la vista previa y la baja se confirma con su huella (un hash de los ids afectados, sin datos): no se borra nada que la persona no haya visto.
- Orden de la baja, en **una transacción** (sin ventana para crear conversaciones nuevas): bloquear la fila del usuario → `active=false` → cerrar sesiones (`drop_user`) → recalcular el inventario → comparar la huella (si no coincide, deshacer y 409) → borrar. Las sesiones cerradas en memoria no vuelven con el deshacer: con un 409, la persona tendrá que volver a iniciar sesión.
- `QUALITY_RETENTION_DAYS` (90) y la purga existente siguen aplicándose a las cuentas activas.

### 6.6 Auditoría
- Acciones nuevas en `AuditAction` y en el CHECK `ck_audit_log_action`: `user_create`, `user_update`, `user_password_reset`, `user_deactivate` y `user_activate`. **Una sola migración** para estas y las de documentos (`document_upload`, `document_delete`, ver SPEC-ADMIN-DOCUMENTOS §6.10).
- `AuditEntry(artifact_id=None, action=…, user=<admin>, detail={"target": <username>, "role": …, "active": …, "deleted_conversations": N, "deleted_quality_reviews": M})`.
- **Nunca** contraseña, hash ni el cuerpo de la petición (`core/audit.py:1-5`).

### 6.7 Fuera de la API
- El servidor MCP actúa como `MCP_USER` sin consultar `users`: una baja no le afecta. Propuesta PA-497: comprobar que el usuario existe y está activo al arrancar y en cada herramienta.

## 7. Criterios de aceptación

| ID | Criterio |
|---|---|
| CA-USR-01 | Un `admin` ve la lista de usuarios con rol y estado; la respuesta no contiene ningún hash ni contraseña |
| CA-USR-02 | Un `functional` o `qa` recibe 403 `forbidden` en todas las rutas `/admin/users*` y la web no le muestra la tarjeta |
| CA-USR-03 | El alta devuelve 201 con una contraseña de 16 caracteres que verifica con `authenticate`; ninguna otra ruta la vuelve a devolver |
| CA-USR-04 | La contraseña generada no aparece en ningún log (`capture_logs`), en `audit_log` ni en trazas |
| CA-USR-05 | Todas las respuestas de `/admin/users*` llevan `Cache-Control: no-store` |
| CA-USR-06 | El alta de un nombre existente (activo o de baja) da 409 `user_exists` y no cambia su contraseña ni su rol (no hay upsert) |
| CA-USR-07 | Un nombre o rol con formato no válido da 422 `invalid_request`, nunca 500 |
| CA-USR-08 | Un admin no puede cambiar su propio rol ni darse de baja: 403 con el motivo |
| CA-USR-09 | Ningún cambio deja el sistema sin `admin` activo: 409 `last_admin`, también con dos peticiones simultáneas |
| CA-USR-10 | Tras una baja, las sesiones de esa persona responden 401 al momento y su login falla |
| CA-USR-11 | Tras un cambio de rol, las sesiones de esa persona se cierran; al volver a entrar tiene los permisos del rol nuevo |
| CA-USR-12 | La vista previa de la baja muestra el número exacto de conversaciones no publicadas y de revisiones de calidad que se borrarán, y la web lo enseña **antes** de confirmar («Se borrarán N conversaciones en curso y M revisiones de calidad. Lo publicado y la auditoría se conservan») |
| CA-USR-13 | Si el inventario cambia entre la vista previa y la confirmación, la baja da 409 y no borra nada |
| CA-USR-14 | La baja borra las conversaciones no publicadas, sus checkpoints, las revisiones de calidad y la preferencia de proyecto, y conserva las `approved`/`published`, la auditoría y las entregas a QA |
| CA-USR-15 | La reactivación genera una contraseña nueva mostrada una sola vez; la anterior ya no sirve |
| CA-USR-16 | El reinicio de contraseña invalida la anterior y cierra las sesiones de la persona |
| CA-USR-17 | Cada acción deja una entrada en `audit_log` con la acción nueva, el admin y el usuario afectado, sin contraseña ni hash |
| CA-USR-18 | Sin `X-CSRF-Token` u origen no permitido, las escrituras dan 403 y no cambian nada |
| CA-USR-19 | Más de 10 escrituras por minuto del mismo admin dan 429 `rate_limited` con `retry_after` |
| CA-USR-20 | La web borra la contraseña de su estado al cerrar el diálogo y no la escribe en almacenamiento del navegador |
| CA-USR-21 | Tras una baja o un cambio de rol, sus SSE abiertos se cierran, sus trabajos pendientes se cancelan y `publish` no escribe en Jira si la persona ya no está activa o no tiene el permiso |
| CA-USR-22 | Hasta que se haga PA-497, el README y el apartado del servidor MCP dicen que el MCP no respeta las bajas; con PA-497 hecha, un `MCP_USER` de baja no puede usar ninguna herramienta |

## 8. Plan de pruebas

| Nivel | Qué | Dónde |
|---|---|---|
| Unitarias con fakes | Rutas, permisos, errores, CSRF, límites, no-store, sesiones cerradas, inventario y huella, auditoría sin contraseña, logs sin contraseña | `tests/unit/`, con `FakeAuthProvider` (`tests/fakes/auth.py`) ampliado con `UserAdmin` en memoria, `InMemoryAuditTrail` y el almacén de conversaciones en memoria |
| `integration` | `LocalAuthProvider` contra PostgreSQL: crear sin upsert, último admin con dos transacciones simultáneas (con el bloqueo consultivo), migración del CHECK de auditoría, borrados de la baja (conversaciones, checkpoints, preferencia) | `tests/` con `@pytest.mark.integration`, se salta sin `DATABASE_URL` |
| Web (Vitest + MSW) | Tarjeta, alta con diálogo de una vez, copiar y cerrar, cambio de rol, baja con inventario previo y conflicto 409, reactivación, errores por `code`, fila propia sin acciones | `web/src/screens/Admin/` con ejemplos del contrato |
| Manual | Una vuelta con la API real en simulación (sin publicar): alta, entrar con la contraseña, baja con la sesión abierta en otra pestaña | Equipo del usuario |

Datos: usuarios ficticios (`persona-ficticia-01`), nunca nombres reales; contraseñas generadas por la prueba o placeholders (`TU_CONTRASEÑA`).

## 9. Reparto por áreas y estimación

| Orden | Área | Trabajo | Horas |
|---|---|---|---|
| 0 | Principal | **Requisito previo recomendado:** PA-497 (el MCP comprueba que su usuario existe y está activo) | 2 |
| 1 | Principal | Aprobar RF-52; `UserAdmin` en `adapters/base.py`; `UserExistsError` en `adapters/errors.py`; `ErrorCode` `user_exists` y `last_admin`; rutas y modelos en `api/admin.py` / `api/models.py`; `drop_user` (sesiones, SSE y trabajos) y comprobación por petición en `SessionStore.get` (`api/sessions.py`); contrato `docs/api/openapi.yaml` | 7 |
| 2 | Área A | `LocalAuthProvider` con `UserAdmin` (bloqueo consultivo y último admin); comprobación en `publish` antes de escribir en Jira; migración 0007 (CHECK de `audit_log` con las acciones de usuarios y documentos; `users.updated_at` opcional); `AuditAction` en `core/audit.py`; servicio de baja con los borrados por persona (conversaciones, checkpoints, `last_projects`) | 7 |
| 3 | Área B | Streamlit: comprobar `active` y el rol al usar la sesión (`app/session.py`) | 1 |
| 4 | Sesión UI | Tarjeta «Usuarios y roles», diálogos, cliente y tipos (`web/src/api/`), MSW y pruebas | 6 |
| — | Todas | Revisión, pruebas `integration` y prueba manual | 2 |
| | | **Total** | **≈ 25 h** |

Dependencias: 1 → 2 → 4 (la web puede empezar contra el MSW cuando el contrato esté en 1); 3 en paralelo.

## 10. Preguntas abiertas

| # | Pregunta | Recomendación |
|---|---|---|
| P-01 | ¿Se obliga a cambiar la contraseña en el primer acceso? | No en v1.1 (decidido): contraseña aleatoria de 16 caracteres mostrada una vez; autoservicio en PA-496. `security-reviewer` recomienda subir su prioridad (A-10) |
| P-02 | ¿Se permite que el admin escriba la contraseña en lugar de generarla? | No: siempre generada (evita contraseñas débiles y su paso por formularios) |
| P-03 | ¿Cuánto tiempo se conserva la fila `users` de una baja? | Indefinidamente mientras haya auditoría que la cite; borrado físico solo a petición expresa (fuera de v1.1) |
| P-04 | ¿La comprobación por petición consulta la base de datos siempre? | Sí, una consulta por `username` indexada; si molesta al rendimiento, caché de 10 s invalidada por `drop_user` |
| P-05 | ¿Se notifica a la persona por correo al darla de alta? | No: FAQ no envía correos; el admin entrega la contraseña por un canal seguro |
| P-06 | ¿Se mantiene `core.seed_users`? | Sí, solo para la demo y desarrollo (PA-29 propone limitarlo a `APP_ENV=development`) |
| P-07 | ¿Plazo de conservación de `audit_log`? | Hoy indefinido; fijar uno (p. ej. 2 años) cuando haya datos reales, con seudonimización del `username` de las cuentas de baja al vencer |
