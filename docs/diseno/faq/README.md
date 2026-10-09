# FAQ · nombre del asistente en la web

Decisión del usuario (2026-10-09): el asistente se llama **FAQ** y el nombre aparece en toda la web de forma coherente. **Qaracter** es la marca; **FAQ** es el asistente. Diseño aprobado en el lienzo «FAQ · inicio de sesión» (claude.ai, privado); copia de referencia en esta carpeta:

| Archivo | Qué es |
|---|---|
| `login.dc.html` | **Inicio de sesión aprobado** (versión final). Referencia exacta |
| `conversacion.dc.html` | Propuesta de la conversación con el nombre (aprobada en lo que toca al nombre) |
| `carril-opciones.dc.html` | Tres opciones del carril; **aprobada la A** (solo la Q) |
| `detalles.dc.html` | Pestaña, carril, esperas, errores, firma en Jira y MCP |

Los `.dc.html` son prototipos del lienzo: **referencia visual, no código para copiar**. `/_blob/622aff8e…` es `docs/diseno/marca/logo-qaracter-oscuro.svg` y `/_blob/b2008c33…`, `logo-qaracter-blanco.svg`.

## 1. Inicio de sesión (sustituye al de PA-444)

Pantalla dividida en dos mitades (en ventanas estrechas, la mitad azul va arriba y el formulario debajo).

**Mitad azul** (`--color-navy`, `#1e2d3d`), con relleno de 64 px arriba, 56 px a los lados y 48 px abajo; tres bloques repartidos de arriba abajo (`justify-content: space-between`):
1. **Logotipo «FAQ»:** «FA» en DM Sans 800, 120 px, blanco, `letter-spacing: -0.03em`, `line-height: 1`, seguido de **la Q de Qaracter** (`Q_PATH` de `web/src/design/qPath.ts`, relleno `--color-primary`) a **84 px**, separación de 10 px, **alineada a la línea base** (`align-items: baseline`). Con DM Sans 800 a 120 px la altura de las mayúsculas es exactamente 84 px: la Q y «FA» coinciden arriba y abajo. Accesible como una imagen con nombre «FAQ».
2. **Mensaje:** «Historias de usuario y pruebas en segundos. **Siempre con tu aprobación.**» — DM Sans 500, 30 px, interlineado 1,3, ancho máximo 460 px; la segunda frase en `--color-primary`.
3. **Pie:** «un asistente de **Qaracter**» — 14 px, `--color-on-navy`; «Qaracter» en blanco y 700. Solo esas palabras.

**Mitad blanca**, formulario centrado, ancho máximo 360 px, separación de 28 px:
1. **Logo completo de Qaracter** (versión oscura, el componente `QaracterLogo` de PA-444), 30 px de alto, alineado a la izquierda.
2. **«Hola de nuevo»** (h1, 28 px, 700) y debajo «Inicia sesión para continuar en FAQ.» (15 px, `--color-text-muted`).
3. Usuario, contraseña y el botón principal naranja **«Entrar en FAQ»** (los mismos campos, validaciones y errores de hoy).

## 2. El nombre en el resto de la web

| Sitio | Texto o cambio |
|---|---|
| **Pestaña del navegador** | «FAQ · Qaracter» (y el título de cada pantalla con el patrón que ya se use) |
| **Carril** | Solo la Q (opción A): sin texto debajo. `aria-label` y `title` «FAQ · Inicio» |
| **Inicio** | Encima de «¿En qué trabajamos hoy?»: la Q (56 px) y «Hola, soy **FAQ**, tu asistente de análisis funcional y QA.» Tarjetas de flujo y cuadro de texto pueden nombrarlo («Cuéntale a FAQ…», «O escríbele a FAQ directamente») y un pie «FAQ propone; tú decides. Nada se publica en Jira sin tu aprobación.» |
| **Lista de conversaciones** | Cabecera «Tus conversaciones con FAQ» si cabe |
| **Conversación** | El avatar del asistente (la Q) con la etiqueta «FAQ» debajo; el botón «Ver la propuesta de FAQ»; en la propuesta, «La decisión es tuya: FAQ no publica nada sin tu aprobación.» |
| **Esperas** (`TypingIndicator` y los pasos de Generando) | En primera persona del asistente: «FAQ está leyendo la HU en Jira…», «FAQ está buscando en la documentación…», «FAQ está escribiendo la propuesta…», «FAQ está preparando una nueva versión…» |
| **Errores de la web** | Título «FAQ no ha podido…» donde el título actual hable del agente. **El mensaje del backend no se toca** (sale tal cual) |

**Lo que no cambia:** los botones de acción («Revisar y aprobar», «Aprobar y publicar»…), los textos que vienen de la API, el contrato y el backend. La firma en los comentarios de Jira y el nombre en el servidor MCP son del backend: quedan como propuesta aparte.

## 3. Un solo punto para el nombre

El nombre puede cambiar si dirección decide otro: definirlo en **una constante** (por ejemplo `ASSISTANT_NAME = 'FAQ'` en `web/src/text/`) y usarla en todos los textos. Cambiar el nombre debe ser cambiar una línea (más el logotipo del login).
