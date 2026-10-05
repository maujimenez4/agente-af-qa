// Funciones del frontend que existen pero no entran en la entrega (DESIGN-DECISIONS.md §4 bis, «QA encadenada»).

/**
 * Flujo unido HU → QA (T-54): *Pedir sus pruebas a QA* en el Resultado de la HU y «Pendientes de pruebas» con
 * *Recoger* en Inicio de QA. Fuera de la entrega de React (decisión de la principal y su responsable, 2026-10-05):
 * se trabaja por roles y QA empieza escribiendo la clave de la HU. Las rutas siguen en la API, y el cliente, el MSW y
 * los componentes (`QaHandoffs`, `HandoffAction`) se conservan con sus pruebas por si se retoma: basta con poner
 * `true` aquí. Con `false`, *Pedir sus pruebas a QA* sale como «disponible pronto» y no hay lista de pendientes.
 */
export const QA_HANDOFF_ENABLED = false
