---
id: DOC-08
title: Especificación del módulo de préstamo digital
category: documentacion
version: 1
date: 2026-06-20
related: [DOC-01, DOC-02, DOC-03, DOC-04, DOC-09, DOC-10, DOC-14, DOC-16, DOC-21]
epics: [EP-PRESTAMO]
---

# Especificación del módulo de préstamo digital

Especificación funcional del módulo de préstamo digital de PortalVF y AppVF, que permite a las personas socias gestionar sus préstamos y reservas sin acudir al mostrador. El alcance se aprobó en el acta del 10 de junio de 2026 (DOC-21).

## Objetivo

Reducir las gestiones presenciales de reserva y renovación y ofrecer a la persona socia una vista completa de sus préstamos, reservas e historial.

## Alcance

**Incluye:**

- Reservar un título y cancelar una reserva.
- Renovar un préstamo.
- Consultar los préstamos activos y sus vencimientos.
- Consultar el historial de préstamos.

**Excluye:**

- El pago de reposiciones (se gestiona en el mostrador).
- La reserva de salas y espacios.
- El préstamo interbibliotecario.

## Actores

- **Persona socia** autenticada en PortalVF o AppVF.
- **PrestaVF**, que aplica las reglas de préstamo y reservas mediante la API interna (DOC-14).
- **AvisosVF**, que envía las notificaciones (DOC-10).

## Requisitos funcionales

### RF-PD-01. Reservar un título

1. Desde la ficha del catálogo, la persona socia pulsa «Reservar» y elige la sede de recogida.
2. El sistema valida RN-RES-01, RN-RES-02 y RN-RES-09 (DOC-02) antes de crear la reserva.
3. Si la persona ya tiene 3 reservas activas, se muestra: «Has alcanzado el máximo de 3 reservas activas. Cancela una reserva para hacer otra».
4. Si la reserva se crea, se muestra la posición en la cola y el número de ejemplares del título.

### RF-PD-02. Cancelar una reserva

1. En «Mis reservas», cada reserva activa tiene la opción «Cancelar».
2. La cancelación pide confirmación y no tiene penalización (RN-RES-07).
3. Si la reserva estaba «disponible para recoger», el ejemplar pasa de inmediato a la siguiente persona de la cola.

### RF-PD-03. Renovar un préstamo

1. En «Mis préstamos», cada préstamo muestra el botón «Renovar» y el número de renovaciones usadas, en el formato «Renovaciones: 1 de 2».
2. El botón se desactiva, con el motivo visible, cuando:
   1. hay reservas pendientes sobre el título: «No se puede renovar: otras personas están esperando este título»;
   2. se ha alcanzado el máximo: «Has usado las 2 renovaciones de este préstamo»;
   3. el préstamo está vencido: «El préstamo ha vencido. Devuélvelo en cualquier sede»;
   4. hay una suspensión activa (RN-SAN-03): «Tienes una suspensión activa hasta el día indicado».
3. Al renovar, la nueva fecha de vencimiento es la vigente más 21 días (artículo 5 de DOC-01), y se muestra de inmediato.
4. «Renovar todo» renueva los préstamos que cumplen las condiciones e informa de los que no se han podido renovar y por qué.

### RF-PD-04. Consultar los préstamos activos

1. Lista de préstamos activos con el título, la sede de préstamo, la fecha de vencimiento y las renovaciones usadas.
2. Los préstamos que vencen en 3 días o menos se destacan.
3. Los préstamos vencidos se muestran en primer lugar, con los días de retraso.

### RF-PD-05. Consultar el historial de préstamos

1. Si la persona socia no tiene activado el historial, se le ofrece activarlo, con un enlace a la política de protección de datos (DOC-04).
2. Si está activo, se muestran los préstamos devueltos de los últimos 12 meses, ordenados del más reciente al más antiguo.
3. Se puede filtrar por año y por tipo de material, y buscar por título.
4. La opción «Desactivar y borrar historial» pide confirmación y elimina todos los registros.
5. Desde una entrada del historial se puede volver a reservar el título, con las reglas de RF-PD-01.

## Requisitos no funcionales

- Las acciones de reservar, cancelar y renovar responden en menos de 2 segundos en el 95 % de los casos.
- El módulo es accesible con teclado y lector de pantalla.
- Todos los textos están en español y, en una fase posterior, en la lengua cooficial ficticia de Villaficticia.

## Reglas aplicables

| Regla | Documento | Uso en el módulo |
|---|---|---|
| Máximo 3 reservas activas | DOC-02, RN-RES-02 | RF-PD-01 |
| Bloqueo de 48 horas | DOC-02, RN-RES-05 | Aviso de disponibilidad |
| Préstamo de 21 días y 2 renovaciones | DOC-01, artículos 4 y 5 | RF-PD-03, RF-PD-04 |
| No renovar con reservas pendientes | DOC-02, RN-RES-08 | RF-PD-03 |
| Historial de 12 meses | DOC-04 | RF-PD-05 |

## Dependencias

- API interna de préstamo y reservas (DOC-14).
- Módulo de notificaciones (DOC-10).
- Catálogo en línea (DOC-09).
