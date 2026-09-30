---
id: DOC-05
title: Alta y renovación del carné de persona socia
category: procesos
version: 2
date: 2026-06-30
related: [DOC-01, DOC-04, DOC-13, DOC-16, DOC-17]
epics: [EP-SOCIOS]
---

# Alta y renovación del carné de persona socia

Proceso de negocio para dar de alta a una persona socia, renovar su carné y tramitar la baja en la Biblioteca Municipal de Villaficticia.

## Participantes

- **Persona solicitante:** quien pide el carné.
- **Personal de sala:** atiende el alta presencial y valida las solicitudes en línea.
- **SociosVF:** sistema de gestión de personas socias (ver DOC-13).
- **AvisosVF:** envía la confirmación del alta.

## Tipos de carné

| Tipo | Edad | Vigencia | Límite de préstamo |
|---|---|---|---|
| Carné general | 14 años o más | 3 años | 8 ejemplares (DOC-01) |
| Carné infantil | Menores de 14 años | 3 años o hasta cumplir 14 | 4 ejemplares de la colección infantil y juvenil |

El carné es gratuito. La primera emisión y las renovaciones no tienen coste; la reposición por pérdida tampoco.

## Alta presencial

1. La persona solicitante acude a cualquier sede con un documento identificativo en vigor.
2. El personal de sala busca en SociosVF si ya existe una ficha con ese documento, para evitar duplicados.
3. Si no existe, el personal registra los datos de identificación y contacto, y las preferencias de aviso.
4. La persona solicitante acepta la política de protección de datos (DOC-04) y decide si activa el historial de préstamos.
5. SociosVF genera el número de persona socia con el formato `SOC-` seguido de un correlativo, y el carné se imprime en el momento.
6. AvisosVF envía la confirmación del alta por el canal elegido.

Para el carné infantil, el paso 1 lo hace una persona tutora, que firma la autorización y figura como contacto.

## Alta en línea

1. La persona solicitante rellena el formulario de alta en PortalVF.
2. PortalVF comprueba el formato de los datos y envía la solicitud a SociosVF en estado «pendiente de validación».
3. La persona solicitante recibe un aviso con el plazo para validar la solicitud: **10 días naturales**.
4. En ese plazo acude a cualquier sede con el documento identificativo. El personal de sala valida los datos y entrega el carné.
5. Si no acude en 10 días, la solicitud caduca y SociosVF elimina los datos.

Mientras la solicitud está pendiente de validación, la persona solicitante puede consultar el catálogo pero no reservar ni tomar préstamos.

## Renovación del carné

1. SociosVF detecta los carnés que caducan en los próximos 30 días y AvisosVF envía un aviso a la persona socia.
2. La persona socia renueva desde PortalVF, AppVF o en el mostrador, confirmando que sus datos de contacto siguen vigentes.
3. La renovación amplía la vigencia 3 años desde la fecha de caducidad anterior.
4. Si el carné caduca sin renovarse, se conservan los datos, pero la persona socia no puede tomar préstamos, renovarlos ni reservar hasta renovarlo. Las reservas activas se mantienen hasta que caduquen.
5. Al cumplir 14 años, el carné infantil se convierte en carné general en la siguiente renovación.

## Baja

1. La persona socia pide la baja en el mostrador o desde el formulario «Privacidad» de PortalVF.
2. SociosVF comprueba que no hay préstamos pendientes de devolución ni reposiciones pendientes (RN-SAN-05).
3. Si hay préstamos pendientes, la baja queda en espera hasta su devolución.
4. Se cancelan las reservas activas y se aplican los plazos de conservación de DOC-04.

## Indicadores del proceso

- Tiempo medio de alta presencial: objetivo inferior a 10 minutos.
- Porcentaje de solicitudes en línea validadas en plazo: objetivo superior al 80 %.
