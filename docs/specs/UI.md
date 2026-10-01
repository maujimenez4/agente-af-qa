# UI · «Propuesta mixta» (T-23)

**Versión:** 1.0 · **Fecha:** 2026-10-01 · **Tarea:** T-23 · **Trazabilidad:** RNF-15, D-04, D-12, PA-44
**Diseño de referencia:** lienzo «Rediseño UI del agente AF y QA», página **Propuesta mixta** — https://claude.ai/artifact/PK7Mfx3z357t1x7e2hsSbB
**Decisión:** «Decisiones del día 6» de `docs/KANBAN.md` (la UI mixta sustituye al modelo de pestañas Contexto/Historia/QA).

Este documento describe **qué** muestra cada pantalla, **quién** la ve y **de qué depende** en el backend. No define contratos nuevos: lo que aún no existe se marca con su tarea (T-47, T-48, T-50 … T-53, PA-05) o como propuesta adicional. La implementación es de T-24 en adelante, en Streamlit (D-04, sin frontend separado).

---

## 1. Principios de la interfaz

1. **Asistente conversacional por fuera, arranque guiado por dentro.** El usuario elige el flujo (tarjetas) y el origen (selector de Jira o clave escrita). El modelo **no** hace preguntas para recoger datos (eso queda para v2, PA-43).
2. **La operación queda fijada antes de generar** y no cambia durante la conversación: es lo único que se podrá aprobar y publicar (`core/approvals.py`, el destino no cambia entre iteraciones).
3. **Las fuentes se pueden desmarcar** antes de generar.
4. **La conversación sirve para iterar** la propuesta (RF-20) y preguntar sobre ella.
5. **Nada se escribe en Jira sin aprobación humana**: recibo con una casilla por operación y huella de la versión revisada (§5).
6. **El resultado distingue publicación simulada y real** (`JIRA_PUBLISH_MODE`, T-25).
7. **Textos en español**; mensajes de error tomados de las excepciones (`adapters/errors.py` y errores del núcleo), nunca reescritos en la UI.
8. **Datos de ejemplo ficticios** (proyecto `DEMO`, usuarios `af-demo`, `qa-demo`, `admin-demo`).

## 2. Marco común

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Carril lateral (88 px) | Logotipo Q, zonas Trabajo, Historial, Ajustes (según rol) y usuario | Cambiar de zona | `core/permissions.py` (§3) |
| Lista de conversaciones (248 px) | «Nueva conversación», buscador, conversaciones agrupadas por día con **clave de proyecto**, título, flujo y estado («Publicado», «Versión 2», «Informe listo») | Retomar una conversación | **T-52** (checkpointer y listado por usuario) · proyecto de la conversación **T-50** |
| Cabecera | Título de la conversación y **Q de fase** («Fase N de 4 · Contexto / Generar / Revisión / Publicado») | — | Estado del grafo (`AgentState`, `artifact.status`) |
| Compositor | Cuadro de texto con ayuda según el flujo, «Elegir en Jira», **selector de modelo** («Modelo automático») y enviar | Enviar mensaje / feedback | Override de sesión de `ModelRouter` (RF-42) |
| Aviso de modo de prueba | «Modo de prueba: al aprobar verás lo que se haría en Jira, pero no se escribirá nada.» | — | `JIRA_PUBLISH_MODE=simulation` (T-25) |
| Panel derecho (420 px) | «Antes de generar», propuesta, suite o informe según la fase | Plegar panel | — |

Las cuatro fases de la Q son: **1 Contexto** (origen y fuentes) · **2 Generar** (generar e iterar) · **3 Revisión** (recibo, aprobada) · **4 Publicado**.

## 3. Roles y visibilidad

Según `core/permissions.py` (`ROLE_PERMISSIONS`):

| Función de la UI | Permiso | `functional` (analista) | `qa` | `admin` |
|---|---|---|---|---|
| Nueva necesidad, Evolucionar HU | `GENERATE_STORY` | ✅ | ⛔ desactivada | — |
| Revisar la calidad | `GENERATE_STORY` (no publica) · *provisional, lo fija T-48* | ✅ | ⛔ desactivada | — |
| Aprobar y publicar HU | `PUBLISH_STORY` | ✅ | — | — |
| Preparar pruebas | `GENERATE_TESTS` | ⛔ desactivada | ✅ | — |
| Aprobar y publicar suite, registrar ejecución | `PUBLISH_TESTS` · *registrar ejecución provisional, lo fija T-47* | — | ✅ | — |
| Ver contexto y memoria | `VIEW_CONTEXT`, `VIEW_MEMORY` | ✅ | ✅ | ✅ |
| Ajustes (conexiones, modelos, documentos, usuarios) | `MANAGE_*` | — | — | ✅ |
| Historial | ver PA-62 | — | — | ✅ |

- **Tarjetas que el rol no puede usar:** se muestran **desactivadas** (`aria-disabled`) con la ayuda «Disponible para el rol de analista funcional.» o «Disponible para el rol QA.». El rol QA ve la tarjeta «Preparar pruebas» seleccionada por defecto.
- **El administrador** configura pero no genera ni publica (D-01): ve Ajustes e Historial y no ve las tarjetas de flujo.
- La UI consulta `can()` antes de mostrar y `require()` antes de ejecutar; el error es «No tienes permiso para realizar esta acción.».
- Que `publish` exija también el permiso además de la aprobación está pendiente (PA-25 · T-31).

## 4. Flujo de HU (analista funcional)

### 4.1 Mixta 1 · Inicio
Pantalla central «¿En qué trabajamos hoy?» con la Q, el subtítulo «Elige qué hacemos y de qué partimos. Después lo mejoramos conversando. Nada se publica en Jira sin tu aprobación.»

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Tarjetas de flujo (rejilla 2×2) | **Nueva necesidad**, **Evolucionar una HU**, **Revisar la calidad de una HU** (analista) y **Preparar pruebas** (QA) | Elegir flujo (`aria-pressed`) | Permisos (§3) · Revisar la calidad **T-48** |
| Compositor | Texto de ayuda según el flujo (p. ej. «Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.») | Escribir necesidad o clave | Reconocimiento de clave **T-53** |
| Selector de proyecto | Clave y nombre del proyecto; **todos los que ve la conexión**, con el último usado preseleccionado | Cambiar de proyecto (abre Mixta 1b) | `list_projects` (SPEC-00 v1.3) · último proyecto por usuario **T-50** |
| «Elegir en Jira» | Botón | Abre Mixta 1b | `list_projects`, `list_epics`, `list_children` |
| Recientes del proyecto | Chips con clave y título (HU y épicas) | Fijar ese origen | `search` del proyecto · **T-50** (proyecto) |
| Lista de conversaciones | Ver §2 | Retomar | **T-52** |
| Aviso de modo de prueba | Ver §2 | — | T-25 |

Una clave de otro proyecto escrita en el texto cambia el proyecto de la conversación sola (decisión del día 6 · **T-50**, **T-53**).

### 4.2 Mixta 1b · Elegir en Jira
Diálogo modal (`role="dialog"`).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Buscador | «Buscar por texto o clave en el proyecto DEMO» | Filtrar las tres columnas | `search` con `text_search_jql` (T-14) · clave **T-53** |
| Columna Proyectos | «Proyectos que ve la conexión (N)» | Elegir proyecto | `list_projects` |
| Columna Épicas | «Épicas de DEMO (N)»; nota «Elegir la épica sirve para crear una HU nueva dentro de ella.» | Elegir épica | `list_epics` |
| Columna HU | «HU de DEMO-1 (N)» | Elegir HU | `list_children` |
| Pie | «Seleccionada: DEMO-3 · …» · *Cancelar* · *Usar la épica DEMO-1* · *Usar DEMO-3* | Fijar el origen (épica o HU) | `Origin` (+ `project_key` **T-50**) |

### 4.3 Mixta 2 · Origen fijado
Fase 1 de 4. Conversación a la izquierda y panel «Antes de generar» a la derecha.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Mensaje del usuario | La necesidad escrita | — | — |
| HU parecida | Etiqueta «Búsqueda en Jira por texto · sin IA»; tarjeta con la HU encontrada (clave, épica, nº de CA y RN) | *Evolucionar DEMO-3* · *Crear HU nueva* | **T-53** (HU parecida por `ContextService`, sin LLM) |
| Tarjeta «Operación fijada» | «Operación fijada: evolucionar DEMO-3. No cambia durante la conversación; es lo único que se podrá aprobar y publicar.» | — | `PublishTarget` en `core/approvals.py` |
| Panel · Operación | Operación y origen; «Se puede cambiar solo antes de generar.» | *Cambiar* (vuelve a Mixta 1) | — |
| Panel · Restricciones | Texto opcional | Escribir | Se añade al texto de la necesidad (decisión de integración a confirmar en T-51) |
| Panel · Fuentes | Lista con **casillas**: título, `DOC-NN` o clave y categoría; una fuente desmarcada indica «No influirá en la propuesta»; la memoria aparece como «prioritaria» | Marcar / desmarcar | Fuentes excluidas en el estado inicial **T-51** · nombres de categoría **T-49** |
| Panel · Presupuesto | «Contexto · 3.150 de 6.000 tokens» con barra de progreso | — | `core/context/budget.py` (T-18) |
| Panel · Pie | *Generar propuesta* · «Una llamada al modelo. Después itera conversando.» | Arranca el grafo | `core/graph` (`retrieve_context` → `generate`) |

### 4.4 Mixta 2b · Generando
Fase 2 de 4. La **Q de carga se llena un cuarto por proceso** (§7).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Lista de procesos | 1 Recuperar contexto (fuentes y tokens) · 2 Generar la versión 1 (proveedor · modelo) · 3 Validar citas y diff con Jira · 4 Analizar el impacto | — | Nodos `retrieve_context`, `generate` (`StoryWriter`, `diff_stories`, `ImpactAnalyzer`) |
| Titular | «Generando la propuesta…» → «Propuesta lista · Versión 1 · N cambios frente a Jira» | *Ver la propuesta* | — |
| Compositor | Desactivado: «Espera a la propuesta para pedir cambios» | — | — |
| Panel | «La propuesta aparece aquí cuando las citas están comprobadas.» | — | `core/functional/citations.py` |

### 4.5 Mixta 3 · Iterar
Fase 2 de 4. Conversación + panel de la propuesta.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Resumen del asistente | «Versión 1 lista. 4 de 5 criterios tienen fuente; el CA-04 no.» | — | Validación de citas |
| Mensaje de cambio | El usuario pide un cambio (RF-20) | Enviar | Reanudación `{"decision": "iterate", "feedback": …}` |
| Indicador | **«Escribiendo la respuesta»** con la Q animada | — | Llamada `generate` en curso |
| Respuesta | «Versión 2 lista. Cambió el CA-03 y añadió la RN-02. Afecta también a DEMO-2…» | Abrir en el panel | `ImpactAnalysis` |
| Aviso de modelo usado | «Generado con openrouter · qwen3.8-27b» | — | `Artifact.model_used` (proveedor y modelo de `StructuredResult`). El motivo del cambio («Groq llegó a su límite») no lo expone el backend → PA-67 |
| Sugerencias | Chips: «Busca la fuente del CA-04», «Añade un criterio de error», «Revisa INVEST» | Rellenar el compositor | — |
| Panel · Versiones | *Jira* · *v1* · *v2* … | Ver una versión | `StoryVersionStore` (T-19) · versión de partida en `artifact_state` (T-25) |
| Panel · Pestañas | **Propuesta** · **Cambios (N)** · **Impacto (N)** · **Fuentes (N)** | Cambiar de pestaña | `UserStory`, `diff_stories`, `ImpactAnalysis`, fuentes citadas |
| Propuesta | «Como / quiero / para», CA y RN con su cita (`DOC-NN` o clave); el cambiado lleva la marca «Cambiado en v2» / «Nueva» | — | — |
| CA sin fuente | «Sin respaldo en las fuentes: confírmalo o pide que se busque.» | *Confirmar* · *Pedir fuente* | *Pedir fuente* = `iterate` con feedback predefinido; *Confirmar* se guarda en la versión editada **T-51** (`edit`) |
| Pie del panel | *Editar a mano* · *Descartar* · *Revisar y aprobar* | Editar / descartar / abrir el recibo | `edit` **T-51** · `discard` · §4.6 |

### 4.6 Recibo de aprobación (Trabajo 3 de la v2)
Fase 3 de 4 al aprobar. Es la **revisión humana**: el `interrupt` de `human_review`.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Versión N lista para revisar» | — | `version` del payload |
| «Qué se hará en Jira» | **Una casilla por operación**: «Actualizar DEMO-3 con la versión 3» (con los campos cambiados), «Añadir un comentario con los cambios», «Vincular con DEMO-2» (motivo); contador «N de 3 revisadas» → «Todo revisado» | Marcar cada operación | `target` (`PublishTarget.describe()`) e `impact` del payload · lista detallada de operaciones (`plan`) **T-51** |
| Aviso | «Generado con IA a partir de N fuentes. Revisa cada operación antes de aprobar.» | — | — |
| Botones | *Descartar* · *Volver a generar* · **Aprobar y publicar** (activo solo con todas las casillas marcadas) | `discard` · `iterate` · `approve` | Contrato §5 |
| Historial de la HU | Versiones con proveedor, versión del prompt (`prompt_version`, nunca su texto), hora e iteraciones de quién | — | `artifact_versions` · `audit_log` (T-25) |
| Pie | «Al publicar quedará registrado quién aprobó, cuándo y qué claves se crearon.» | — | `SqlAuditTrail` |

### 4.7 Mixta 4 · Resultado
Tweak «modo»: **simulación** o **real**.

| Modo | Fase | Contenido | Acción | Dependencia |
|---|---|---|---|---|
| Simulación | 3 de 4 · Aprobada | Distintivo «Aprobada · simulada»; «Publicación simulada · No se ha escrito nada en Jira. Esto es lo que se habría hecho, y queda en la auditoría:» + operaciones; nota «La aprobación sigue vigente: cuando se active la publicación real se podrá publicar sin repetir la revisión. La memoria se genera al publicar de verdad.» | *Ver el registro de auditoría* · *Ir al historial* | `publish` en `simulation` (T-25); caducidad de la aprobación PA-41 |
| Real | 4 de 4 · Publicado | «Publicado en Jira · Estas operaciones ya están en Jira:» + operaciones hechas; «La memoria de DEMO-3 se ha generado e indexado; tendrá prioridad en las próximas propuestas.» | *Abrir DEMO-3 en Jira* · *Ver la memoria* · *Pedir sus pruebas a QA* | `publish` en `live` (T-27, T-30) · `memorize` (T-33) · *Pedir sus pruebas a QA*: PA-63 |
| Ambos | — | «Versión 2 aprobada por af-demo a las 15:47» · aviso «Modo de prueba activo… Lo cambia el administrador.» | — | `audit_log` |

### 4.8 Mixta 5 · Revisar la calidad
Flujo propio, **solo lectura: no publica** (decisión del día 6).

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Calidad de DEMO-4 · Revisar la calidad · solo lectura» | — | **T-48** |
| Conversación | «He revisado DEMO-4 con INVEST y contra las fuentes. Hay 3 puntos a mejorar. No he cambiado nada en Jira.»; preguntas sobre el informe | Preguntar | **T-48** (`StoryWriter.review`) |
| Panel · INVEST | Seis filas I, N, V, E, S, T con «Bien» / «Mejorable» | — | **T-48** |
| Panel · Hallazgos | Tipo (Ambigüedad · Hueco · Sin fuente), CA afectado, explicación y propuesta | — | **T-48** (`open_questions`, `changes_from_previous`) |
| Pie | *Descargar informe* · *Evolucionar DEMO-4 con esto*; «Este flujo no publica en Jira. Evolucionar abre una conversación nueva con estas mejoras como punto de partida.» | Descargar / abrir Mixta 2 con el flujo Evolucionar | Descarga: PA-64 · conversación nueva **T-52** |

## 5. Contrato de aprobación (SPEC-00 anexo §11)

1. `human_review` hace `interrupt()` con el payload `{artifact, version, target, fingerprint, impact, decisions}`.
2. La UI muestra el recibo (§4.6 / §6.4) con `target` e `impact`. La lista detallada de operaciones de Jira (`plan`) llega con **T-51**; hasta entonces el recibo se construye con `target` e `impact`.
3. Respuestas de la UI:
   - Aprobar: `{"decision": "approve", "fingerprint": <la huella recibida>}`. **Sin huella, o con otra, no se aprueba**: el grafo responde «La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto.» (`ValueError`; `ApprovalError` de `core/approvals.py` también es subclase de `ValueError`, no de `AgentError`: T-24 debe capturarlas).
   - Iterar: `{"decision": "iterate", "feedback": "<texto del chat>"}`.
   - Descartar: `{"decision": "discard"}`.
   - Editar a mano: decisión `edit` (contenido editado → versión nueva con su huella) **T-51**.
4. La UI no guarda ni reconstruye la huella: devuelve exactamente la del último `interrupt`. Si la persona itera, la huella anterior deja de valer.
5. *Aprobar y publicar* solo se activa con todas las casillas del recibo marcadas; es una ayuda visual: la garantía la da la huella en el grafo.
6. Tras publicar, la aprobación se consume (un solo uso). En simulación sigue vigente (T-25), siempre que la huella siga coincidiendo con la versión aprobada; su caducidad antes de activar `live` es PA-41.
7. **Toda escritura en Jira pasa por el nodo `publish`** con aprobación vigente, incluidos el reintento de una publicación parcial (§6.5) y el registro de la ejecución (§6.6). La UI nunca llama a `IssueTracker` ni a `TestManagement` para escribir.

## 6. Flujo de QA (rol QA)

Se entra por **Preparar pruebas** en Mixta 1 y se parte siempre de una HU existente («El modo QA parte siempre de una HU existente.»).

### 6.1 QA 1 · HU de origen, tipos de caso y fuentes
Fase 1 de 4.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Clave reconocida | «Clave reconocida en Jira · sin IA»; tarjeta con la HU (épica, nº de CA y RN, «sin casos de prueba en Jira», «Publicada por el agente») | — | **T-53** · `get_issue` |
| Operación fijada | «Operación fijada: suite de pruebas de DEMO-3. Los casos serán subtareas de DEMO-3 con la etiqueta «caso-prueba»; la estrategia y la matriz, adjuntos.» | — | `PublishTarget` (D-09) |
| Panel · Tipos de caso (RF-22) | Casillas Positivos, Negativos, Alternos, De excepción | Marcar | Indicaciones para `TestWriter` (T-26) como texto (a confirmar en PA-61 / T-51) |
| Panel · Incluir además | Datos sintéticos (RF-25), Riesgos, dependencias e impacto (RF-27), Estrategia de pruebas (RF-26) | Marcar | `SuiteDraft` (T-26) |
| Panel · Fuentes | HU de origen (**obligatoria**, sin casilla), memoria de la HU (prioritaria), casos de HU relacionadas (regresión), documentos | Marcar / desmarcar | Fuentes excluidas **T-51** · categorías **T-49** |
| Pie | *Generar la suite* · «Una llamada al modelo. Después itera conversando.» | Arranca el grafo en modo QA | Conexión de `TestWriter` al grafo (PA-61) |

### 6.2 QA 2 · Generando
Fase 2 de 4. Mismo patrón que Mixta 2b.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Lista de procesos | 1 Recuperar la HU y el contexto · 2 Generar casos y escenarios · 3 Validar la cobertura («Cada CA con al menos un CP; CA y RN existentes») · 4 Datos sintéticos, riesgos y estrategia | — | `core/qa/writer.py`, `core/qa/validation.py` (T-26) · PA-61 · granularidad PA-66 |
| Titular | «Generando la suite…» → «4 casos · todos los CA cubiertos» | *Ver la suite* | — |
| Compositor | Desactivado: «Espera a la suite para pedir cambios» | — | — |
| Panel | «La suite aparece aquí cuando la cobertura está comprobada.» | — | `CoverageError` si no se cumple |

### 6.3 QA 3 · Iterar la suite

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Conversación | Resumen («Suite lista: 4 casos y todos los CA cubiertos. Riesgo: …»), peticiones de cambio, indicador «Escribiendo la respuesta», sugerencias | `iterate` | RF-20 |
| Panel · Estado | Versiones *v1*, *v2*; distintivo «Todos los CA cubiertos» | — | Validación de cobertura |
| Pestaña **Casos** | Por caso: id, título, tipo, prioridad, «Verifica CA-xx, RN-yy», marca «nuevo en v2» y su **Gherkin** desplegable | — | `TestSuite` (RF-23) |
| Pestaña **Cobertura** | Matriz CA/RN × CP (RF-24) «se adjunta como matriz-DEMO-3.md»; «Cada CA y cada RN tiene al menos un caso. Si no fuera así, la suite no se podría aprobar.» | — | `SuiteDraft.coverage_md` |
| Pestaña **Datos y riesgos** | Tabla de datos sintéticos (identificadores ficticios, RF-25) y lista de riesgos, dependencias y áreas de impacto (RF-27) | — | T-26 |
| Pestaña **Estrategia** | = plan de pruebas (decisión del día 6): alcance, niveles, entornos, criterios de entrada y salida, prioridad; «se adjunta como estrategia-DEMO-3.md» | — | RF-26 (T-28) |
| Pie | *Editar a mano* · *Descartar* · *Revisar y aprobar* | — | `edit` **T-51** · §6.4 |

### 6.4 QA 4 · Recibo
Fase 3 de 4. Mismo patrón que §4.6.

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Pruebas de DEMO-3 · versión 2 lista para revisar» | — | `version` del payload |
| «Qué se hará en Jira» | Casillas: «Crear 5 subtareas en DEMO-3 con la etiqueta «caso-prueba»» (pasos, datos, resultado esperado y prioridad) · «Adjuntar estrategia-DEMO-3.md» · «Adjuntar matriz-DEMO-3.md» (cobertura CA/RN ↔ CP); contador «N de 3 revisadas» | Marcar cada operación | `target` e `impact` · hoy una sola operación `publish_suite`; desglose (`plan`) **T-51** · `JiraNativeTests` (T-30, D-09) |
| Aviso | «Generado con IA a partir de la HU publicada y N fuentes. Revisa cada operación antes de aprobar. Si una subtarea falla, las demás se mantienen y podrás reintentar solo esa.» | — | RNF-13 · PA-05 |
| Botones | *Descartar* · *Volver a la suite* · **Aprobar y publicar** (activo con todas las casillas) | `discard` · `iterate` · `approve` | Contrato §5 |
| Historial de la suite | Versiones con modelo, `prompt_version`, hora e iteraciones de `qa-demo` | — | `artifact_versions` · `audit_log` |

### 6.5 QA 5 · Resultado
Tweak «modo»: **real**, **parcial** o **simulación**.

| Modo | Contenido | Acción | Dependencia |
|---|---|---|---|
| Simulación | «Publicación simulada · No se ha escrito nada; esto es lo que se habría hecho.»; «La aprobación sigue vigente para publicar cuando se active el modo real.» | *Ver el registro de auditoría* | T-25 |
| Parcial | «Publicada en parte · 6 de 7 operaciones hechas · falló CP-05»; por operación: hecha o «Jira no respondió; no se creó»; «Lo creado se mantiene. El reintento solo publica CP-05 y no duplica las subtareas que ya existen (RNF-13).» | **Reintentar solo los fallidos** | `PublishResult.failed` (T-30) · idempotencia **PA-05**. El reintento pasa por `publish`; si reutiliza la aprobación de la publicación parcial o exige una revisión nueva se decide en T-30/PA-05 (hoy la aprobación se consume al publicar) |
| Real | «Suite publicada en Jira · 5 subtareas y 2 adjuntos en DEMO-3» (hoy el plan de una suite es una sola operación `publish_suite` con el nº de casos; el desglose por subtarea y adjunto depende de **T-51** y T-30); «Cuando ejecutes las pruebas, registra aquí el resultado.» | *Registrar la ejecución* · *Abrir DEMO-3 en Jira* | T-30 · §6.6 |

### 6.6 QA 6 · Registrar la ejecución (R-01, opción A)

| Zona | Contenido | Acción | Dependencia |
|---|---|---|---|
| Cabecera | «Ejecución de las pruebas de DEMO-3 · Ronda 1 · entorno de preproducción»; contadores Pasó / Falló / Bloqueado / Sin ejecutar | — | **T-47** |
| Aviso | «El resultado se registra en cada subtarea; no lo decide la IA.» | — | RF-28 |
| Tabla | Subtarea (clave), caso (id · prioridad · título), **Resultado** (Pasó, Falló, Bloqueado, Sin ejecutar) y **Evidencia** («Obligatoria si falla», «Enlace o nota (opcional)») | Elegir resultado y escribir evidencia | **T-47** |
| Nota | «Un caso fallido necesita evidencia. Proponer un defecto vinculado queda para la v2.0 (RF-29).» | — | R-01 opción A |
| Pie | «Se cambiará el estado de N subtareas y se añadirá un comentario con la evidencia. Nada se escribe en Jira sin tu aprobación.» · *Guardar borrador* · *Revisar y registrar en Jira* | Guardar / abrir recibo | **T-47** · borrador PA-65 |

El registro de la ejecución es un **artefacto propio**: *Revisar y registrar en Jira* abre un recibo con una casilla por subtarea (cambio de estado y comentario de evidencia), se aprueba con la huella (§5) y solo escribe el nodo `publish` (T-47).

## 7. Estados vacío, cargando y error

| Estado | Pantalla | Texto | Acción |
|---|---|---|---|
| Vacío | Panel sin propuesta | «Aún no hay propuesta» · «Elige un origen para generar la primera versión de la HU.» | Ir a Mixta 1 |
| Vacío | Sin conversaciones | Lista vacía con «Nueva conversación» | — |
| Cargando | Mixta 2b / QA 2 | Q de carga por procesos (§8) | — |
| Cargando | Iterar | «Escribiendo la respuesta» (§8) | — |

Errores: tarjeta con título corto y el **mensaje de la excepción tal cual** (en español y apto para la UI, SPEC-00 §8). Ejemplos reales del código:

| Excepción | Título | Mensaje (del código) | Acción |
|---|---|---|---|
| `RateLimitError` (cadena agotada) | Límite de uso alcanzado | «Todos los proveedores de la tarea «generate_story» han alcanzado su límite de uso. Espera unos minutos o elige otro modelo.» | Reintentar tras `retry_after` («Reintento disponible en N s») · cambiar de modelo |
| `ExternalServiceError` (cadena) | Proveedores no disponibles | «Todos los proveedores de la tarea «…» han fallado. Revisa las conexiones en Administración o elige otro modelo.» | Cambiar de modelo |
| `AuthenticationError` (Jira) | Jira rechazó las credenciales | «Jira ha rechazado las credenciales (HTTP 401). Revisa el email, el token y sus scopes.» | (Solo admin) Ir a Ajustes |
| `NotFoundError` (Jira) | No existe la incidencia | «La incidencia DEMO-99 no existe o no tienes permiso para verla.» (clave con formato no válido: ««X» no es una clave de Jira válida.») | Elegir en Jira |
| `ExternalServiceError` (Jira) | Sin conexión con Jira | «No se pudo conectar con Jira. Revisa la URL del sitio y la red.» | Reintentar |
| `CitationError` | La propuesta no es válida | «La propuesta cita fuentes que no están en el contexto recibido. …» | *Volver a generar* |
| `CoverageError` | La suite no es válida | «La suite de pruebas no cubre la HU: algún criterio no tiene casos, faltan casos positivos o negativos, se referencian CA/RN inexistentes o hay datos que parecen personales. Vuelve a generarla.» | *Volver a generar* |
| `PublishError` | No se puede publicar | «No consta una aprobación humana vigente para esta versión exacta del artefacto.» | Volver al recibo |
| `ApprovalError` | Versión ya publicada | «Esta versión ya se publicó; genera una versión nueva.» | Iterar |
| `ApprovalError` | Destino cambiado | «El destino de publicación no puede cambiar entre iteraciones.» | Nueva conversación |
| `AuthenticationError` (permisos) | Sin permiso | «No tienes permiso para realizar esta acción.» | — |
| Publicación parcial (RNF-13) · no es una excepción: entradas de `state["errors"]` | Publicada en parte | «No se pudo publicar CP-04.» · «No se pudo vincular DEMO-3 con DEMO-2.» (el resumen «Creadas … · falló …» del lienzo se compone con `PublishResult.created`/`failed`, T-30) | *Reintentar solo los fallidos* (PA-05) |

Los errores nunca muestran cabeceras, tokens ni cuerpos de respuesta (CLAUDE.md, principio 2).

## 8. Animaciones

Todas responden a una acción o a un proceso real, duran ≤ 0,42 s salvo la carga, usan `cubic-bezier(.2,.7,.2,1)` y se **desactivan con «reducir movimiento»** (`@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}`). Microinteracciones: solo color o brillo (botón −6 % al pulsar, borde naranja al pasar el ratón, foco visible naranja de 2 px).

| # | Animación | Cuándo | Cómo en Streamlit | Alternativa estática (PA-44) |
|---|---|---|---|---|
| 1 | **Q de fase** | La Q de la cabecera sube un cuarto al pasar de fase (0,42 s): `clipPath` con `rect` que se traslada de 326 a 244,5 / 163 / 81,5 / 0 | SVG + `@keyframes` en `st.html`; la fase sale del estado del grafo y el SVG se vuelve a pintar | Q rellena hasta la fase actual, sin transición |
| 2 | **Q de carga por procesos** | Durante la generación, un cuarto por proceso, en bucle mientras dura | SVG en `st.html` dentro de un `st.empty()` que se actualiza con los eventos de `graph.stream`. **Hoy solo se distinguen los nodos** (`load_origin`, `retrieve_context`, `generate`): escribir, validar citas y diff, e impacto ocurren dentro de `generate`, así que la Q avanza en 2–3 pasos y el último cuarto llega al terminar `generate`. Un cuarto por proceso real exige eventos dentro de `generate` → PA-66 | Lista de procesos con marca ✓ y `st.status` |
| 3 | **Q de «escribiendo»** | Mientras el modelo responde en el chat (parpadeo suave) | SVG + CSS en `st.html` como mensaje provisional; se sustituye por la respuesta | Texto «Escribiendo la respuesta…» |
| 4 | **Entrada escalonada de la versión nueva** | Al llegar una versión: los CA entran con retardo de 0,08 s y el cambiado se resalta un instante (`flash`) | Cada CA en `st.html` con `animation-delay`; solo se anima en la primera pintada de esa versión (marca en `st.session_state`) | Marca «Cambiado en vN» / «Nueva» sin animación |
| 5 | **Recibo con casillas** | Cada casilla confirma su operación; el botón se activa al completar | `st.checkbox` por operación y `st.button(disabled=not all(...))`; la transición de color es CSS de tema | Igual, sin transición (funciona sin CSS) |
| 6 | **Q que se completa al publicar** | En el resultado real la Q llega a 4/4 y aparecen las operaciones hechas | SVG + `@keyframes` en `st.html` | Q completa y lista de operaciones |

Viabilidad: las seis se pueden hacer con `st.html` (SVG y CSS, sin JavaScript) y widgets estándar. `st.html` no ejecuta scripts, así que **no hay estado animado entre reruns**: cada animación se dispara al pintar y se controla con `st.session_state` para no repetirla. Si en T-24 alguna no fuese viable, se usa su alternativa estática y se anota.

## 9. Dependencias del backend

| Necesidad de la UI | Pantallas | Tarea |
|---|---|---|
| Proyecto en la conversación (`project_key` en `Origin`/`PublishTarget`, último proyecto por usuario) | Mixta 1, 1b, lista de conversaciones | **T-50** |
| Fuentes excluidas, `plan` de operaciones en `human_review`, decisión `edit` | Mixta 2, 3, recibo, QA 1, QA 3, QA 4 | **T-51** |
| Conversaciones persistentes y listado por usuario | Lista de conversaciones, retomar, Mixta 5 → Evolucionar | **T-52** |
| Reconocimiento de clave y HU parecida sin IA | Mixta 1, 2, QA 1 | **T-53** |
| Registro de la ejecución | QA 5 (*Registrar la ejecución*), QA 6 | **T-47** |
| Revisar la calidad | Mixta 5 | **T-48** |
| Reintentar solo los fallidos sin duplicar | QA 5 (parcial), estado de error | **PA-05** (T-30) |
| Categorías de las fuentes | Panel de fuentes | **T-49** |
| `TestWriter` conectado al grafo | QA 1 … QA 4 | PA-61 |
| Ya disponible | `list_projects`, `list_epics`, `list_children`, `search` (T-14) · `ContextService` y presupuesto (T-18) · `StoryWriter` (T-20) · versiones y diff (T-19) · impacto (T-21) · auditoría, `artifact_state` y simulación (T-25) · `TestWriter` (T-26) · `ModelRouter` con override (RF-42) · permisos (T-22) | — |

## 10. Fuera de alcance de este documento
- Código de `app/` (T-24, T-28, T-29, T-31, T-33).
- Las pantallas de **Ajustes** e **Historial** (página «Propuesta v2» del lienzo); se detallan en T-29 y T-45.
- La conversación libre que recaba datos con el LLM (PA-43, v2).
- Defectos vinculados (RF-29, v2.0).
