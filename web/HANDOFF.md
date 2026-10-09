# Traspaso de T-56 · Frontend React (área B) · 2026-10-08

**Estado:** T-56 ✅ (PR #2 a #17 en `PreProduccion`; este traspaso y PA-412, en la [#18](https://github.com/maujimenez4/agente-af-qa/pull/18), `t56-entrega`), con un pendiente de la principal: la prueba contra la API real del bloqueo por un CA sin caso (ver «Pendiente»).
**Issue de seguimiento:** [#5](https://github.com/maujimenez4/agente-af-qa/issues/5) («T-56 · Frontend React: seguimiento»).
**Siguiente paso del proyecto:** T-57, el punto de control en el que se decide si la demo se hace con React (`web/`) o con Streamlit (`app/`, plan B). El guion está en [DEMO.md](DEMO.md).

**Nombre (PA-478, 2026-10-09):** el asistente se llama **FAQ**; Qaracter es la marca. El nombre está en una sola constante, `src/text/assistant.ts`.

Este documento está pensado para alguien que no ha seguido el proyecto. El detalle de cada pantalla está en [UI.md v2.1](../docs/specs/UI.md) y el porqué de cada decisión, en [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md).

## 1. Qué se entrega
Una web en React (Vite, React 19, TypeScript) con el aspecto del lienzo «Propuesta mixta», que sustituye a Streamlit como interfaz del agente (D-04 revisada). Habla **solo** con la API HTTP de T-55 (`docs/api/openapi.yaml`); nunca con Jira ni con el LLM.

### Pantallas y flujos
| Zona | Quién la ve | Qué hace |
|---|---|---|
| **Inicio de sesión** | todos | Dividido (PA-478): a la izquierda, en azul, el logotipo «FAQ», el mensaje y «un asistente de Qaracter»; a la derecha, el logo de Qaracter y el formulario (*Entrar en FAQ*). Usuario y contraseña contra `POST /auth/login`, con los errores `invalid_credentials` y `too_many_attempts` (cuenta atrás) |
| **Flujo de la HU** (analista funcional) | `functional` (usuario `af-demo`) | Inicio → Elegir en Jira → **Origen y fuentes** (presupuesto de tokens, excluir documentos) → **Generando** (la Q avanza por pasos; *Detener*) → **Iterar** (chat; pestañas Propuesta, Cambios, Impacto y Fuentes; selector de versiones con la versión «Jira»; *Editar a mano*) → **Recibo** (casillas por operación y la huella exacta) → **Resultado** (simulado, publicado o publicado en parte; *Abrir la clave en Jira*, *Ver la memoria*) |
| **Flujo de QA** | `qa` | QA escribe la clave de la HU → QA 1 Origen (tipos de caso) → QA 2 Generando → QA 3 Iterar la suite (Casos, **Cobertura**, Datos y riesgos, Estrategia; *Descargar la matriz*) → QA 4 Recibo (`publish_suite`) → QA 5 Resultado. **Un CA sin caso bloquea la aprobación**; una RN sin caso solo avisa |
| **Revisar la calidad** | `functional` (a `qa` le sale desactivada) | Revisión de solo lectura de una HU de Jira |
| **Memoria** | todos | Lista de memorias por proyecto, con búsqueda, y su detalle por secciones con *Descargar la memoria* |
| **Ajustes · Administración** | `admin` | *Probar conexiones*, los modelos configurados por tarea (solo lectura) y el modo de publicación; Documentos y Usuarios y roles, «disponible pronto» |
| **Piezas comunes** | — | Carril por rol (la Q lleva a Inicio, «FAQ · Inicio») con el anillo de consumo total del día, lista de conversaciones, la Q animada, estados vacío, cargando y error (título por `error.code`) |

Todo se maneja con el teclado, respeta «reducir movimiento» y se ha revisado a 1024, 1280 y 1440 px al 100, 125 y 150 % (axe, WCAG 2.1 A/AA).

## 2. Cómo arrancarlo
Requisito: **Node.js 22.12 o superior**.

### Con la API simulada (sin Python ni Docker)
```bash
cd web
npm ci
npm run dev:mock     # http://localhost:5173
```
- Usuarios `af-demo`, `qa-demo` y `admin-demo`, con la contraseña ficticia `demo` (solo existe en la API simulada, MSW).
- Casos que la pantalla no provoca sola: `?simular=…` en la URL (lista en [README.md](README.md)). Por ejemplo, `?simular=sin-cubrir` enseña el bloqueo por un CA sin caso y `?simular=publicado` simula una publicación correcta (fase 4) sin escribir en ningún Jira.
- Catálogo del sistema de diseño: `http://localhost:5173/?catalogo`.
- Usa un perfil nuevo o InPrivate: un perfil que ya abrió la API simulada conserva su Service Worker y, contra la API real, da «Error inesperado».

### Con la API real
En la raíz del repo, con el backend montado (`README.md` de la raíz y `docs/api/README.md`):
```powershell
uv run python -m core.seed_users   # solo si aún no existen af-demo, qa-demo y admin-demo: genera contraseñas aleatorias, las muestra una sola vez y, si se vuelve a ejecutar, las cambia (`demo` solo sirve en la API simulada)
uv run python -m api               # http://127.0.0.1:8000/api/v1
```
En otra terminal:
```powershell
cd web
npm ci
npm run dev                        # http://localhost:5173, proxy de /api a 127.0.0.1:8000
```
Abre `http://localhost:5173` (no `127.0.0.1`: la cookie de sesión es `Secure`). Recorrido completo y lista de comprobación: [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md).

### Antes de cada cambio
`npm run lint`, `npm test`, `npm run build` y `npm run api:check` sin errores. El build de producción no incluye la API simulada, el catálogo ni `?simular=`.

## 3. Decisiones clave
El detalle, en [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md) y en [UI.md v2.1](../docs/specs/UI.md).
- **Solo el contrato de T-55.** Los tipos se generan desde `docs/api/openapi.yaml` (`npm run api:types`) y `src/api/client.contract.ts` hace fallar `tsc` si el cliente se aparta de una ruta.
- **Aprobación humana:** para aprobar se devuelve exactamente la `fingerprint` de la última revisión; el recibo muestra solo las operaciones del plan que trae la API. Una publicación simulada gasta la aprobación (PA-41): el Resultado lo dice y pide empezar de nuevo desde la misma HU con el modo real (PA-412, versión explícita mientras siga pendiente PA-410).
- **Seguridad en el navegador:** el texto de la API se pinta como texto (nunca HTML); todo enlace pasa por `safeHref`; ESLint prohíbe el almacenamiento del navegador y las URL sin validar; la sesión vive en una cookie HttpOnly.
- **Roles:** cada rol completa su flujo (D-01). El administrador entra en Ajustes y Memoria: configura, pero no genera ni publica; las tarjetas que un rol no puede usar salen desactivadas. QA empieza escribiendo la clave de la HU. Historial, solo para admin (y «disponible pronto»).
- **Cobertura de la suite:** `uncovered: null` es «no se sabe»; un CA sin caso bloquea la aprobación y una RN sin caso solo avisa.
- **Un solo nombre:** «FAQ» sale de `src/text/assistant.ts`. Cambiarlo es cambiar esa línea y el logotipo del inicio de sesión (`FaqLogo`). Los textos de la API (mensajes de error, títulos, pasos de Generando) salen tal cual (PA-478).
- **Sin tiempos ni proveedores inventados:** se muestra el modelo de `Artifact.model_used` y ningún tiempo fijo.
- **Diferencias con el lienzo** (foco accesible, la Q con reducir movimiento, la suite publicada en parte en fase 4…): propuesta para corregir el lienzo en `docs/diseno/CORRECCIONES-LIENZO.md` (PA-304).

## 4. Quién hizo cada parte
- **Área B (responsable de `web/`):** el proyecto `web/` y el sistema de diseño; el flujo de la HU y el de QA (QA 1 a QA 5) con Cobertura; Memoria; *Editar a mano* de la HU; la API simulada; UI.md v2.0 y v2.1; el pulido final (accesibilidad, tamaños, PA-131, PA-342 a PA-344, PA-346, PA-347, PA-412 y PA-435), el guion de la demo y este traspaso.
- **Sesión MCP** (`ses-web`, `ses-web-admin`): la prueba de la web contra la API real de punta a punta (`docs/pruebas/WEB-API-2026-10-05.md`, hallazgos PA-330 a PA-339), Administración (PA-241) y Revisar la calidad.
- **Sesión UI** (`ses-web-fixes` y `ses-web-pulido`): los arreglos PA-332 a PA-336, hallados en la prueba contra la API real, y PA-427 a PA-431 (la Q en Revisar la calidad, extractos con formato, el chat pegado al final, «Generando una nueva versión…» y «Disponible pronto» en Ajustes); en `ses-faq`, el nombre FAQ en la web (PA-478).
- **Sesión Modelos** (`ses-qa-cobertura`): PA-426 en el backend (el bloqueo de la aprobación por un CA sin caso y el reintento dirigido al generar).
- **Principal:** la API y el contrato de T-55, las PA del contrato que pidió la web y las fusiones en `PreProduccion`.

## 5. PA abiertas
| PA | De quién | Estado |
|---|---|---|
| **PA-310** | Área B | Pasar a ESLint 10. Bloqueada: `eslint-plugin-jsx-a11y` 6.10.2 (la última) solo admite hasta ESLint 9 (comprobado el 2026-10-07). Solo afecta al desarrollo; sin vulnerabilidades |
| **PA-304** | Área B | Correcciones del lienzo «Propuesta mixta»: la propuesta está en `docs/diseno/CORRECCIONES-LIENZO.md` (9 correcciones); falta aplicarla en el artefacto del lienzo y volver a copiarlo a `docs/diseno/lienzo/` |
| **PA-130** | Área B | Una revisión de calidad lanzada desde Inicio no se marca como abierta hasta abrirla desde la lista: si la sesión caduca entonces, al volver se va a Inicio (la revisión sigue en la lista). Arreglo: `onCreated(id)` en `QualityScreen` y `setCurrentId` en `WorkZone` |
| **PA-129** | Área B | `src/test/watchdog.ts`: si fallara un `findBy*` de `ReceiptPublishing.pa333.test.tsx`, la prueba se colgaría hasta el límite de Vitest en lugar de fallar a los 3 s |
| **PA-403** | Área B | Decidir si Revisar la calidad ofrece las fuentes con casillas antes de empezar (hoy envía `excluded_sources: []`) |
| **PA-410** | Principal | Volver a revisar y aprobar la misma conversación tras una simulación (hoy da 409 `not_in_review`). Cuando exista, la web cambia la nota del Resultado simulado al literal de PA-412 (ver la nota en la fila de PA-410 del Kanban) |
| **PA-345** | Principal | El ejemplo de `GET /admin/models` usa `task: functional`, que no es un `TaskType`; con la API simulada, Ajustes lo muestra en inglés. Con la API real no pasa |
| **PA-479** | Principal | La firma de FAQ en los comentarios que publica en Jira (backend) |
| **PA-480** | Principal | El nombre FAQ en el servidor MCP (backend) |
| **PA-481** | Área B | El nombre FAQ en Streamlit (`app/`, plan B), si la demo lo usara |
| **PA-340** | Principal | Validar el diseño de *Editar a mano* y decidir si la suite de QA se edita a mano (hoy, fuera de la entrega) |

## 6. Pendiente
1. **La principal** probará contra la API real, tras el cambio de modelo, una suite con un CA sin caso: aviso en Iterar, *Aprobar y publicar* desactivado en el recibo y, si se intenta aprobar, el rechazo en «No se aprobó» con `review.error` («Falta al menos un caso para CA-0N: pídeselo al agente antes de aprobar.»). La web ya lo pinta así con la API simulada (`?simular=sin-cubrir`).
2. **Después**, actualizar la variante B (API real) de [DEMO.md](DEMO.md) para enseñar también ese bloqueo; hoy solo lo enseña la variante A (API simulada).

## 7. Fuera de la entrega
Se ven como «disponible pronto» o no se muestran; el código que ya existe se conserva con sus pruebas.
- **Flujo unido HU → QA** (*Pedir sus pruebas a QA*, «Pendientes de pruebas», *Recoger*): `QA_HANDOFF_ENABLED = false` en `src/app/features.ts`.
- **QA 6**, registrar la ejecución de los casos, y *Reintentar solo los fallidos* (PA-05).
- **Editar la suite de QA a mano** (pendiente de PA-340).
- **Historial y auditoría.**
- **Selector de modelo** por petición (UI.md §11).
- También: Documentos y Usuarios y roles en Ajustes, las citas por CA y RN (PA-315, aplazada), la conversación libre con el LLM (PA-43) y los defectos vinculados (RF-29), estos dos para la v2.

## 8. Reglas para quien siga
- Cada bloque sale de `origin/PreProduccion` en su propia rama y entra con una PR pequeña a `PreProduccion`, con test-writer, spec-checker (CONFORME), security-reviewer (APTO), Vitest completo, lint, build y `api:check` en verde.
- Commits `T-XX: … [RNF-15]`. No se toca `app/` ni, sin avisar en el issue #5, `web/src/api/` o los componentes compartidos.
- En mocks y pruebas, solo datos sintéticos; ningún secreto en `web/`.
