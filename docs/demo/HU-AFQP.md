# HU de la demo en AFQP (Biblioteca de Villaficticia)

Guion de las historias que se crean **a través del agente** en el proyecto sintético AFQP de Jira, en modo `live` y siempre con aprobación humana. Todos los datos son inventados (D-06): no hay personas, organizaciones ni sistemas reales.

El orden importa: la 2 aprovecha la memoria que deja la 1 al publicarse (ciclo de aprendizaje), y la 5 y la 6 trabajan sobre la 1.

Antes de empezar:
1. `JIRA_PUBLISH_MODE=live` en el `.env` (lo cambia el usuario) y reiniciar la API. ✅ Hecho el 2026-10-07.
2. Borrar en Jira las HU de prueba `[PRUEBA-AGENTE]` (AFQP-18, 19, 20, 23 y 25). ✅ Hecho el 2026-10-07.
3. PA-432 fusionada (la misma HU se estructura igual en el ensayo y en la demo). ✅
4. Modelos mixtos (PA-443): HU, evolución y calidad con Groq (segundos); QA con el modelo local (6–8 min), así que la suite se lleva preparada.
5. **No publicar una segunda suite de una HU que ya tiene casos** (AFQP-27 tiene AFQP-29…34) hasta cerrar PA-450: se daría por publicada sin llegar a Jira.

Anota en la tabla final la clave que Jira asigne a cada una.

---

## 1 · HU nueva desde texto libre: préstamo de libros electrónicos
**Pantalla:** Nueva HU · **Enseña:** generación con fuentes del RAG; al publicar, memoria indexada.

Texto para pegar:

> Queremos que las personas socias puedan tomar prestados libros electrónicos desde el catálogo en línea. Cada persona puede tener como máximo 3 libros electrónicos prestados a la vez. El préstamo dura 21 días y, al vencer, el libro se devuelve solo, sin que la persona tenga que hacer nada. Se puede devolver antes desde «Mis préstamos». Si la persona tiene el carné caducado, no puede tomar prestado ningún libro electrónico. Los libros electrónicos tienen un número limitado de licencias: si todas están prestadas, el libro aparece como «Agotado».

Esperado: CA de préstamo correcto, límite de 3, vencimiento a los 21 días, devolución anticipada y carné caducado; RN con los límites. Aprobar y publicar.

## 2 · HU nueva que reaprovecha la 1: reservar un libro electrónico agotado
**Pantalla:** Nueva HU · **Enseña:** el RAG recupera la memoria de la HU 1 (fuente «memoria») y respeta sus reglas.

Texto para pegar:

> Cuando un libro electrónico está agotado, la persona socia debe poder reservarlo para que se le preste en cuanto quede una licencia libre. Las reservas se atienden por orden de llegada. Cuando le toca, la persona recibe un aviso y tiene 48 horas para confirmar el préstamo; si no confirma, pasa a la siguiente persona de la lista. Una persona no puede tener más de 2 reservas de libros electrónicos a la vez.

Esperado: en las fuentes aparece la memoria de la HU 1 (límite de 3 préstamos, licencias). Aprobar y publicar.

## 3 · Revisar la calidad de una HU mal escrita: pagar las multas en línea
**Pantalla:** Nueva HU (o crearla primero así en Jira y abrir «Revisar calidad») · **Enseña:** informe INVEST con problemas concretos y mejora iterando.

Texto (vago a propósito):

> Como socio quiero pagar las multas por internet para no tener que ir a la biblioteca. Tiene que ser rápido y seguro y funcionar con los medios de pago habituales. Si hay algún problema se avisa a alguien.

Esperado: la revisión señala que no hay importes, ni plazos, ni medios de pago concretos, ni CA verificables, y que «avisar a alguien» es ambiguo. Iterar con:

> Las multas son de 0,20 € por día de retraso y libro, con un máximo de 6 € por libro. Se paga con tarjeta o con el monedero de la biblioteca. Si el pago falla, se muestra el motivo y la multa sigue pendiente. Mientras una persona tenga multas por más de 3 €, no puede tomar prestados libros.

## 4 · Evolucionar una HU existente: renovar un préstamo
**Pantalla:** Evolucionar · **HU de partida:** AFQP-3, HU-02 «Renovar un préstamo» (la sembrada en AFQP) · **Enseña:** comparación entre versiones e impacto en HU-01 «Reservar un libro disponible» (vínculo «relates to»).

Cambio que se pide:

> Añade que un préstamo no se puede renovar si otra persona socia tiene ese libro reservado. En ese caso se muestra el mensaje «No se puede renovar: este libro está reservado por otra persona» y se indica la fecha de devolución.

Esperado: CA nuevo o modificado, la regla nueva y el impacto en HU-01. Aprobar y publicar: actualiza la HU, añade el comentario y crea el vínculo.

## 5 · Suite de QA con valores límite
**Pantalla:** QA · **HU de partida:** la HU 1 · **Enseña:** casos por CA, cobertura completa y subtareas `caso-prueba` con la estrategia y la matriz adjuntas.

Esperado: valores límite con 2, 3 y 4 préstamos simultáneos; día 21 y día 22 del préstamo; carné caducado; libro agotado. Comprobar que cada CA tiene al menos un caso antes de aprobar (PA-426). Aprobar y publicar.

## 6 · Iterar la suite delante del público
**Pantalla:** Iterar sobre la suite de la 5 · **Enseña:** una iteración corta.

Mensaje:

> Añade un caso de devolución anticipada: la persona devuelve el libro el día 5 desde «Mis préstamos» y la licencia queda libre para la siguiente reserva.

---

## Claves asignadas en Jira

| # | HU | Clave AFQP | Publicada |
|---|---|---|---|
| 1 | Préstamo de libros electrónicos | AFQP-27 | 2026-10-07 · generada con qwen3:1.7b y editada a mano |
| 2b | Reservar un libro electrónico agotado (generada con Groq) | AFQP-28 | 2026-10-07 · gpt-oss-120b, retoques a mano |
| 2 | Reservar un libro electrónico agotado | | |
| 3 | Pagar las multas en línea | | |
| 4 | Renovar un préstamo (evolución de HU-02) | | |
| 5 | Suite de QA de la 1 | AFQP-29 … AFQP-34 (subtareas de AFQP-27) | 2026-10-08 · qwen3:1.7b, 6 casos, un CA por caso; 5 RN sin caso (avisan sin bloquear) |
| 6 | Iteración de la suite | | |
