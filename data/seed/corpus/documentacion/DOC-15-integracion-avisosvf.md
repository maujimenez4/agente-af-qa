---
id: DOC-15
title: Integración con la pasarela AvisosVF
category: documentacion
version: 2
date: 2026-07-15
related: [DOC-04, DOC-07, DOC-10, DOC-13, DOC-14, DOC-22]
epics: [EP-AVISOS]
---

# Integración con la pasarela AvisosVF

Diseño de la integración entre los sistemas de negocio (PrestaVF y SociosVF) y la pasarela de avisos AvisosVF. La versión 2 incorpora la política de reintentos y el canal por defecto aprobados en el acta técnica DOC-22.

## Visión general

1. PrestaVF y SociosVF publican eventos de negocio en la cola interna de eventos.
2. AvisosVF consume los eventos, consulta las preferencias de la persona socia en SociosVF y decide si procede enviar un aviso y por qué canales.
3. AvisosVF compone el mensaje a partir de la plantilla del aviso (DOC-10) y lo envía.
4. AvisosVF registra el resultado de cada envío.

## Eventos consumidos

| Evento | Origen | Aviso | Obligatorio |
|---|---|---|---|
| `reserva.disponible` | PrestaVF | AV-01 | Sí |
| `prestamo.proximo_vencimiento` | PrestaVF | AV-02 | No |
| `prestamo.vencido` | PrestaVF | AV-03 | Sí |
| `sancion.aplicada` | PrestaVF | AV-04 | Sí |
| `reserva.caducada` | PrestaVF | AV-05 | Sí |
| `carne.proximo_caducar` | SociosVF | AV-06 | No |
| `reclamacion.resuelta` | PortalVF | AV-07 | Sí |

## Estructura de un evento

```json
{
  "evento": "reserva.disponible",
  "id_evento": "EVT-000187",
  "fecha": "2026-07-20T10:15:00",
  "socio_id": "SOC-0007",
  "datos": {
    "titulo": "El faro de Villaficticia",
    "sede_recogida": "Sede Norte",
    "limite_recogida": "2026-07-22T10:15:00"
  }
}
```

El evento no incluye datos de contacto: AvisosVF los obtiene de SociosVF en el momento del envío, para respetar los cambios de preferencias.

## Reglas de procesamiento

1. **Idempotencia:** AvisosVF descarta un evento cuyo `id_evento` ya ha procesado.
2. **Agrupación:** los eventos `prestamo.proximo_vencimiento` del mismo día y persona socia se agrupan en un único aviso.
3. **Franja horaria:** los avisos no obligatorios generados entre las 22:00 y las 8:00 se retienen hasta las 8:00.
4. **Canal por defecto:** si la persona socia no ha configurado preferencias, se usa el correo electrónico (DOC-22).

## Política de reintentos

Aprobada en el acta técnica DOC-22:

1. Si un envío falla por un error temporal del canal, AvisosVF reintenta hasta **3 veces**.
2. Las esperas entre intentos son de 5, 15 y 60 minutos.
3. Si la persona socia tiene activo otro canal, tras el segundo fallo se envía también por ese canal.
4. Tras el tercer reintento fallido, el aviso queda como «no entregado», visible en la bandeja de PortalVF, y se genera una alerta para el equipo técnico.
5. Los errores permanentes (dirección inexistente, app desinstalada) no se reintentan y se marca el canal como «a revisar» en SociosVF.

## Registro de envíos

- Cada envío guarda: identificador del evento, tipo de aviso, canal, fecha, resultado y número de intentos.
- El registro no guarda el contenido completo del mensaje, solo el tipo de aviso y los identificadores.
- Se conserva 6 meses (DOC-04) y se consulta para resolver reclamaciones (DOC-07).

## Picos de carga

El recordatorio AV-02 se genera para todos los préstamos que vencen en 3 días, a las 9:00. Para evitar picos, AvisosVF envía en lotes de 500 avisos por minuto.

## Supervisión

- Porcentaje de avisos entregados al primer intento: objetivo superior al 98 %.
- Tiempo desde el evento hasta el envío de los avisos inmediatos: inferior a 5 minutos.
