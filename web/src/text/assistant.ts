// PA-478 · El asistente se llama FAQ; Qaracter es la marca (docs/diseno/faq/README.md). Un solo punto para el nombre:
// si dirección cambia el nombre, basta con cambiar esta línea (y el logotipo del inicio de sesión, `FaqLogo`).

/** Nombre del asistente en toda la web. */
export const ASSISTANT_NAME = 'FAQ'
/** La marca. */
export const BRAND_NAME = 'Qaracter'

/** Título de la pestaña del navegador. */
export const DOCUMENT_TITLE = `${ASSISTANT_NAME} · ${BRAND_NAME}`
/** Nombre accesible y `title` de la Q del carril, que lleva a Inicio. */
export const RAIL_HOME_LABEL = `${ASSISTANT_NAME} · Inicio`

// Inicio de sesión (§1).
export const LOGIN_BUTTON = `Entrar en ${ASSISTANT_NAME}`
export const LOGIN_LEAD = `Inicia sesión para continuar en ${ASSISTANT_NAME}.`

// Inicio (§2).
export const HOME_GREETING_BEFORE = 'Hola, soy '
export const HOME_GREETING_AFTER = ', tu asistente de análisis funcional y QA.'
export const HOME_GREETING = `${HOME_GREETING_BEFORE}${ASSISTANT_NAME}${HOME_GREETING_AFTER}`
export const HOME_CONTROL = `${ASSISTANT_NAME} propone; tú decides. Nada se publica en Jira sin tu aprobación.`
/** Rótulo visible encima del cuadro de texto libre de Inicio (su nombre accesible sigue siendo el del flujo). */
export const HOME_WRITE_HINT = `O escríbele a ${ASSISTANT_NAME} directamente`
/** Pista de la tarjeta «Necesito una HU». */
export const NEED_HINT = `Cuéntale a ${ASSISTANT_NAME} lo que hace falta; si ya existe una HU parecida, te la propone.`

// Lista de conversaciones y conversación.
export const CONVERSATIONS_HEADING = `Tus conversaciones con ${ASSISTANT_NAME}`
export const VIEW_PROPOSAL = `Ver la propuesta de ${ASSISTANT_NAME}`
export const VIEW_SUITE = `Ver la suite de ${ASSISTANT_NAME}`
export const PROPOSAL_CONTROL = `La decisión es tuya: ${ASSISTANT_NAME} no publica nada sin tu aprobación.`

// Esperas (los pasos de la lista son los de la API, `step.label`, y no se cambian).
export const WRITING_PROPOSAL = `${ASSISTANT_NAME} está escribiendo la propuesta…`
export const WRITING_SUITE = `${ASSISTANT_NAME} está escribiendo la suite…`
export const PREPARING_VERSION = `${ASSISTANT_NAME} está preparando una nueva versión…`

// Títulos de error que hablan del trabajo del asistente (el mensaje de la API va tal cual).
export const ERROR_PROPOSAL_UNFINISHED = `${ASSISTANT_NAME} no ha podido terminar la propuesta`
export const ERROR_CITATIONS = `${ASSISTANT_NAME} no ha podido citar sus fuentes`
export const ERROR_COVERAGE = `${ASSISTANT_NAME} no ha podido cubrir todos los criterios`
export const ERROR_QUALITY = `${ASSISTANT_NAME} no ha podido revisar la calidad`

/** Otros textos propios de la web que hablaban de «el agente». */
export const RESULT_SIMULATION_NOTICE = `Modo de prueba activo: ${ASSISTANT_NAME} no escribe en Jira. Lo cambia el administrador.`
export const USAGE_SUBJECT = `todas las personas que usan ${ASSISTANT_NAME}`
/** Ficha de una HU de Jira en QA (`published_by_agent`). */
export const PUBLISHED_BY_ASSISTANT = `publicada por ${ASSISTANT_NAME}`
