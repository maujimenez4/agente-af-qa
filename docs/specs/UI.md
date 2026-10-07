# UI · «Propuesta mixta» (T-23, T-56)

**Versión:** 2.0 · **Fecha:** 2026-10-06 · **Tareas:** T-23 (diseño), T-56 (frontend en React) · **Trazabilidad:** RNF-15, D-04 (revisada), D-12, PA-44, PA-300
**Diseño de referencia:** lienzo «Rediseño UI del agente AF y QA», página **Propuesta mixta** — https://claude.ai/artifact/PK7Mfx3z357t1x7e2hsSbB (copia en `docs/diseno/lienzo/`)
**Decisión:** «Decisiones del día 6» de `docs/KANBAN.md` (la UI mixta sustituye al modelo de pestañas Contexto/Historia/QA) y D-04 revisada (frontend propio en React).

Este documento describe **qué** muestra cada pantalla, **quién** la ve y **de qué depende**. La implementación es el frontend en **React** de `web/` (T-56), que habla con el backend **solo a través de la API HTTP** de T-55 (`docs/api/openapi.yaml`, `docs/api/README.md`). Las decisiones de detalle (medidas, textos, accesibilidad, casos límite) están en `web/DESIGN-DECISIONS.md`; cuando el lienzo y este documento no coinciden, manda este documento. Lo que aún no existe se marca con su tarea o su propuesta (PA-XX).

**Estado en la web** (2026-10-06): hechas y fusionadas el inicio de sesión, Inicio, Elegir en Jira, Origen, Generando, Iterar, el recibo y el Resultado de la HU, el flujo de QA (QA 1 a QA 5), Revisar la calidad, Memoria y Administración. **Pendientes:** *Editar a mano* (§4.5 bis; conectado para la HU en `t56-editar`, diseño pendiente de validar en PA-340) y lo que §11 deja fuera de la entrega. Los arreglos de la prueba contra la API están fusionados (PA-332 a PA-334 y PA-336); PA-335 (ventanas estrechas) llega con la PR #11.

---

## 1. Principios de la interfaz

1. **Asistente conversacional por fuera, arranque guiado por dentro.** El usuario elige el flujo (tarjetas) y el origen (selector de Jira o clave escrita). El modelo **no** hace preguntas para recoger datos (eso queda para v2, PA-43).
2. **La operación queda fijada antes de generar** y no cambia durante la conversación: es lo único que se podrá aprobar y publicar (`core/approvals.py`, el destino no cambia entre iteraciones).
3. **Las fuentes se pueden desmarcar** antes de generar.
4. **La conversación sirve para iterar** la propuesta (RF-20).
5. **Nada se escribe en Jira sin aprobación humana**: recibo con una casilla por operación y huella de la versión revisada (§5).
6. **El resultado distingue publicación simulada y real** (`publish_mode` de `GET /settings`, T-25).
7. **Textos en español.** El mensaje de un error es el de la API (`ErrorBody.message`), **tal cual y como texto**; la web solo elige el título, el tono y la acción según `ErrorBody.code` (§7).
8. **Todo lo que llega de la API** (texto de Jira, del RAG y del LLM) se pinta **como texto**, nunca como HTML. Los `.md` (matriz, memoria, informe) solo se descargan.
9. **Datos de ejemplo ficticios** (proyecto `DEMO`, usuarios `af-demo`, `qa-demo`, `admin-demo`).

## 2. Marco común

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Carril lateral (88 px) | Logotipo Q; zonas **Trabajo** (analista y QA), **Memoria** (los tres roles), **Historial** (admin, «disponible pronto», PA-302) y **Ajustes** (admin); anillo de consumo de tokens de hoy de **toda la instalación** («24 %» · «instalación»); usuario y *Cerrar sesión* | Cambiar de zona | Permisos (§3) · `GET /settings/usage` (PA-305) |
| Lista de conversaciones (248 px) | «Nueva conversación», buscador local (sin mayúsculas ni tildes), conversaciones agrupadas por día («Hoy», «Ayer», fecha) con clave de proyecto, título y «flujo · estado» («Versión 2», «Simulado», «Publicado», «En curso», «Aprobada», «Descartada»); se desplaza dentro de su columna | Retomar una conversación | `GET /conversations` (T-52) |
| Cabecera (64 px) | Título de la conversación, **Q de fase** («Fase N de 4 · Contexto / Generar / Revisión / Publicado») y *Ocultar el panel* / *Mostrar el panel* | Plegar el panel derecho | Estado de la conversación (`ConversationOut.state`) |
| Compositor | Cuadro de texto con ayuda según el flujo, «Elegir en Jira», selector de modelo **en solo lectura** («Modelo automático») y enviar. **Intro envía**, Mayús+Intro hace un salto de línea; mientras genera, el botón de enviar pasa a *Detener* | Enviar | Elegir modelo por petición (RF-42) queda fuera de la entrega |
| Aviso de modo de prueba | En Inicio: «Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.» En el Resultado (HU y QA), solo tras una simulación: «Modo de prueba activo: el agente no escribe en Jira. Lo cambia el administrador.» | — | `publish_mode = simulation` |
| Panel derecho | «Antes de generar» (420 px), propuesta o informe (480 px), suite de QA (540 px). Plegado, se oculta sin perder su estado | — | — |

Las cuatro fases de la Q son: **1 Contexto** (origen y fuentes) · **2 Generar** (generar e iterar) · **3 Revisión** (recibo, aprobada) · **4 Publicado**.

**Ventanas estrechas (PA-335).** Con menos de 1024 px CSS útiles (el escalado habitual de Windows: 1024 al 125 %, y 1280 y 1440 al 150 %), no hay barra horizontal ni controles cortados:
- La **lista de conversaciones** se pliega en una franja de 48 px con el botón «Conversaciones» (solo icono, con su nombre accesible y su tooltip) y se abre como capa junto a ella.
- Si el área de trabajo mide menos de 680 px (p. ej. 1024 al 150 %), el **panel derecho** se abre como capa sobre la conversación, con *Mostrar el panel* y un botón *Cerrar* (×) en su cabecera.
- Las dos capas se comportan como un diálogo: el foco entra al abrirlas y vuelve al botón al cerrarlas; se cierran con Esc, con un clic fuera o si el foco sale de ellas (así nunca quedan dos abiertas); Tab no sale de ellas. Los botones llevan `aria-expanded`.
- Un título recortado con «…» se ve completo al pasar el ratón.
- Por encima de 1024 px, nada cambia.

### 2.1 Inicio de sesión (PA-311)
Pantalla mínima con las piezas del sistema (no está en el lienzo; se mantiene por decisión de la principal).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Formulario | Usuario y contraseña | *Iniciar sesión* | `POST /auth/login` (cookie HttpOnly y `csrf_token` solo en memoria) |
| Errores | `invalid_credentials` («No se pudo iniciar sesión»); `too_many_attempts` con la cuenta atrás de `retry_after` | Reintentar | — |
| Al recargar | La sesión se recupera sin volver a entrar | — | `GET /auth/me` |

## 3. Roles y visibilidad

Según `core/permissions.py` (`ROLE_PERMISSIONS`), que la API aplica en cada ruta:

| Función de la UI | Permiso | `functional` (analista) | `qa` | `admin` |
|---|---|---|---|---|
| Nueva necesidad, Evolucionar HU | `GENERATE_STORY` | ✅ | ⛔ desactivada | — |
| Revisar la calidad | `GENERATE_STORY` (no publica) | ✅ | ⛔ desactivada | — |
| Aprobar y publicar HU | `PUBLISH_STORY` | ✅ | — | — |
| Preparar pruebas | `GENERATE_TESTS` | ⛔ desactivada | ✅ | — |
| Aprobar y publicar suite | `PUBLISH_TESTS` | — | ✅ | — |
| Memoria | `VIEW_MEMORY` | ✅ | ✅ | ✅ |
| Ajustes (Administración, §10) | `MANAGE_*` | — | — | ✅ |
| Historial | PA-62 | — | — | «disponible pronto» |

- **Tarjetas que el rol no puede usar:** se muestran **desactivadas** (`aria-disabled`) con la ayuda «Disponible para el rol de analista funcional.» o «Disponible para el rol QA.». El rol QA ve la tarjeta «Preparar pruebas» seleccionada por defecto.
- **El administrador** configura pero no genera ni publica (D-01): entra en Ajustes, ve Memoria e Historial y no ve las tarjetas de flujo.
- Una ruta sin permiso responde 403 `forbidden` («No tienes permiso para realizar esta acción.»), que la web muestra con su tarjeta.

## 4. Flujo de HU (analista funcional)

### 4.1 Mixta 1 · Inicio
Pantalla central «¿En qué trabajamos hoy?» con la Q, el subtítulo «Elige qué hacemos y de qué partimos. Después lo mejoramos conversando. Nada se publica en Jira sin tu aprobación.»

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Tarjetas de flujo (rejilla 2×2) | **Nueva necesidad**, **Evolucionar una HU**, **Revisar la calidad de una HU** (analista) y **Preparar pruebas** (QA) | Elegir flujo (`aria-pressed`) | Permisos (§3) |
| Compositor | Texto de ayuda según el flujo (p. ej. «Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.») | Escribir necesidad o clave | `POST /start/propose` (T-53) |
| Selector de proyecto | Clave y nombre del proyecto; todos los que ve la conexión, con el último usado preseleccionado | Cambiar de proyecto (abre Mixta 1b) | `GET /projects`, `POST /projects/choose` (T-50) |
| «Elegir en Jira» | Botón | Abre Mixta 1b | — |
| Recientes del proyecto | Chips con clave y título (HU y épicas) | Fijar ese origen | `GET /projects/{project}/search` |
| Lista de conversaciones | Ver §2 | Retomar | `GET /conversations` |
| Aviso de modo de prueba | Ver §2 | — | `GET /settings` |

Una clave de otro proyecto escrita en el texto cambia el proyecto de la conversación sola; el aviso se da en Origen (T-50, T-53, PA-313).

### 4.2 Mixta 1b · Elegir en Jira
Diálogo modal (`role="dialog"`).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Buscador | «Buscar por texto o clave en el proyecto DEMO» (espera 300 ms entre pulsaciones) | Filtrar | `GET /projects/{project}/search` |
| Columna Proyectos | «Proyectos que ve la conexión (N)» | Elegir proyecto | `GET /projects` |
| Columna Épicas | «Épicas de DEMO (N)»; nota «Elegir la épica sirve para crear una HU nueva dentro de ella.» | Elegir épica | `GET /projects/{project}/epics` |
| Columna HU | «HU de DEMO-1 (N)» | Elegir HU | `GET /epics/{key}/stories` |
| Pie | «Seleccionada: DEMO-3 · …» · *Cancelar* · *Usar la épica DEMO-1* · *Usar DEMO-3* · **Usar el proyecto X** (si solo se cambia de proyecto) | Fijar el origen o el proyecto | — |

### 4.3 Mixta 2 · Origen fijado
Fase 1 de 4. Conversación a la izquierda y panel «Antes de generar» a la derecha.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Mensaje del usuario | La necesidad escrita | — | — |
| HU parecida | Etiqueta «Búsqueda en Jira por texto · sin IA»; tarjeta con la HU encontrada (clave, épica, nº de CA y RN) | *Evolucionar DEMO-3* · *Crear HU nueva* · «HU nueva en la épica DEMO-1» | `POST /start/propose` (T-53), `GET /issues/{key}` |
| Tarjeta «Operación fijada» | «Operación fijada: evolucionar DEMO-3. No cambia durante la conversación; es lo único que se podrá aprobar y publicar.» | — | `PublishTarget` |
| Aviso de proyecto | Si la clave es de otro proyecto (`project_changed`) o hay claves de otros proyectos que no se usan (`ignored_projects`) | — | T-53, PA-313 |
| Panel · Operación | Operación y origen; «Se puede cambiar solo antes de generar.» | *Cambiar* (vuelve a Inicio) | — |
| Panel · Restricciones | Texto opcional | Escribir | Necesidad nueva: se añaden al texto del origen. Evolucionar: van como primer `feedback` |
| Panel · Fuentes | Lista con **casillas**: título, `DOC-NN` o clave y categoría; la de origen es obligatoria; una fuente desmarcada indica «No influirá en la propuesta»; la memoria aparece como «prioritaria» | Marcar / desmarcar | `POST /start/sources` (`excluded_sources`, T-51) |
| Panel · Presupuesto | «Contexto · 2.350 de 6.000 tokens» con barra; aviso desde el 90 % o si hay fuentes que no caben. Al marcar o desmarcar, estimación al instante («Contexto · ≈ 2.350 de 6.000 tokens · estimación», barra más clara) hasta la confirmación, que es la que cuenta; si la cambia, «Al quitar un documento puede entrar otro relacionado en su lugar: la cifra confirmada es la que cuenta.». En una necesidad nueva, lo que ocupa su texto aparte («… del total de 6.300»). Al lector de pantalla solo llega lo confirmado | — | `budget` de `POST /start/sources` (PA-102); `sources[].tokens`, `budget.fixed` y `budget.total` (PA-330) |
| Panel · Pie | *Generar propuesta* · «Una llamada al modelo. Después itera conversando.» | `POST /conversations` (202) | — |

### 4.4 Mixta 2b · Generando
Fase 2 de 4. La **Q de carga** avanza con los pasos (§8).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Lista de procesos | Los pasos que manda la API, **con su etiqueta tal cual** (PA-307, PA-327); la web no da por hecho cuántos son | — | Eventos `progress` del SSE (`GET /conversations/{id}/events`) |
| Titular | «Generando la propuesta…» → «Propuesta lista · Versión 1 · N cambios frente a Jira» | *Ver la propuesta* | `review_ready` |
| *Detener* | En el compositor; «Deteniendo la generación…» mientras termina el paso en curso. Acaba en «Generación detenida» (*Reintentar*) o en la propuesta | `POST /cancel` (PA-314) | — |
| Error | Tarjeta según `code`; *Reintentar* repite el paso que falló | `POST /retry` (PA-276) | — |
| Compositor | Desactivado: «Espera a la propuesta para pedir cambios» | — | — |

Si el SSE se corta sin evento final, la web consulta `GET /conversations/{id}` hasta que deja de generar.

### 4.5 Mixta 3 · Iterar
Fase 2 de 4. Conversación + panel de la propuesta.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Resumen del asistente | Compuesto en la web, sin LLM: «Versión 2 lista. CA-02: … Afecta también a DEMO-2 (…)» y, si las hay, «Quedan N preguntas abiertas» | — | `changes_from_previous`, `impact`, `open_questions` |
| Mensaje de cambio | El usuario pide un cambio (RF-20) | Enviar | `POST /iterate` (202) |
| Indicador | **«Escribiendo la respuesta»** con la Q animada; la respuesta se escribe letra a letra | — | SSE |
| Aviso de modelo usado | «Generado con local · qwen3:4b-instruct · 2 fuentes» | — | `Artifact.model_used`. El motivo de un cambio de proveedor no lo expone el backend (PA-67) |
| Sugerencias | Chips: «Añade un criterio de error», «Aclara el alcance», «Revisa INVEST» | Rellenar el compositor | — |
| Panel · Versiones | *Jira* (solo al evolucionar) · *v1* · *v2* … | Ver una versión | `ConversationOut.versions`, `jira_baseline` (PA-316) |
| Panel · Pestañas | **Propuesta** · **Cambios (N)** · **Impacto (N)** · **Fuentes (N)**; en una HU nueva, *Cambios* va sin recuento | Cambiar de pestaña | `UserStory`, `impact.diffs` (acumulados frente a Jira; los CA y RN se nombran `acceptance_criteria[CA-02]`, como en la API real y en el ejemplo del contrato, y la web acepta también `acceptance_criteria.CA-02`, PA-341), `impact.affected` |
| Propuesta | «Como / quiero / para», CA y RN; marcas «Cambiado en vN» / «Nueva» frente a la versión anterior (en la v1, frente a Jira) | — | — |
| Pie del panel | *Editar a mano* (§4.5 bis) · *Descartar* (con confirmación) · *Revisar y aprobar* | Editar / descartar / abrir el recibo | `POST /discard` · §4.6 |

El aviso «CA sin fuente» (*Confirmar* · *Pedir fuente*) del lienzo queda aplazado: los CA no traen una cita propia (PA-315).

### 4.5 bis Editar a mano (RF-32) · diseño pendiente de validar (PA-340)
El lienzo solo tiene el botón. **Diseño propuesto**, pendiente de validar por la principal (PA-340); en la web ya está conectado para la HU (parte B, rama `t56-editar`). En QA, *Editar a mano* sigue «disponible pronto».

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Panel derecho | El editor de la HU **en lugar de la pestaña Propuesta** (540 px): Historia (título, «Como / Quiero / Para», descripción, objetivo, prioridad), Criterios de aceptación (título y «Dado / Cuando / Entonces», una línea por paso; *Subir*, *Bajar*, *Quitar*, *Añadir un criterio*), Reglas de negocio y «Más campos» plegado (alcance, supuestos, restricciones, dependencias…). La clave de Jira, las fuentes y los cambios frente a la anterior no se editan | Editar | — |
| Rechazo | Arriba, «No se guardó la edición.» y el motivo de la API tal cual | — | `review.error` |
| Pie | Lo que falta antes de guardar, los avisos (no impiden guardar), nota opcional (como mucho 1.000 caracteres; con menos de 1024 px útiles, plegada tras «Añadir una nota» si está vacía), *Cancelar* (con cambios, pide confirmación) y *Guardar la versión N+1* | `POST /conversations/{id}/edit` | Contrato §5 |
| Mientras se edita | El foco va al primer campo; el compositor queda desactivado («Guarda o cancela la edición para pedir cambios»). Con el panel en capa (PA-335), Esc, el velo y *Cerrar* piden «¿Descartar los cambios?» si hay cambios sin guardar | — | — |
| Tras guardar | El panel vuelve a la propuesta con la versión nueva; en la conversación, «Versión N guardada: editada a mano, sin llamar al modelo», «Editada a mano · N fuentes» y, si la hay, «Nota de la edición: …»; la lista pasa a «Versión N»; en el historial del recibo, «Versión N editada a mano» | — | `VersionOut.edited` |

**El backend decide:** *Guardar* solo se bloquea con lo que la API rechaza seguro (título vacío, ningún CA, identificadores mal formados o repetidos, CA sin título o sin pasos, RN sin descripción, sin cambios, nota de más de 1.000 caracteres); lo demás es un aviso. **Editar la suite de QA** a mano queda fuera por ahora (pregunta abierta en PA-340).

### 4.6 Recibo de aprobación
Fase 3 de 4. Es la **revisión humana** (contrato §5).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Versión N lista para revisar» | — | `review.version` |
| «Qué se hará en Jira» | **Una casilla por operación del plan**, sin deducir ninguna: «Actualizar DEMO-3 con la versión 3» (con los campos que cambian), «Crear la HU en la épica DEMO-1», «Añadir a DEMO-3 un comentario con los cambios» (solo cuando el plan trae la operación `comment`, PA-319), «Vincular DEMO-3 con DEMO-2» (con el motivo); contador «N de M revisadas» → «Todo revisado» | Marcar cada operación | `review.plan` (T-51), `review.impact` |
| Aviso | «Generado con IA a partir de N fuentes. Revisa cada operación antes de aprobar.» | — | — |
| Botones | *Descartar* (con confirmación) · **Volver a la propuesta** (vuelve a Iterar, donde se pide el cambio) · **Aprobar y publicar** (activo solo con todas las casillas marcadas) | `POST /discard` · Iterar · `POST /approve` | Contrato §5 |
| Historial de la HU | Versiones con modelo, versión del prompt (`prompt_version`, nunca su texto) y hora, y la de partida desde Jira | — | `ConversationOut.versions` |

Aprobar responde 202; la publicación sigue por el SSE («Aprobando y publicando…», sin *Detener*). Una huella que no casa vuelve al recibo con «No se aprobó» y el motivo; las casillas se vacían.

### 4.7 Mixta 4 · Resultado

| Modo | Fase | Contenido | Acción | Dependencia |
|---|---|---|---|---|
| Simulación | 3 de 4 · Aprobada (la Q no se llena: no se ha escrito nada en Jira) | Distintivo «Aprobada · simulada»; «Publicación simulada · No se ha escrito nada en Jira. Esto es lo que se habría hecho, y queda en la auditoría:» + operaciones numeradas; nota «La aprobación sigue vigente…» y aviso «Modo de prueba activo…» (§2) | *Ver el registro de auditoría* e *Ir al historial* («disponible pronto») | `result.simulated` (T-25); caducidad de la aprobación PA-41 |
| Real | 4 de 4 · Publicado | «Publicado en Jira · Estas operaciones ya están en Jira:» + operaciones con ✓ y las claves publicadas; «La memoria de la HU se ha generado e indexado; tendrá prioridad en las próximas propuestas.» | *Abrir DEMO-3 en Jira* · **Ver la memoria** (abre Memoria con esa clave, §4.9) · *Pedir sus pruebas a QA* («disponible pronto», §11) | `result.published_keys`, `jira_browse_url` (PA-318) |
| En parte | 4 de 4 · Publicada en parte | Las operaciones aprobadas, numeradas y sin ✓, y «Lo que no se pudo publicar» con los mensajes de la API. No es un error HTTP (RNF-13) | *Abrir DEMO-3 en Jira* · *Ver la memoria* · *Pedir sus pruebas a QA* («disponible pronto») | `result.errors` (estado `published`, PA-324) |
| Todos | — | «Versión 2 aprobada por af-demo a las 15:47» | — | — |

*Reintentar solo los fallidos* es PA-05 (fuera de alcance). La memoria puede quedar sin indexar (`MemoryOut.indexed = false`) aunque el texto diga «indexado»: nota para la principal en PA-329.

### 4.8 Mixta 5 · Revisar la calidad
Flujo propio, **solo lectura: no publica** (decisión del día 6). Pantalla propia tras Inicio, **sin el panel «Antes de generar», sin restricciones ni compositor**; las preguntas sobre el informe siguen en PA-101.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Elegir la HU | «Reviso la HU con INVEST y contra las fuentes, y te doy un informe. No cambio nada en Jira.» y una tarjeta por HU que se puede revisar: la elegida en Jira o, si no, las claves reconocidas y, sin ninguna, las parecidas (las épicas no se revisan). Sin ninguna, «No encuentro esa HU…» | *Revisar DEMO-4* (no se lanza el modelo sin confirmar) · *Volver al inicio* | `POST /start/propose` · `POST /quality-reviews` (202, `running`; `excluded_sources: []`, PA-403) |
| Cabecera | «Calidad de DEMO-4» con «Revisar la calidad · solo lectura», **sin la Q de fases** | — | — |
| En curso | «Revisando la calidad de DEMO-4…» y «Son dos llamadas al modelo: con el modelo local puede tardar unos minutos. No se escribe nada en Jira.» Sin pasos: la API no da el avance (PA-402) | — | `GET /quality-reviews/{id}` hasta `done` o `error` (sin SSE): cada 2 s los dos primeros minutos y después cada 10 s; tope de 30 min desde `created_at` (o desde que se abrió la pantalla): al pasarlo, tarjeta con *Volver a consultar* y *Revisar de nuevo* (PA-406) |
| Error | La tarjeta de `quality_failed` (u otro `code`) con el mensaje tal cual y «Nada se ha escrito en Jira.» | *Reintentar* (empieza otra revisión) | `QualityReviewOut.error` |
| Conversación | «He revisado DEMO-4 con INVEST y contra las fuentes.», el resumen del informe y «Hay 3 puntos a mejorar. No he cambiado nada en Jira.»; tarjeta «Informe de calidad de DEMO-4 · En el panel» | — | `report.summary` |
| Panel «Informe de calidad» (480 px) | Bajo el título, un **resumen contado sin IA** a partir del veredicto («INVEST: 5 de 6 bien · 1 ambigüedad · 1 hueco», sin puntuaciones). Secciones: **INVEST** (las seis letras con su nombre y «Bien» / «Mejorable», en dos filas de tres), **Hallazgos** (tipo —Ambigüedad, Hueco, Sin fuente, INVEST, Incoherencia con las fuentes— con el CA o la RN afectados, explicación y propuesta; sin ninguno, «No hay hallazgos.»), **Preguntas para negocio** y **Fuentes**. Todo como texto | — | `report` (campo a campo) |
| Pie del panel | *Descargar informe* (`calidad-DEMO-4.md`, solo para descargar) · *Evolucionar DEMO-4 con esto* (si hay mejoras); «Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas mejoras como punto de partida.» | Descargar · conversación nueva de evolución | `report_markdown` · `evolve_feedback` (el proyecto se deduce de la clave, PA-405) |
| Lista de conversaciones | La revisión aparece junto a las conversaciones, por `updated_at`: «Revisar la calidad · Revisando / Informe listo / Con error»; al retomarla se abre esta pantalla | Retomar | `GET /quality-reviews` (PA-103, PA-272) |

**Diferencias con el lienzo** (PA-404): el paso previo para elegir la HU, la cabecera sin la Q de fases, INVEST en dos filas de tres (en una no caben los nombres en 480 px), las secciones «Preguntas para negocio» y «Fuentes», el resumen sin IA y la pantalla sin compositor ni chips.

### 4.9 Memoria (PA-329)
Zona propia del carril para los tres roles (diseño validado por la principal el 2026-10-06). Solo lectura: no llama al LLM ni escribe nada.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Columna de la lista (248 px) | Título «Memoria», selector de proyecto («Todos los proyectos» y los de la conexión), buscador (espera 300 ms) y la lista, pedida con `limit=200` de una vez (sin «Mostrar más») y desplazable dentro de su columna. Cada fila: clave, «vN», punto «Indexada» / «No indexada», título y «DEMO · 2 oct» | Elegir una memoria | `GET /memories?project=&q=&limit=` |
| Lista vacía | «Aún no hay memorias. Se generan al publicar una HU en Jira (modo real).»; con filtros, «Ninguna memoria coincide con el proyecto o la búsqueda.» | — | — |
| Detalle | «DEMO-9001 · Memoria v2», «Proyecto DEMO · Actualizada el 2 de octubre de 2026», distintivo «Indexada» / «No indexada» con su explicación, *Descargar la memoria* (`memoria-DEMO-9001.md`) y las secciones como texto, en el orden del `.md`: objetivo, alcance, reglas de negocio, decisiones, dependencias, cambios, criterios de aceptación y referencias | Descargar | `GET /memories/{key}` (`memory` campo a campo; `markdown` solo para descargar) |
| Error | Tarjeta según `code`; una memoria que no existe da «No se encuentra» sin romper la pantalla | Reintentar | 404 `not_found` |

Mientras se mira Memoria, la conversación de Trabajo sigue donde estaba.

## 5. Contrato de aprobación

La web no habla con el grafo: usa las rutas de la API, que traducen a las decisiones de `human_review` (SPEC-00 anexo §11, T-51).

1. Una conversación en revisión trae `review` con `{artifact, version, target, fingerprint, impact, plan, decisions, error}`.
2. El recibo (§4.6 / §6.4) pinta **una casilla por operación de `plan`** y nada más.
3. Acciones:
   - Aprobar: `POST /conversations/{id}/approve` con `{"fingerprint": <la huella recibida>}` (202).
   - Iterar: `POST /conversations/{id}/iterate` con `{"feedback": "<texto>"}` (202).
   - Descartar: `POST /conversations/{id}/discard`.
   - Editar a mano: `POST /conversations/{id}/edit` con `{"content": <contenido completo editado>, "fingerprint": <la huella recibida>, "feedback": <nota opcional>}` (200). Crea la versión siguiente sin llamar al modelo, con huella nueva; `jira_key`, `internal_id` y `story_jira_key` no se pueden cambiar.
   - **Respuesta rechazada** (huella que no casa, edición inválida o sin cambios): no es un error HTTP; la revisión sigue con `review.error` y el motivo en español, que la UI muestra junto al recibo o al editor. Tras 20 rechazos en la misma revisión, 409: hay que empezar una conversación nueva.
   - **409** se distingue por `error.code`: `approval_rejected` → *Empezar de nuevo*; `not_in_review` → *Actualizar* el estado.
4. La UI no guarda ni reconstruye la huella: envía exactamente la del último `review`. Si la persona itera o edita, la huella anterior deja de valer.
5. *Aprobar y publicar* solo se activa con todas las casillas del recibo marcadas; es una ayuda visual: la garantía la da la huella.
6. Tras publicar, la aprobación se consume (un solo uso). En simulación sigue vigente (T-25); su caducidad antes de activar `live` es PA-41.
7. **Toda escritura en Jira pasa por el nodo `publish`** con aprobación vigente. La web nunca habla con Jira ni con el LLM: solo con la API.

## 6. Flujo de QA (rol QA)

Se entra por **Preparar pruebas** en Inicio **escribiendo la clave de la HU**: se parte siempre de una HU existente. El flujo unido HU → QA (recoger HU pasadas por el analista) queda fuera de la entrega (§11).

### 6.1 QA 1 · HU de origen, tipos de caso y fuentes
Fase 1 de 4. Cabecera «Pruebas de DEMO-3».

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Clave reconocida | «Clave reconocida en Jira · sin IA»; tarjeta con la HU (épica, «1 criterio y 1 regla», casos de prueba que ya tiene en Jira, «publicada por el agente») | *Preparar pruebas de DEMO-3* | `POST /start/propose`, `GET /issues/{key}` (`test_cases`, `published_by_agent`, PA-104) |
| Operación fijada | «Operación fijada: suite de pruebas de DEMO-3. Los casos serán subtareas de DEMO-3 con la etiqueta «caso-prueba»; la estrategia y la matriz, adjuntos.» | — | `PublishTarget` (D-09) |
| Panel · Tipos de caso (RF-22) | Casillas Positivos y Negativos («· obligatorio», no se pueden quitar), Alternos y De excepción | Marcar | Primer `feedback` «Incluye casos: …» |
| Panel · Incluir además | Plegado con su resumen («3 de 3 incluidos»): datos sintéticos (RF-25), riesgos, dependencias e impacto (RF-27) y estrategia de pruebas (RF-26) | Marcar | «Incluye además: …» en el `feedback` |
| Panel · Fuentes y presupuesto | Como en §4.3 (la HU de origen, obligatoria) | Marcar / desmarcar | `POST /start/sources` |
| Pie | *Generar la suite* | `POST /conversations` con `flow: tests` | — |

### 6.2 QA 2 · Generando
Fase 2 de 4. Mismo patrón que Mixta 2b, con **cuatro pasos** y sus etiquetas de QA (sin «Guardar la memoria»: en QA no se guarda memoria, D-07; PA-327).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Lista de procesos | «Recuperar la HU de origen», «Recuperar el contexto (Jira, documentos y memoria)», «Generar casos y escenarios, validar la cobertura y preparar datos, riesgos y estrategia» y «Publicar (o simular la publicación de) los casos de prueba en Jira», tal como los manda la API | — | `progress` del SSE |
| Titular | «Generando la suite…» → «Suite lista · Versión 1 · 4 casos» | *Ver la suite* | — |
| Compositor | Desactivado: «Espera a la suite para pedir cambios» | — | — |
| Error | `coverage_failed` → «La suite no es válida» · *Volver a generar* | `POST /retry` | — |

### 6.3 QA 3 · Iterar la suite
Panel «Suite de pruebas» (540 px).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Conversación | Resumen sin LLM («Suite lista: 4 casos y todos los CA cubiertos. Riesgo: …»), peticiones de cambio, «Escribiendo la respuesta», sugerencias | `POST /iterate` | RF-20 (que la v2 aplique el cambio pedido es PA-331) |
| Panel · Estado | Versiones *v1*, *v2*; distintivo de cobertura (abajo) | — | `ReviewPayload.uncovered` (PA-326) |
| Pestaña **Casos** | Por caso: id, título, tipo, prioridad, «Verifica CA-01, RN-01», precondiciones, pasos, marca «Nuevo en v2» y su **Gherkin** desplegable | — | `TestSuite` (RF-23) |
| Pestaña **Cobertura** | Matriz CA/RN × CP (RF-24) «se adjunta como matriz-DEMO-3.md» y *Descargar la matriz* (si la API trae `coverage_md`) | Descargar | `coverage_md`, `uncovered` (PA-326) |
| Pestaña **Datos y riesgos** | Tabla de datos sintéticos (identificadores ficticios, RF-25) y riesgos, dependencias y áreas de impacto (RF-27) | — | `TestSuite` |
| Pestaña **Estrategia** | = plan de pruebas (decisión del día 6): alcance, niveles, entornos, criterios de entrada y salida, prioridad; «se adjunta como estrategia-DEMO-3.md». Se muestra como texto (títulos y puntos); el formato de negritas y listas es PA-334 | — | `strategy_md` (RF-26) |
| Pie | *Editar a mano* («disponible pronto»; editar la suite queda fuera por ahora, PA-340) · *Descartar* · *Revisar y aprobar* | — | §6.4 |

**Cobertura** (`uncovered`, PA-326); `null` y listas vacías **no se tratan igual**:
- **Listas vacías** («todo cubierto»): distintivo «Todos los CA cubiertos» y «Cada CA y cada RN de la HU tiene al menos un caso.».
- **Con elementos:** distintivo «1 CA y 1 RN sin caso», el aviso «Sin ningún caso: CA-03, RN-03.» y una fila «· Sin caso» por cada uno en la matriz.
- **`null` o sin el campo** («no se sabe»): sin distintivo ni ninguna afirmación de cobertura completa; nota «No se ha podido comprobar qué CA y RN de la HU quedan sin caso…».
- **Una RN sin caso se avisa pero no bloquea la aprobación** (decisión de la principal, 2026-10-06, por el riesgo con el modelo local): la API solo exige un caso por CA (`coverage_failed`).

### 6.4 QA 4 · Recibo
Fase 3 de 4. Mismo patrón que §4.6. Cabecera «Pruebas de DEMO-3 · Suite, versión N lista para revisar».

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| «Qué se hará en Jira» | **Una casilla**, porque el plan trae una sola operación: «Crear N subtareas en DEMO-3 con la etiqueta «caso-prueba»», con el detalle de que adjunta `estrategia-DEMO-3.md` y `matriz-DEMO-3.md`; contador «0 de 1 revisada» → «Todo revisado» | Marcar | `publish_suite` en `review.plan` · `JiraNativeTests` (T-30, D-09) |
| Aviso | «Generado con IA a partir de la HU y N fuentes. Revisa cada operación antes de aprobar. Si una subtarea falla, las demás se mantienen.» | — | RNF-13 |
| Botones | *Descartar* · *Volver a la suite* · **Aprobar y publicar** | `POST /discard` · Iterar · `POST /approve` | Contrato §5 |
| Historial de la suite | Versiones con «N casos · cobertura validada» (o los CA y RN sin caso, o solo los casos si no se sabe), modelo, `prompt_version` y hora | — | `ConversationOut.versions` |

### 6.5 QA 5 · Resultado

| Modo | Fase | Contenido | Acción | Dependencia |
|---|---|---|---|---|
| Simulación | 3 de 4 · Aprobada | «Publicación simulada · No se ha escrito nada en Jira. Esto es lo que se habría hecho, y queda en la auditoría:»; «La aprobación sigue vigente para publicar cuando se active el modo real.» y el aviso «Modo de prueba activo…» (§2) | *Ver el registro de auditoría* («disponible pronto») | T-25 |
| Real | 4 de 4 · Publicado | «Suite publicada en Jira» con las subtareas en «Claves en Jira» | *Abrir DEMO-3 en Jira* · *Registrar la ejecución* (§6.6) | `result.published_keys` |
| En parte | **4 de 4 · Publicada en parte** (igual que la HU; el lienzo dice fase 3, PA-304) | Las operaciones aprobadas y «Lo que no se pudo publicar» con los mensajes de la API y los casos que fallaron | *Abrir DEMO-3 en Jira* | Estado `approved` con `result.errors` y `failed_ids` (PA-324) |

*Reintentar solo los fallidos* (PA-05) queda fuera de alcance: lo creado se mantiene.

### 6.6 QA 6 · Registrar la ejecución (R-01, opción A) · fuera de la entrega
*Registrar la ejecución* sale como «disponible pronto». El diseño se mantiene para cuando entre:

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Ejecución de las pruebas de DEMO-3 · Ronda 1 · entorno de preproducción»; contadores Pasó / Falló / Bloqueado / Sin ejecutar | — | `POST /executions` (T-47) |
| Aviso | «El resultado se registra en cada subtarea; no lo decide la IA.» | — | RF-28 |
| Tabla | Subtarea, caso, **Resultado** (Pasó, Falló, Bloqueado, Sin ejecutar) y **Evidencia** (obligatoria si falla) | Elegir resultado y escribir evidencia | `PUT /executions/{id}/results` |
| Pie | *Guardar borrador* · *Revisar y registrar en Jira* (recibo con una casilla por subtarea y huella, §5) | Guardar / abrir recibo | `POST /executions/{id}/approve` |

## 7. Estados vacío, cargando y error

| Estado | Pantalla | Texto | Acción |
|---|---|---|---|
| Vacío | Panel sin propuesta | «Aún no hay propuesta» · «Elige un origen para generar la primera versión de la HU.» | Ir a Inicio |
| Vacío | Sin conversaciones | Lista vacía con «Nueva conversación» | — |
| Vacío | Memoria | §4.9 | — |
| Cargando | Generando, QA 2 | Q de carga por pasos (§8) | — |
| Cargando | Iterar | «Escribiendo la respuesta» (§8) | — |

**Errores:** tarjeta con un título según `ErrorBody.code` y el **mensaje de la API tal cual**. La lista completa (28 códigos, con su tono y su acción) está en `web/DESIGN-DECISIONS.md` §6; un código desconocido usa «No se pudo completar la acción». Los más frecuentes:

| `code` | Título | Acción |
|---|---|---|
| `unauthenticated` | Sesión caducada | Iniciar sesión |
| `rate_limited` | Límite de uso alcanzado | Reintentar tras la cuenta atrás de `retry_after` |
| `service_unavailable` | Servicio no disponible | Reintentar |
| `provider_timeout` | El modelo no respondió a tiempo | Volver a generar |
| `citation_failed` | La propuesta no es válida | Volver a generar |
| `coverage_failed` | La suite no es válida | Volver a generar |
| `publish_failed` | No se puede publicar | Volver al recibo (nunca se aprueba dos veces: se reintenta con `POST /retry`) |
| `approval_rejected` | Aprobación rechazada | Empezar de nuevo |
| `not_in_review` | La revisión ya no está abierta | Actualizar |
| `cancelled` | Generación detenida | Reintentar |
| `not_found` | No se encuentra | — |
| `forbidden` | Sin permiso | — |

Una publicación **parcial** no es un error: llega en `result.errors` y la pinta el Resultado. Los errores nunca muestran cabeceras, tokens ni cuerpos de respuesta (CLAUDE.md, principio 2). Un tratamiento común del 401 en todas las pantallas es PA-332.

## 8. Animaciones

Todas responden a una acción o a un proceso real, duran ≤ 0,42 s salvo la carga, usan `cubic-bezier(.2,.7,.2,1)` y **se desactivan con «reducir movimiento»** (`prefers-reduced-motion: reduce`): el estado final va en el estilo base, así que sin animación la pantalla queda igual de clara. Microinteracciones: solo color o brillo (botón −6 % al pulsar, borde naranja al pasar el ratón). Foco visible: contorno naranja de 2 px con halo oscuro (WCAG 1.4.11, PA-304).

| # | Animación | Cuándo | Cómo en la web | Con «reducir movimiento» |
|---|---|---|---|---|
| 1 | **Q de fase** | La Q de la cabecera sube un cuarto al pasar de fase (0,42 s); al bajar de fase, anima desde la anterior | SVG con `clipPath` y transición CSS | Q rellena hasta la fase, sin transición |
| 2 | **Q de carga por pasos** | Durante la generación: llena un cuarto con `load_origin`, otro con `retrieve_context` y el tercero con `generate`; mientras `generate` está en curso, se anima **dentro** del tercer cuarto; `review_ready` la llena | SVG que sigue los eventos `progress` del SSE | Los cuartos hechos, sin movimiento; la lista marca el paso en curso |
| 3 | **Q de «escribiendo»** | Mientras llega la respuesta en el chat | SVG + CSS con «Escribiendo la respuesta» (`role="status"`) | Texto sin animación |
| 4 | **Escritura de la respuesta** | La respuesta (completa, sin streaming) se escribe letra a letra, como mucho 1,5 s | Solo visual (`aria-hidden`); el texto completo se anuncia una vez | Texto completo de inmediato |
| 5 | **Entrada escalonada de la versión nueva** | Los CA entran con un pequeño retardo y el cambiado se resalta | CSS con `animation-delay` | Marcas «Cambiado en vN» / «Nueva» sin animación |
| 6 | **Recibo con casillas** | Cada casilla confirma su operación; el botón se activa al completar | Casillas nativas y transición de color | Igual, sin transición |
| 7 | **Q que se completa al publicar** | Publicada entera, la Q del Resultado llega a 4/4; publicada en parte, se llena solo en parte y no llega a 4/4 (la fase de la cabecera sí marca 4 de 4) | SVG + CSS | Q en su estado final, sin movimiento |

## 9. Dependencias del backend

La web solo depende de la API (`docs/api/openapi.yaml`); los tipos y los ejemplos se generan del contrato (`npm run api:types`) y `client.contract.ts` comprueba en `tsc` que cada método del cliente devuelve exactamente la respuesta de su ruta.

| Necesidad de la UI | Pantallas | Rutas |
|---|---|---|
| Sesión y permisos | Todas | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Proyectos y búsqueda en Jira | Inicio, Elegir en Jira | `GET /projects`, `POST /projects/choose`, `GET /projects/{project}/epics`, `GET /projects/{project}/search`, `GET /epics/{key}/stories`, `GET /issues/{key}` |
| Arranque guiado y fuentes | Inicio, Origen, QA 1 | `POST /start/propose`, `POST /start/sources` |
| Conversaciones | Lista, Generando, Iterar, recibo, Resultado | `GET /conversations`, `POST /conversations`, `GET /conversations/{id}`, `GET /conversations/{id}/events` (SSE), `POST /iterate`, `/approve`, `/discard`, `/cancel`, `/retry`; `/edit` (Editar a mano de la HU, §4.5 bis; diseño pendiente de validar en PA-340) |
| Memoria | Memoria, Resultado | `GET /memories`, `GET /memories/{key}` |
| Ajustes y consumo | Carril, Resultado, Administración | `GET /settings`, `GET /settings/usage`, `POST /admin/connections/test`, `GET /admin/models` |
| Revisar la calidad | Mixta 5, lista de conversaciones | `POST /quality-reviews`, `GET /quality-reviews`, `GET /quality-reviews/{id}` |
| Registrar la ejecución (fuera de la entrega) | QA 6 | `POST /executions`, `PUT /executions/{id}/results`, `POST /executions/{id}/approve` |
| QA encadenada (fuera de la entrega) | Resultado, Inicio de QA | `POST /conversations/{id}/handoff`, `GET /qa/handoffs`, `POST /qa/handoffs/{id}/take` |

## 10. Administración (Ajustes, solo admin · T-29 mínima)
El diseño es el de Ajustes de la página «Propuesta v2» del lienzo, con las piezas de la «Propuesta mixta». Página «Ajustes»: «Comprueba los servicios y consulta la configuración. Desde aquí no se genera ni se publica nada.»

| Tarjeta | Contenido | Acción | Dependencia |
|---|---|---|---|
| Conexiones | Al entrar, «Aún no has probado las conexiones. La prueba tarda unos segundos y se puede repetir cada 10 s.» (la API no guarda el último resultado y no se llama a servicios externos al abrir la pantalla). Tras probar, una fila por servicio (Jira, PostgreSQL, `Modelos · <proveedor>`, Embeddings) con «Conectado» / «Con problemas», el detalle de la API como texto y el tiempo | *Probar conexiones* (con CSRF; un 429 `rate_limited` trae la cuenta atrás de `retry_after`) | `POST /admin/connections/test` |
| Modelos por tarea | Cadena de modelos por tarea (principal y respaldo) con el host de cada proveedor, el cambio de la sesión si lo hay y una fila de embeddings; «Solo lectura: los modelos se cambian en config/models.yaml.» | — | `GET /admin/models` |
| Modo de publicación | «Simulación: no se escribe nada en Jira» o, en real, «Al aprobar, se escribe en Jira lo que la persona confirma.» | — | `publish_mode` de `GET /settings` |
| Documentos, usuarios e historial | «Disponible pronto» | — | — |
| Pie | «Las claves se leen del .env y nunca se muestran. El administrador configura, pero no genera ni publica artefactos (D-01).» | — | — |

**Diferencias con el lienzo** (PA-401): Conexiones sin estado al entrar; «Conectado» / «Con problemas» con el detalle de la API en lugar de «Falta la clave»; modelos con host, el cambio de la sesión y la fila de embeddings; la tarjeta «Modo de publicación» es nueva; documentos y usuarios, «disponible pronto». El archivo del lienzo (`AdministracionV2.dc.html`) aún no está copiado en el repositorio (PA-400).

## 11. Fuera de alcance y fuera de la entrega
- **Flujo unido HU → QA** (2026-10-05): *Pedir sus pruebas a QA* sale tras publicar como «disponible pronto» («No entra en esta entrega…») y no aparece tras una simulación; QA empieza escribiendo la clave de la HU. El cliente y las piezas se conservan desactivados en la web (`QA_HANDOFF_ENABLED = false`).
- **QA 6 · Registrar la ejecución** (§6.6) y *Reintentar solo los fallidos* (PA-05).
- **Elegir el modelo por petición** (RF-42): el selector del compositor queda en solo lectura.
- **El aviso «CA sin fuente»** (PA-315) y **editar la suite de QA a mano** (pregunta en PA-340).
- **Historial** y el **registro de auditoría** («disponible pronto»).
- La conversación libre que recaba datos con el LLM (PA-43, v2) y los defectos vinculados (RF-29, v2.0).
