# Requisitos de seguridad para la parte 2 de T-55 (API real)

Salen de la revisión de seguridad de la parte 1 (contrato), con veredicto APTO. Se cumplen antes de exponer la API.

1. **Cookie de sesión:**
   - `afqa_session` con `HttpOnly; Secure; SameSite=Strict; Path=/api`, sin `Domain`. Sin `Secure` solo con un indicador explícito de desarrollo en `core/config.py`.
   - Identificador aleatorio (≥ 128 bits) guardado en el servidor; no un JWT con datos.
   - Se rota al iniciar sesión y se invalida al cerrarla.
   - Caduca por inactividad y por tiempo absoluto.
2. **CSRF:**
   - Token ligado a la sesión y comparado con `hmac.compare_digest`, en todo POST, PUT o DELETE (incluido `logout`).
   - `Origin`/`Referer` validados contra una lista permitida, también en el login.
   - Ningún GET tiene efectos.
3. **CORS:**
   - Mejor el frontend en el mismo origen (proxy).
   - Si hace falta CORS: lista explícita de orígenes, nunca `*` con credenciales. `allow_headers` solo `Content-Type` y `X-CSRF-Token`.
4. **Login:**
   - Límite de intentos por usuario y por IP, con espera progresiva y 429 `too_many_attempts`.
   - El mismo mensaje y un tiempo parecido si el usuario no existe.
   - Nunca se registra la contraseña ni el cuerpo.
5. **Propiedad y permisos:**
   - Cada conversación, revisión y entrega se comprueba contra su dueño o rol, con un 404 idéntico si no existe o no es suya.
   - Permisos por ruta con `core/permissions.py`: `publish_story` para aprobar y el rol QA para `/qa/*`.
6. **SSE:**
   - Exige la cookie y comprueba la propiedad antes de abrir el flujo.
   - Se cierra si la sesión caduca.
   - Límite de conexiones por usuario y heartbeat.
   - Los eventos de error no llevan trazas.
7. **Tamaño:**
   - Límite global del cuerpo (p. ej. 256 KB, con 413 en la forma común).
   - `EditIn.content` se valida con `schemas/` según el tipo de artefacto en revisión.
8. **Errores:**
   - Manejadores para `RequestValidationError` (hecho), `HTTPException` y `Exception` genérica, con la forma común.
   - Solo los mensajes de `adapters/errors.py`, nunca `str(exc)`.
   - `retry_after` acotado.
9. **Escritura en Jira:**
   - La API solo reanuda el grafo con `approve` y la huella; nunca llama a métodos de escritura.
   - `publish_mode` no se cambia desde la API.
   - Pruebas de que `edit`, `iterate`, `discard` y `quality-reviews` no escriben.
10. **QA encadenada:**
    - `take` construye la entrada solo desde la versión aprobada o publicada que conste en el servidor.
    - `handoff` solo desde `approved`, `simulated` o `published` del propio usuario.
11. **Búsqueda:**
    - `search` y `propose` pasan por `core/context` (`keywords`, `any_keyword_jql`): `q` nunca se interpola en JQL.
    - Las claves se limitan a los proyectos visibles.
12. **Selector de modelo:** `PUT /settings/models/{task}` solo acepta pares que estén en la cadena de `config/models.yaml` para esa tarea (D-14).
13. **Logging:**
    - structlog con `user`, `action`, `artifact_id`, `model` y `duration_ms`.
    - Nunca `Cookie`, `X-CSRF-Token`, cuerpos ni prompts.
    - Access log de uvicorn filtrado.
14. **Servidor:**
    - `uvicorn` como dependencia directa.
    - La configuración nueva (orígenes, `Secure`, caducidades, límites) en `core/config.py`; los secretos, como `SecretStr`.
    - `/docs` y `/openapi.json` desactivados fuera de desarrollo.
    - Cabeceras `X-Content-Type-Options`, `Cache-Control: no-store` y CSP en el frontend.
15. **Dependencias:**
    - `fastapi` fijado por debajo de 0.142 (cuarentena de versiones recién publicadas).
    - `uv sync --locked` en CI.
