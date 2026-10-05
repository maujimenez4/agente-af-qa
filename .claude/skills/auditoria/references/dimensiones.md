# Dimensiones de la capa 2

Encargo de cada subagente `auditor`. Copia el bloque de su dimensión en el prompt, junto con el alcance (rutas) y la salida de la capa 1. Cada bloque dice **qué buscar**, **dónde mirar primero** y **qué no repetir**.

## Índice
- [principios](#principios) · [correccion](#correccion) · [seguridad](#seguridad) · [llm-rag](#llm-rag) · [pruebas](#pruebas) · [frontend](#frontend)
- [Pasada de refutación](#pasada-de-refutación)

---

## principios
**Qué buscar:** incumplimientos de los principios no negociables de `CLAUDE.md`, que una regla mecánica no detecta.
- Aprobación humana: caminos por los que un artefacto llega a `publish` sin estado `APPROVED` ni confirmación (reanudaciones, reintentos, modo `simulation` que acaba escribiendo, aprobaciones reutilizadas).
- Secretos: configuración leída sin `SecretStr`, valores que se cuelan en mensajes de error, en el estado del grafo o en la memoria `.md`.
- Datos sintéticos: fixtures, semillas o corpus con nombres, emails o documentos de aspecto real.
- Trazabilidad: artefactos sin la clave de Jira ni los IDs de CA, RN y CP que exige la SPEC-00.
- Salidas estructuradas: texto del modelo que se trocea a mano en lugar de validarse con `schemas/`.
- Alcance: funcionalidad que no está en el Kanban ni en la SPEC.

**Dónde mirar primero:** `core/graph/`, `core/approvals.py`, `core/memory/`, `schemas/`, `data/seed/`.
**No repitas:** las reglas `jira-write`, `env-read` y `core-concrete-import` de la capa 1.

## correccion
**Qué buscar:** fallos de lógica que aparecen en uso real.
- Carreras entre hilos, procesos o peticiones (estado compartido sin candado, comprobación y escritura separadas).
- Estados imposibles o sin salida (una conversación que no puede ni reintentarse ni descartarse).
- Errores silenciosos (`except` que convierte un fallo en un éxito aparente, valores por defecto que esconden datos ausentes).
- Reintentos o reanudaciones que **escriben dos veces** en Jira o en la base de datos.
- Fechas y zonas horarias, ordenaciones sin desempate, paginación (`nextPageToken`) incompleta.

**Dónde mirar primero:** `core/graph/`, `api/service.py`, `api/app.py` (SSE y cancelación), `adapters/jira/`, `core/conversations.py`, `core/handoff.py`.
**No repitas:** `silent-except` de la capa 1 (sí puedes razonar si un caso marcado es grave).

## seguridad
**Qué buscar:** riesgos que necesitan entender el flujo de datos.
- Inyección de órdenes al modelo: texto de Jira, de documentos o del usuario que llega al prompt sin delimitar ni neutralizar.
- XSS: Markdown o HTML del modelo o de Jira pintado sin escapar (Streamlit `st.markdown`, React).
- CSRF y origen: rutas que modifican algo sin `session_for`, o con método `GET`.
- Permisos: rutas o vistas sin `require`/`can`, objetos de otra persona accesibles por id.
- Fugas en logs, trazas de Langfuse, mensajes de error o respuestas de la API (prompts completos, cabeceras, cadenas de conexión).

**Dónde mirar primero:** `api/`, `app/views/`, `core/context/`, `core/rag/`, `adapters/observability/`, `mcp_server/`.
**No repitas:** secretos en el código (gitleaks), `log-sensitive-field` y las reglas `web-*` de la capa 1.

## llm-rag
**Qué buscar:** uso del modelo y del RAG que degrada calidad, coste o seguridad.
- Contexto sin presupuesto: entradas que pueden superar la ventana del modelo sin pasar por `core/context/budget.py`.
- Citas sin validar: fuentes citadas que no se comprueban contra el contexto entregado.
- Texto libre interpretado a mano (regex sobre la respuesta) en lugar de salida estructurada.
- Prompts sin cabecera `version:` en `prompts/`, o versiones que no se registran en la auditoría.
- Reintentos ante 429 sin backoff ni cambio de proveedor (D-14), llamadas sin tiempo límite.

**Dónde mirar primero:** `prompts/`, `core/functional/`, `core/qa/`, `core/rag/`, `core/context/`, `adapters/llm/`.
**No repitas:** `inline-prompt` de la capa 1.

## pruebas
**Qué buscar:** huecos y fragilidad de la suite.
- Criterios de aceptación del Kanban o de la SPEC sin ninguna prueba que los cubra.
- Pruebas que dependen del reloj, del orden, de la red o de la máquina (Windows, 15,6 ms).
- Mocks o fakes que esconden el comportamiento real (un fake que nunca falla, que no valida el esquema o que acepta lo que el adaptador real rechaza).
- Pruebas `integration` sin `skip` cuando faltan credenciales.
- Pruebas que no comprueban nada (sin `assert` relevante).

**Dónde mirar primero:** `tests/fakes/`, `tests/unit/` de los módulos del alcance, `docs/KANBAN.md` (criterios).
**No repitas:** la cobertura que mide pytest; razona sobre el comportamiento.

## frontend
**Qué buscar:** calidad de `web/` frente al contrato y a los usuarios.
- Estados de carga, vacío y error que faltan o que dejan la pantalla bloqueada.
- Accesibilidad: controles sin etiqueta, foco perdido tras una acción, contraste, navegación por teclado.
- Diferencias con `docs/api/openapi.yaml`: campos, códigos de error o rutas que el cliente usa y el contrato no tiene (o al revés).
- Manejo de `401`, `403`, `429` (`retry_after`) y de la cabecera `X-CSRF-Token`.

**Dónde mirar primero:** `web/src/api/`, `web/src/screens/`, `web/src/components/`, `docs/api/openapi.yaml`, `docs/specs/UI.md`.
**No repitas:** las reglas `web-*` de la capa 1 ni lo que ya prohíbe `web/eslint.config.js`.

---

## Pasada de refutación
Lanza un `auditor` por dimensión con este encargo y la tabla de hallazgos de esa dimensión:

> Intenta **refutar** cada hallazgo de esta tabla. Lee el código citado y su contexto (quién llama a la función, qué garantiza el llamador, qué cubren las pruebas). Para cada fila, añade `Veredicto`:
> - `refutado`: el código, un llamador o una prueba impide el fallo (cita dónde);
> - `plausible`: no lo impide nada, pero el escenario requiere condiciones poco habituales;
> - `confirmado`: puedes describir el escenario concreto que lo produce.
> Ajusta la gravedad si la evidencia lo justifica. No añadas hallazgos nuevos.

Solo pasan al informe los `confirmado` y `plausible`.
