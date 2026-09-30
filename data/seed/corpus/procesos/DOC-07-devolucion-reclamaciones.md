---
id: DOC-07
title: Devolución, retrasos y reclamaciones
category: procesos
version: 2
date: 2026-05-05
related: [DOC-01, DOC-03, DOC-06, DOC-10, DOC-17, DOC-18]
epics: [EP-PRESTAMO, EP-AVISOS]
---

# Devolución, retrasos y reclamaciones

Proceso que cubre la devolución de ejemplares, la gestión de los retrasos y la tramitación de las reclamaciones de las personas socias.

## Devolución

### Canales

- Mostrador de cualquier sede.
- Puntos de autopréstamo (DOC-18).
- Buzones de devolución exteriores, disponibles cuando la sede está cerrada.
- Devolución automática de los libros electrónicos al vencer la licencia.

### Pasos en el mostrador

1. El personal de sala lee el código del ejemplar.
2. PrestaVF registra la devolución y comprueba si hay reservas pendientes sobre el título.
3. Si hay una reserva, PrestaVF indica que el ejemplar va a la estantería de reservas o a traslado (ver DOC-06).
4. Si la devolución llega con retraso, PrestaVF calcula la sanción según RN-SAN-01 y RN-SAN-02 (DOC-03).
5. El personal revisa el estado físico del ejemplar. Si detecta un deterioro grave, lo registra y se inicia el proceso de reposición (RN-SAN-05).
6. Se entrega un justificante de devolución, impreso o por aviso.

### Devolución en buzón

Los ejemplares depositados en el buzón se registran el siguiente día de apertura con la fecha de depósito, de modo que no generan retraso por el tiempo que pasan en el buzón (artículo 6 de DOC-01).

## Gestión de retrasos

1. El día siguiente al vencimiento, AvisosVF envía el aviso «Préstamo vencido» (DOC-10).
2. El aviso se repite cada 7 días mientras el ejemplar no se devuelve.
3. Si el retraso supera los 30 días, PrestaVF bloquea el carné (RN-SAN-06) y se envía un aviso específico.
4. Al devolver, se aplica la suspensión correspondiente y AvisosVF comunica la fecha de fin.

## Reclamaciones

### Motivos habituales

- Sanción que la persona socia considera indebida (por ejemplo, porque devolvió el ejemplar en el buzón a tiempo).
- Reserva caducada sin haber recibido el aviso de disponibilidad.
- Exigencia de reposición por un deterioro que ya existía.
- Errores en los datos de la ficha de persona socia.

### Procedimiento

1. La persona socia presenta la reclamación en el mostrador o desde el formulario «Reclamaciones» de PortalVF, en un plazo de **10 días hábiles** desde el hecho reclamado (RN-SAN-07).
2. PortalVF registra la reclamación con un número `REC-` y un correlativo, y envía un acuse de recibo.
3. El responsable de sala revisa la reclamación, consultando el registro de PrestaVF y, si procede, el registro de avisos de AvisosVF.
4. El responsable resuelve en un plazo máximo de 15 días hábiles:
   1. **Estimada:** se anula la sanción o se corrige el dato, y se deja constancia del motivo.
   2. **Desestimada:** se mantiene la sanción y se explica el motivo.
5. AvisosVF notifica la resolución a la persona socia.
6. Si la reclamación es por una sanción, mientras se resuelve la sanción sigue vigente, salvo que el responsable la suspenda de forma cautelar.

### Criterios de resolución

- Si el registro de AvisosVF muestra que el aviso de reserva disponible no llegó a entregarse por un fallo del sistema, la reserva caducada no cuenta como no recogida a efectos de RN-SAN-04 (DOC-03).
- Si el ejemplar consta en el buzón con fecha de depósito dentro de plazo, se anula la sanción.

## Indicadores

- Reclamaciones resueltas en plazo: objetivo del 95 %.
- Porcentaje de reclamaciones estimadas por fallo del sistema: se revisa en la comisión trimestral.
