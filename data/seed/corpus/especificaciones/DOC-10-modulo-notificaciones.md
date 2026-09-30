---
id: DOC-10
title: Especificación del módulo de notificaciones
category: especificaciones
version: 2
date: 2026-07-15
related: [DOC-02, DOC-03, DOC-04, DOC-05, DOC-06, DOC-07, DOC-15, DOC-19, DOC-20, DOC-21, DOC-22]
epics: [EP-AVISOS]
---

# Especificación del módulo de notificaciones

Especificación funcional de los avisos que el servicio digital envía a las personas socias a través de AvisosVF. La versión 1 ya incluía la fecha y hora límite en el aviso de reserva disponible (acta DOC-19) y el contador de reservas no recogidas en el aviso de reserva caducada (acta DOC-20). La versión 2 incorpora el recordatorio previo al vencimiento (acta DOC-21) y la política de reintentos y el canal por defecto (acta DOC-22).

## Objetivo

Que la persona socia conozca a tiempo cualquier hecho que requiera una acción suya: recoger una reserva, devolver o renovar un préstamo, o conocer una sanción.

## Canales

| Canal | Uso | Por defecto |
|---|---|---|
| Correo electrónico | Todos los avisos | Sí |
| Notificación de AppVF | Todos los avisos, si la app está instalada | No |
| Aviso en PortalVF | Bandeja de avisos al iniciar sesión | Siempre activo |

Los mensajes de texto al teléfono móvil no se usan, por decisión del acta DOC-22.

## Catálogo de avisos

### AV-01. Reserva disponible

- **Evento:** la reserva pasa a «disponible para recoger» (RN-RES-05, DOC-02).
- **Momento:** inmediato.
- **Contenido:** título, sede de recogida y fecha y hora límite de recogida (48 horas desde la disponibilidad).
- **Obligatorio:** sí; la persona socia no puede desactivarlo.

### AV-02. Recordatorio de vencimiento

- **Evento:** un préstamo vence en 3 días.
- **Momento:** a las 9:00, 3 días antes del vencimiento.
- **Contenido:** títulos que vencen y si pueden renovarse; si no, el motivo (por ejemplo, reservas pendientes).
- **Obligatorio:** no; puede desactivarse en las preferencias.

### AV-03. Préstamo vencido

- **Evento:** un préstamo no se ha devuelto en la fecha de vencimiento.
- **Momento:** el día siguiente al vencimiento y, después, cada 7 días (DOC-07).
- **Contenido:** títulos vencidos, días de retraso y recordatorio de RN-SAN-01.
- **Obligatorio:** sí.

### AV-04. Sanción aplicada

- **Evento:** PrestaVF registra una sanción: una suspensión (RN-SAN-01, RN-SAN-05) o una restricción de reservas (RN-SAN-04).
- **Momento:** inmediato.
- **Contenido:** tipo de sanción (suspensión o restricción de reservas), fecha de fin y cómo reclamar (RN-SAN-07).
- **Obligatorio:** sí.

### AV-05. Reserva caducada

- **Evento:** una reserva caduca sin recogida (RN-RES-06).
- **Momento:** inmediato.
- **Contenido:** título y número de reservas no recogidas en los últimos 90 días, con la advertencia de RN-SAN-04.
- **Obligatorio:** sí.

### AV-06. Carné próximo a caducar

- **Evento:** el carné caduca en 30 días (DOC-05).
- **Momento:** a las 9:00.
- **Obligatorio:** no.

### AV-07. Resolución de reclamación

- **Evento:** el responsable de sala resuelve una reclamación (DOC-07).
- **Momento:** inmediato.
- **Obligatorio:** sí.

## Preferencias

1. En «Mis preferencias» la persona socia elige los canales y activa o desactiva los avisos no obligatorios.
2. Debe haber siempre al menos un canal activo además del aviso en PortalVF.
3. Los cambios se aplican a los avisos generados a partir de ese momento.

## Reglas de envío

1. Los avisos se agrupan: si el mismo día vencen varios préstamos, se envía un único AV-02.
2. Los avisos no obligatorios no se envían entre las 22:00 y las 8:00.
3. Si el envío falla, AvisosVF reintenta según la política de DOC-15 y DOC-22. Tras el último reintento fallido, el aviso queda registrado como «no entregado» y visible en PortalVF.
4. Todos los envíos quedan registrados durante 6 meses (DOC-04), para poder resolver reclamaciones.

## Requisitos no funcionales

- Los avisos inmediatos se envían en menos de 5 minutos desde el evento.
- Los textos están redactados en lenguaje claro y no incluyen datos personales distintos del nombre de pila.
