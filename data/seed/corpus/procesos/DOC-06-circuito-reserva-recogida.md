---
id: DOC-06
title: Circuito de reserva y recogida
category: procesos
version: 3
date: 2026-05-05
related: [DOC-01, DOC-02, DOC-03, DOC-09, DOC-10, DOC-14, DOC-17, DOC-19, DOC-20]
epics: [EP-PRESTAMO, EP-AVISOS]
---

# Circuito de reserva y recogida

Describe de principio a fin cómo se tramita una reserva, desde que la persona socia la solicita hasta que recoge el ejemplar o la reserva caduca. Las reglas aplicables están en el Reglamento de reservas (DOC-02). La versión 2 (2026-03-05) recoge el plazo de recogida de 48 horas acordado en el acta DOC-19; la versión 3 (2026-05-05), la consecuencia de las reservas no recogidas (RN-SAN-04) acordada en el acta DOC-20.

## Participantes

- **Persona socia:** solicita, cancela y recoge la reserva.
- **PrestaVF:** gestiona la cola de reservas y los préstamos.
- **CatálogoVF:** informa de los ejemplares y su ubicación.
- **AvisosVF:** notifica los cambios de estado.
- **Personal de sala:** prepara el ejemplar en la estantería de reservas.

## Fase 1. Solicitud

1. La persona socia busca el título en el catálogo (DOC-09) y pulsa «Reservar», o lo pide en el mostrador.
2. Elige la sede de recogida.
3. PrestaVF comprueba las condiciones:
   1. carné vigente y sin sanción que impida reservar (RN-RES-01);
   2. menos de 3 reservas activas (RN-RES-02);
   3. el título no es una obra de referencia y la persona no lo tiene ya en préstamo (RN-RES-09).
4. Si alguna condición falla, la reserva se rechaza con un mensaje que indica el motivo (ver los códigos de error en DOC-14).
5. Si todo es correcto, la reserva se crea en estado «pendiente» y la persona socia ve su posición en la cola.

## Fase 2. Espera

1. Mientras la reserva está pendiente, los préstamos de ese título no pueden renovarse (RN-RES-08).
2. La persona socia puede cancelar la reserva sin penalización (RN-RES-07).
3. Cuando se devuelve un ejemplar del título, PrestaVF lo asigna a la primera reserva de la cola (RN-RES-04).
4. Si el ejemplar está en otra sede, se genera una orden de traslado a la sede de recogida. El traslado no consume el plazo de recogida.

## Fase 3. Disponible para recoger

1. El personal de sala coloca el ejemplar en la estantería de reservas y lo marca como recibido en PrestaVF.
2. PrestaVF cambia la reserva a «disponible para recoger» y bloquea el ejemplar durante **48 horas** (RN-RES-05).
3. AvisosVF envía el aviso «Tu reserva está disponible», con la sede y la fecha y hora límite de recogida (DOC-10).

## Fase 4. Recogida o caducidad

**Recogida:**

1. La persona socia presenta el carné en el mostrador o en el punto de autopréstamo.
2. PrestaVF convierte la reserva en un préstamo de 21 días (DOC-01) y la reserva pasa a «recogida».

**Caducidad:**

1. Si pasan 48 horas sin recogida, PrestaVF marca la reserva como «caducada» (RN-RES-06).
2. La reserva cuenta como no recogida. Si es la tercera en 90 días, se aplica RN-SAN-04 (DOC-03).
3. El ejemplar se asigna a la siguiente reserva de la cola o, si no hay más, vuelve a la estantería.
4. AvisosVF notifica la caducidad a la persona socia.

## Casos particulares

- **Cierre imprevisto de la sede:** el plazo de 48 horas se amplía por el tiempo de cierre.
- **Ejemplar extraviado en el traslado:** el personal de sala reasigna otro ejemplar; la persona socia mantiene su posición.
- **Error de catalogación:** la cancelación por parte del personal no cuenta como no recogida.

## Métricas

- Tasa de reservas caducadas: objetivo inferior al 10 % mensual.
- Tiempo medio entre la devolución y la disponibilidad en la sede de recogida: objetivo inferior a 2 días hábiles.
