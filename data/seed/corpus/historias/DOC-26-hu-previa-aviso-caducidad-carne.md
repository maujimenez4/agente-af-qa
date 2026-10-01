---
id: DOC-26
title: HU previa · Avisar de que el carné va a caducar
category: historias
version: 1
date: 2025-12-04
related: [DOC-05, DOC-10, DOC-15]
epics: [EP-SOCIOS, EP-AVISOS]
---

# HU previa · Avisar de que el carné va a caducar

Historia de usuario del proyecto anterior de avisos (referencia interna HU-ANT-12), ya implantada. Se conserva como antecedente para nuevas HU de gestión del carné.

## Historia

**Como** persona socia, **quiero** recibir un aviso cuando mi carné esté a punto de caducar **para** renovarlo a tiempo y no perder el acceso al préstamo.

## Criterios de aceptación

- **CA-01 · Antelación.** Dado un carné que caduca dentro de 30 días, cuando SociosVF hace su revisión diaria, entonces AvisosVF envía un aviso a la persona socia (DOC-05).
- **CA-02 · Un solo aviso.** Dado un carné ya avisado, cuando la revisión diaria se repite, entonces no se envía un segundo aviso.
- **CA-03 · Carné infantil.** Dado un carné infantil, cuando se genera el aviso, entonces se envía al contacto de la persona tutora.

## Reglas de negocio

- **RN-01.** La renovación amplía la vigencia 3 años desde la fecha de caducidad anterior (DOC-05).
- **RN-02.** Con el carné caducado no se puede tomar en préstamo, renovar ni reservar (DOC-05).

## Decisiones

- El aviso usa los canales elegidos en las preferencias de aviso (DOC-10).

## Estado

Implantada. Pendiente como mejora: un segundo recordatorio 7 días antes (no aprobada).

## Notas para nuevas HU

- Una HU nueva de renovación del carné debe partir de este aviso: el enlace del aviso lleva a la renovación en PortalVF o AppVF (DOC-05).
- Si la persona socia renueva antes de que caduque el carné, la vigencia se amplía desde la fecha de caducidad anterior, no desde la fecha de la renovación.
- Al cumplir 14 años, el carné infantil se convierte en carné general en la siguiente renovación; el aviso de esa renovación ya se envía a la propia persona socia.
- El texto del aviso no incluye datos personales más allá del número de persona socia y la fecha de caducidad.
