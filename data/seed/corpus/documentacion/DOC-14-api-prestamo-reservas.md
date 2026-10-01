---
id: DOC-14
title: API interna de préstamo y reservas
category: documentacion
version: 1
date: 2026-06-25
related: [DOC-01, DOC-02, DOC-03, DOC-05, DOC-08, DOC-12, DOC-13, DOC-15]
epics: [EP-PRESTAMO]
---

# API interna de préstamo y reservas

Contrato de la API interna que expone PrestaVF a los canales del servicio digital (PortalVF, AppVF y puntos de autopréstamo). Es una API interna y ficticia; no está publicada fuera de la red municipal.

## Datos generales

- **URL base:** `https://api.villaficticia.invalid/prestamo/v1`
- **Formato:** JSON en UTF-8.
- **Autenticación:** sesión de persona socia emitida por SociosVF o identidad de servicio de cada terminal de autopréstamo. Las credenciales nunca se incluyen en la documentación ni en los registros.
- **Fechas:** formato ISO 8601, zona horaria de Villaficticia.
- **Códigos de estado:** los de DOC-12.

## Recursos

### Préstamos

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/socios/{socio_id}/prestamos` | Préstamos activos de la persona socia |
| POST | `/prestamos/{prestamo_id}/renovaciones` | Renovar un préstamo |
| POST | `/socios/{socio_id}/renovaciones` | Renovar todos los préstamos renovables |
| GET | `/socios/{socio_id}/historial` | Historial de préstamos (solo si está activo) |
| DELETE | `/socios/{socio_id}/historial` | Desactivar y borrar el historial |

### Reservas

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/socios/{socio_id}/reservas` | Reservas de la persona socia |
| POST | `/reservas` | Crear una reserva (título y sede de recogida) |
| DELETE | `/reservas/{reserva_id}` | Cancelar una reserva |
| GET | `/titulos/{titulo_id}/cola` | Número de reservas pendientes de un título |

### Sanciones

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/socios/{socio_id}/sanciones` | Sanciones activas y sus fechas de fin |

## Ejemplo: renovar un préstamo

Petición:

```http
POST /prestamo/v1/prestamos/PR-0042/renovaciones
```

Respuesta correcta (200):

```json
{
  "prestamo_id": "PR-0042",
  "estado": "PR-REN",
  "renovaciones_usadas": 1,
  "renovaciones_maximas": 2,
  "vencimiento_anterior": "2026-07-10",
  "vencimiento_nuevo": "2026-07-31"
}
```

La nueva fecha se calcula sumando 21 días al vencimiento anterior (artículo 5 de DOC-01).

## Ejemplo: crear una reserva

```json
{
  "titulo_id": "TIT-0815",
  "sede_recogida": "SEDE-NORTE"
}
```

Respuesta correcta (201): identificador de la reserva, estado `RS-PEN` y posición en la cola.

## Errores de negocio

Todos los errores devuelven un cuerpo con `codigo` y `mensaje`. El `mensaje` está redactado en español para mostrarlo tal cual en los canales.

| HTTP | Código | Regla | Mensaje |
|---|---|---|---|
| 409 | `RESERVA_LIMITE` | RN-RES-02 | Has alcanzado el máximo de 3 reservas activas |
| 409 | `RESERVA_YA_EN_PRESTAMO` | RN-RES-09 | Ya tienes este título en préstamo |
| 422 | `RESERVA_NO_PRESTABLE` | RN-RES-09 | Esta obra es solo de consulta en sala |
| 409 | `RENOVACION_RESERVAS_PENDIENTES` | RN-RES-08 | No se puede renovar: otras personas están esperando este título |
| 409 | `RENOVACION_MAXIMO` | DOC-01, art. 5 | Has usado las 2 renovaciones de este préstamo |
| 409 | `RENOVACION_VENCIDO` | DOC-01, art. 5 | El préstamo ha vencido |
| 403 | `SOCIO_SANCIONADO` | RN-SAN-03 | Tienes una suspensión activa |
| 403 | `SOCIO_SIN_RESERVAS` | RN-SAN-04 | No puedes hacer reservas hasta la fecha indicada |
| 403 | `CARNE_NO_VIGENTE` | DOC-05 | Tu carné no está vigente |
| 404 | `NO_ENCONTRADO` | — | El recurso no existe |

## Eventos publicados

PrestaVF publica estos eventos para AvisosVF (DOC-15):

- `reserva.disponible` (con la fecha y hora límite, 48 horas después)
- `reserva.caducada`
- `prestamo.proximo_vencimiento` (3 días antes)
- `prestamo.vencido`
- `sancion.aplicada`

## Versionado

Los cambios incompatibles publican una nueva versión en la ruta (`/v2`). La versión anterior se mantiene 6 meses.
