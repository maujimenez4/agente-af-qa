# Propuesta de correcciones del lienzo «Propuesta mixta» (PA-304)

**Estado:** propuesta del responsable del área B, 2026-10-07. No se ha cambiado el lienzo: es un artefacto de claude.ai (https://claude.ai/artifact/PK7Mfx3z357t1x7e2hsSbB) y `docs/diseno/lienzo/` es solo su copia de referencia. Al corregirlo hay que volver a copiarlo (README de `lienzo/`).

**Para qué:** que el lienzo diga lo mismo que la web en React (`web/`) y que UI.md v2.1. Hoy, quien abre el lienzo ve decisiones ya descartadas. Cada fila cita dónde está el cambio en la copia y la decisión que lo respalda (`web/DESIGN-DECISIONS.md`, «DD»).

## 1. Accesibilidad (lo más importante)

| # | Dónde (copia del 2026-10-02) | Qué dice el lienzo | Corrección | Respaldo |
|---|---|---|---|---|
| 1 | Todas las pantallas; `textarea:focus{outline:none}` en `MixtoInicio`, `MixtoIterar`, `MixtoOrigen`, `MixtoRevisar`, `QaIterar` y `QaOrigen` | No hay `:focus-visible`: promete un foco naranja de 2 px, pero `#FF7932` sobre blanco da 2,6:1 | `:focus-visible` global con un contorno de 2 px `#FF7932` y un halo de 2 px `#B23E00` (más de 3:1, WCAG 1.4.11). El compositor mantiene su anillo `0 0 0 3px #FFF3EC` | DD §1, decisión 12 |
| 2 | `Animaciones.dc.html:36` (`animation:none!important`) | Con «reducir movimiento», la Q de fase se ve **llena** | El estado final de cada Q va en el estilo base y la animación solo recorre «desde → hasta»: sin animación, la Q queda en su fase | DD §1, decisión 13 |
| 3 | `Rail.dc.html:30-32` y `:61-62` | «24 % tokens» y nombre «Consumo diario de tokens: 24 %» | «24 %» y debajo «consumo total»; nombre accesible y `title`: «Consumo de tokens de hoy de todas las personas que usan el agente: 12.345 de 50.000, 25 % del umbral de aviso» | DD §1, decisión 17; UI.md §2 |

## 2. Textos y estados

| # | Dónde | Qué dice el lienzo | Corrección | Respaldo |
|---|---|---|---|---|
| 4 | `QaResultado.dc.html:107` | Suite publicada en parte: «Fase 3 de 4 · Aprobada» | «Fase 4 de 4 · Publicada en parte», igual que la HU | PA-304, UI.md §6.5 |
| 5 | `MixtoIterar.dc.html:93` y `QaIterar.dc.html:93` | Indicador «Escribiendo la respuesta» | «Generando una nueva versión…» mientras se genera; después, la respuesta se escribe letra a letra | PA-430, PA-131, UI.md §4.5 |
| 6 | `MixtoIterar.dc.html:85` | Sugerencia «Busca la fuente del CA-04» | «Aclara el alcance» (el contrato no da la cita de cada CA) | DD §4 bis, PA-315 |
| 7 | `Rail.dc.html:46` | «Historial» para los tres roles | Solo `admin`, como «disponible pronto» | DD §1, decisión 16; PA-302 |
| 8 | `Estados.dc.html:39` | Aviso con `#FFF3E0` / `#F0C98A` / `#6B3A00` | `#FFF8E6` / `#F0D48A` / `#6B4A00` (una sola paleta de aviso) | DD §1, decisión 1 |
| 9 | `TrabajoRevision.dc.html:25` y diffs | Verde de texto `#14532D` | `#1E5E38` para todo texto verde; `#1E7A46` solo para sólidos | DD §1, decisión 3 |

## 3. Pantallas que el lienzo no tiene o que cambiaron

No se proponen dibujos nuevos: basta con una nota en el lienzo que remita a UI.md v2.1.

- **Editar a mano** (UI.md §4.5 bis, PA-340): el lienzo solo tiene el botón.
- **Memoria** (UI.md §4.9, PA-329): `Memoria.dc.html` es la pestaña de la v1.
- **Recibo de la suite con un CA sin caso** (UI.md §6.4): aviso «Falta un caso para CA-03.» y *Aprobar y publicar* desactivado.
- **Revisar la calidad** (UI.md §4.8, PA-404) y **Ajustes** (UI.md §10, PA-401): las diferencias ya están listadas en UI.md.
- **Ventanas estrechas** (UI.md §2, PA-335): lista en franja de 48 px y panel en capa por debajo de 1024 px útiles.

## Cómo aplicarla
1. La persona responsable del lienzo corrige las filas 1 a 9 en el artefacto y añade la nota de la sección 3.
2. Se vuelve a copiar en `docs/diseno/lienzo/` (con fecha en su README) y se cierra PA-304.
