# Probar `web/` contra la API real

Guía para la sesión principal: levantar el frontend de T-56 en su equipo, con la API de T-55 ya en marcha, y recorrerlo de punta a punta. Es la **única** guía para esta prueba (`API-LOCAL.md` solo enlaza aquí).

> **Reglas:** ni el `.env`, ni las contraseñas de `core.seed_users`, ni tokens se pegan en la PR, el chat o las capturas. `JIRA_PUBLISH_MODE=simulation`: aprobar no escribe nada en Jira. Solo datos sintéticos.

## 1. Requisitos
- **Backend:** `origin/PreProduccion` al día (la web y la API van en la misma rama, así que el contrato coincide), con PostgreSQL, las migraciones, el corpus indexado (`bge-m3` en Ollama) y el modelo de generación que uses. Lo de siempre: `README.md` de la raíz y `docs/api/README.md`.
- **Node.js 22.12 o superior** (`node --version`).
- **Puertos libres:** 8000 (API) y 5173 (Vite).

## 2. Traer la rama
La web está en `PreProduccion` (antes vivía en `area-b`, ya fusionada y retirada). Basta con tu checkout de `PreProduccion` al día:

```powershell
git pull --ff-only origin PreProduccion
```

## 3. Arrancar
Terminal 1, en tu checkout de `PreProduccion`:

```powershell
uv run python -m core.seed_users     # solo si no tienes ya af-demo, qa-demo y admin-demo (cambia sus contraseñas)
uv run python -m api                 # http://127.0.0.1:8000/api/v1, un solo proceso
```

Terminal 2, en el mismo checkout:

```powershell
cd web
npm ci                               # exactamente lo del package-lock.json
npm run dev                          # http://localhost:5173, proxy de /api a 127.0.0.1:8000
```

- Abre **`http://localhost:5173`**, no `127.0.0.1`: la cookie de sesión es `Secure` y sin HTTPS el navegador solo la guarda en `localhost`.
- El proxy va **sin** `changeOrigin` (la API compara `Origin` con `Host`). Si la API está en otro puerto: `$env:API_PROXY_TARGET='http://127.0.0.1:<puerto>'; npm run dev`.
- `npm run dev` **no** usa MSW. Si ves la contraseña `demo` funcionando, estás en `npm run dev:mock`.
- Mejor una ventana de **InPrivate** o un perfil nuevo: un perfil que ya abrió `dev:mock` conserva el Service Worker de MSW y da «Error inesperado».

## 4. Usuarios
`af-demo` (funcional), `qa-demo` (QA) y `admin-demo` (admin), con las contraseñas que mostró `core.seed_users`. El recorrido se hace con **`af-demo`**; los otros dos solo se comprueban por encima.

## 5. Recorrido y lista de comprobación
`<HU>` es una HU del sandbox para evolucionar y `<ÉPICA>` una épica, ambas con datos sintéticos.

**Sesión y marco**
- [ ] Login con `af-demo`; recargar la página mantiene la sesión.
- [ ] Inicio: el proyecto del sandbox, las tarjetas de flujo, «Recientes» y el aviso de simulación.
- [ ] Carril: el anillo con el consumo de hoy (si `/settings/usage` responde 503, no se pinta).

**Evolucionar una HU**
- [ ] Elegir en Jira: épicas, HU y búsqueda del sandbox; elegir `<HU>`.
- [ ] Origen y fuentes: la ficha de la HU, las fuentes del RAG y de Jira con casillas y el presupuesto «Contexto · N de M tokens», que cambia al desmarcar una fuente.
- [ ] Generando: los pasos avanzan con el SSE y la Q se llena por cuartos. Prueba también *Detener*: muestra «Deteniendo…» y termina en `cancelled` con *Reintentar*. Después, *Reintentar*.
- [ ] Iterar: la propuesta (con el texto «Generado con …» de `model_used`), y las pestañas Cambios, Impacto y Fuentes.
- [ ] Iterar: pedir un cambio crea v2; el selector muestra v1, v2 y «Jira».
- [ ] Recibo (*Revisar y aprobar*): las operaciones del plan; *Aprobar y publicar* envía la huella exacta.
- [ ] Resultado simulado: «Modo de prueba activo» y nada escrito en Jira (compruébalo en Jira).
- [ ] Recibo: tras «Actualizar `<HU>`…» va «Añadir a `<HU>` un comentario con los cambios» (viene del plan, PA-319).
- [ ] Si alguna vez se publica de verdad (solo con autorización): *Abrir `<HU>` en Jira* abre la HU con `jira_browse_url` (PA-318); con un vínculo fallido, «Publicada en parte» (PA-324).

**Nueva necesidad**
- [ ] Describir una necesidad con `<ÉPICA>`: el arranque guiado propone «HU nueva en la épica `<ÉPICA>`» o una HU parecida, y si procede avisa de `project_changed` o `ignored_projects`.
- [ ] Generar y aprobar en simulación igual que arriba.

**Retomar y errores**
- [ ] Desde la lista de conversaciones, retomar una en Generando, otra en revisión y otra terminada.
- [ ] En Iterar, *Descartar* → *Sí, descartar*: vuelve a Inicio y nada se escribe en Jira.
- [ ] Reiniciar la API a mitad de sesión: «Sesión caducada» → *Iniciar sesión* → la conversación sigue ahí.

**Otros roles** (solo comprobar que no fallan)
- [ ] `qa-demo`: Inicio con «Preparar pruebas»; el flujo de QA (QA 1 a QA 5) funciona de punta a punta, y *Editar a mano* de la suite sale con el distintivo «Disponible pronto» y su motivo.
- [ ] `admin-demo`: Ajustes (probar conexiones, modelos por tarea y modo de publicación); documentos y usuarios, «Disponible pronto».

**«Disponible pronto» a propósito** (no son fallos): *Editar a mano* de la suite de QA, historial (admin), el registro de auditoría, documentos y usuarios en Ajustes, *Pedir sus pruebas a QA* y *Registrar la ejecución* (QA 6).

## 6. Si algo falla, qué anotar
Un comentario en la PR por fallo, con:
1. **Paso** de la lista, usuario y hora.
2. **Qué esperabas y qué viste** (título de la tarjeta de error y su mensaje).
3. **Petición que falla:** en DevTools → Red, el método y la ruta (sin la query si lleva texto), el estado HTTP y el `code` del cuerpo. En el SSE (`/events`), el último evento recibido.
4. **Consola del navegador** y, si hay, la línea de la consola de Vite (`ECONNREFUSED`, proxy).
5. **Log de la API:** las líneas de esa petición. Ya van sin secretos ni prompts, pero revísalas antes de pegarlas.
6. Una captura, si ayuda, **sin** el `.env`, contraseñas ni datos que no sean sintéticos.

Fallos probables:

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| `ECONNREFUSED` en la consola de Vite | La API no está arrancada, o el destino es `localhost` y resuelve a IPv6 (`::1`) | Arranca la API; deja el destino en `127.0.0.1` |
| 503 en todo | La API no se pudo componer (PostgreSQL caído o `.env` incompleto) | El motivo viene en el 503 y en el log |
| Tras iniciar sesión, vuelve a pedirla | Navegas por `127.0.0.1` y la cookie `Secure` no se guarda | Usa `http://localhost:5173` |
| 403 en los POST | CSRF perdido tras reiniciar la API, o `changeOrigin` activado | Vuelve a iniciar sesión; sin `changeOrigin` |
| «Error inesperado» nada más abrir | Service Worker de MSW de un `dev:mock` anterior | Ventana InPrivate o perfil nuevo |
| `invalid_credentials` | `core.seed_users` se volvió a ejecutar | Usa las últimas contraseñas |
| Origen sin fuentes del RAG | Corpus sin indexar o sin `bge-m3` | `uv run python -m core.rag.indexing` |
| Generando se queda quieta | SSE cortado (proxy, antivirus) o modelo lento en CPU | Espera sin recargar; la pantalla se recupera con `GET /conversations/{id}`. Anota si no avanza |
| `rate_limited` con cuenta atrás | Límites de Groq u OpenRouter | Espera `retry_after`; la cadena pasa al siguiente proveedor |
