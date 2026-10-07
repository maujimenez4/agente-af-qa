# Guion de la demo final de la web (T-56)

Para quien presenta la web en React (`web/`). Entre **5 y 10 minutos**: lo marcado como **imprescindible** cabe en unos 6¼ minutos, y con lo **opcional** se llega a unos 8½ (resumen al final). Los tiempos de cada paso son orientativos.

Hay dos variantes:
- **A · API simulada** (`npm run dev:mock`): todo responde en segundos y se pueden forzar casos con `?simular=`. Es la más segura.
- **B · API real** en modo simulación: más convincente, pero cada generación con los modelos locales tarda minutos. Se apoya en conversaciones preparadas de antemano, que se retoman desde la lista.

Los datos son siempre ficticios (proyecto `DEMO`, HU `DEMO-3`, usuarios `af-demo`, `qa-demo` y `admin-demo`). En ninguna de las dos variantes se escribe nada en Jira.

---

## 0. Antes de empezar

### Variante A · API simulada
1. `cd web && npm ci && npm run dev:mock` y abrir `http://localhost:5173/?simular=publicado` en una ventana **InPrivate** o con un perfil nuevo (un perfil viejo puede guardar un Service Worker de MSW antiguo).
2. Entrar como `af-demo` con la contraseña ficticia `demo`. En la lista ya está «Revisar la calidad de DEMO-3 · Informe listo».
3. Tener a mano `http://localhost:5173/?simular=sin-cubrir` para la parte de QA. Al cambiar la URL se recarga la página, se pierde la sesión simulada y se vuelve a entrar, esta vez como `qa-demo`.
4. Saber que `?simular=publicado` hace que la API simulada responda como una **publicación real** («Publicado en Jira»), aunque nada sale del navegador. Es lo que permite enseñar *Ver la memoria*, que solo aparece tras publicar de verdad (ver la nota del paso 2.6).

### Variante B · API real (modo simulación)
1. **Backend:** `uv run python -m api` con PostgreSQL, las migraciones, el corpus indexado y `JIRA_PUBLISH_MODE=simulation`. Ollama tiene que estar arrancado y los modelos **ya cargados**: lanza una generación de prueba 10 minutos antes, para que la primera petición no espere a que carguen.
2. **Web:** `cd web && npm run dev` y abrir `http://localhost:5173` (no `127.0.0.1`) en una ventana InPrivate. Usuarios `af-demo`, `qa-demo` y `admin-demo` con las contraseñas de `core.seed_users`, que no se enseñan en pantalla.
3. **Conversaciones preparadas**, porque cada generación tarda minutos:
   - `af-demo`: una **revisión de calidad terminada** de la HU de la demo, y una **evolución desde «Evolucionar con esto» ya iterada una vez** (en revisión, versión 2 o posterior). En directo se retoma desde la lista; la iteración solo se cuenta.
   - `qa-demo`: una **suite de la misma HU ya generada y en revisión**. Con `qwen3:1.7b`, sus RN saldrán **sin caso** (el modelo no rellena `rule_ids`).
   - **Memorias de ejemplo** para enseñar en Memoria, porque en modo simulación no se genera ninguna. En el equipo de la principal, con `APP_ENV=development`: `uv run python -m core.memory.seed_demo` (o `--proyecto <CLAVE>` para otro proyecto). Crea dos memorias ficticias, `DEMO-9001` y `DEMO-9002`, que salen como **«No indexadas»**: no pasan por el RAG. Para quitarlas, se borran sus dos `.md` de `data/memory/`.
4. **Plan B listo** (§7): `npx vite --mode mock --port 5174` en otra terminal y `http://localhost:5174/?simular=publicado` en **otro perfil** del navegador, sin entrar todavía.
5. Comprobar el aviso «Modo de prueba» en Inicio y el anillo «consumo total» en el carril.

---

## 1. Qué hace el agente · 0:30 · imprescindible
En Inicio, con `af-demo`.

> «Es un asistente para el análisis funcional y QA. La IA propone historias de usuario y casos de prueba a partir de Jira y de la documentación; la persona los revisa, los cambia conversando o a mano, y los aprueba. **Solo se publica en Jira lo que una persona aprueba**, operación a operación. Hoy estamos en modo de prueba: no se escribe nada en Jira.»

Señala el aviso «Modo de prueba» y las cuatro tarjetas de flujo: cada rol ve las suyas.

## 2. La HU como una historia · unos 4:00
Con `af-demo`. Todo seguido, sin volver a Inicio.

| # | Paso | Tiempo | Prioridad |
|---|---|---|---|
| 2.1 | Revisar la calidad | 0:45 | Imprescindible |
| 2.2 | Evolucionar con esto (Generando) | 0:30 | Imprescindible |
| 2.3 | Iterar una vez | 0:45 | Opcional (en B, solo contarlo) |
| 2.4 | Editar a mano con nota | 0:45 | Imprescindible |
| 2.5 | Recibo con la huella | 0:45 | Imprescindible |
| 2.6 | Resultado y memoria | 0:30 | Imprescindible |

**2.1 · Revisar la calidad.** En la lista, «Revisar la calidad de DEMO-3».
> «Antes de cambiar nada, el agente revisa la HU con INVEST y contra las fuentes. Es solo lectura: no toca Jira.»

Enseña el resumen fijo («INVEST: 5 de 6 bien · 1 ambigüedad · 1 hueco»), contado sin IA a partir del veredicto, los hallazgos con su CA y su propuesta, y en *Fuentes* un extracto con formato. Que no es HTML del modelo se cuenta en §5.

**2.2 · Evolucionar con esto.** *Evolucionar DEMO-3 con esto* abre una conversación de evolución con esas mejoras.
> «La Q se llena con los pasos reales del proceso: cargar el origen, recuperar el contexto y generar.»

Al terminar: «Propuesta lista · Versión N · M cambios frente a Jira» y *Ver la propuesta*. En B, en lugar de esperar, retoma desde la lista la evolución preparada.

**2.3 · Iterar una vez (opcional).** En A: la sugerencia «Añade un criterio de error» y *Enviar*. Sale «Generando una nueva versión…» y después el resumen de la versión nueva.
> «Cada versión marca qué cambió frente a la anterior (“Cambiado en vN”, “Nueva”). La pestaña *Cambios* compara con Jira; *Impacto*, las HU afectadas; *Fuentes*, de dónde sale cada cosa.»

En B, señala en el chat la petición que ya se hizo («la iteración tarda unos minutos con el modelo local; aquí está la de antes»).

**2.4 · Editar a mano con nota.** *Editar a mano*, cambia el título y escribe una nota, por ejemplo «Título acordado con negocio». Después *Guardar la versión N+1*.
> «No todo pasa por el modelo: aquí se corrige a mano, con la misma validación que el backend. Se guarda como una versión nueva, sin llamar al modelo, y la nota queda en la conversación.»

Si sobra tiempo: con solo la nota, el pie explica «Cambia algún campo para guardar una versión nueva; la nota acompaña al cambio.». Y si se cancela con cambios, el editor pregunta antes de perderlos.

**2.5 · Recibo con la huella.** *Revisar y aprobar*. Una casilla por operación del plan: actualizar DEMO-3 con esa versión, añadir un comentario con los cambios y vincularla con DEMO-2.
> «La persona revisa operación a operación: *Aprobar y publicar* solo se activa con todas marcadas. Además, la aprobación lleva la **huella** de la versión que se ha revisado; si alguien cambiara la propuesta entretanto, la aprobación no valdría.»

Marca las tres («Todo revisado») y pulsa *Aprobar y publicar* («Aprobando y publicando…»).

**2.6 · Resultado y memoria.**
- **A, con `?simular=publicado`:** «Publicado en Jira» con las operaciones hechas, y *Ver la memoria* abre la memoria de DEMO-3: «Indexada». **Dilo en voz alta:**
  > «En la demo simulamos que la HU se ha publicado en Jira para poder enseñaros la memoria, que solo se genera al publicar. No se ha escrito nada en Jira.»
- **A, sin `?simular=`, y B:** «Aprobada · simulada», con lo que se habría hecho. **Tras una simulación no aparece *Ver la memoria***, porque la memoria se genera al publicar de verdad. Abre *Memoria* en el carril y enseña una existente: DEMO-9001 en A, o una de las de ejemplo de `seed_demo` en B («No indexada»: explícalo como «aún no está en la base de conocimiento»). Si en B no hay ninguna, sáltate la memoria.

> «Cada HU publicada deja una memoria sintética: objetivo, reglas, decisiones… *Indexada* quiere decir que ya está en la base de conocimiento, y el agente la usa como fuente prioritaria en las próximas propuestas.»

## 3. QA · unos 2:00
Cierra sesión y entra como `qa-demo`. En A, con `http://localhost:5173/?simular=sin-cubrir`.

| # | Paso | Tiempo | Prioridad |
|---|---|---|---|
| 3.1 | Origen y generar la suite | 0:30 | Imprescindible en A; en B, retomar la suite preparada |
| 3.2 | CA sin caso: aviso y recibo bloqueado | 0:45 | Imprescindible (solo A) |
| 3.3 | Pedir el caso y aprobar | 0:30 | Imprescindible (solo A) |
| 3.4 | Cobertura, datos y estrategia | 0:15 | Opcional |

**3.1 · Origen.** «Preparar pruebas» ya viene elegida para QA. Usa el reciente «DEMO-3», luego *Continuar* y *Generar la suite*.
> «Positivos y negativos son obligatorios; los casos serán subtareas de la HU con la etiqueta “caso-prueba”, y la estrategia y la matriz, adjuntos.»

**3.2 · Un CA sin caso bloquea; una RN sin caso solo avisa.** En la suite: el distintivo «1 CA y 1 RN sin caso» y el aviso «Falta un caso para CA-03…». *Revisar y aprobar* abre el recibo, pero *Aprobar y publicar* sigue desactivado aunque se marque la casilla, con el mismo aviso.
> «Cada criterio de aceptación necesita al menos un caso: sin él no se publica. Las reglas de negocio sin caso se avisan pero no bloquean. Con el modelo local pequeño (`qwen3:1.7b`) es lo normal: no rellena qué reglas verifica cada caso, y bloquear dejaría la demo parada.»

**3.3 · Pedir el caso.** *Volver a la suite*, la primera sugerencia «Añade un caso para CA-03» y *Enviar*. En la versión nueva desaparece el aviso del CA (queda «1 RN sin caso») y el recibo ya deja *Aprobar y publicar*.

**En B:** retoma la suite preparada. Lo esperable es ver **RN sin caso que avisan sin bloquear**. El bloqueo por un CA sin caso (en el backend con PA-426: «Falta al menos un caso para CA-0N: pídeselo al agente antes de aprobar.») aún no se ha comprobado contra la API real: la principal lo probará tras el cambio de modelo. Hasta entonces, en B no se enseña: se enseña en A.

**3.4 · Opcional:** *Cobertura* (la matriz CA/RN × caso, *Descargar la matriz*), *Datos y riesgos* (datos sintéticos) y *Estrategia*.

## 4. Administración · 0:45 · opcional
Entra como `admin-demo`: va directo a *Ajustes*.
- *Probar conexiones*: una fila por servicio (Jira, PostgreSQL, modelos y embeddings), con su detalle. En B es la prueba real.
- *Modelos por tarea* (solo lectura) y *Modo de publicación*: «Simulación: no se escribe nada en Jira».
- Documentos y usuarios: «Disponible pronto», con su motivo.

> «El administrador configura y comprueba, pero no genera ni publica nada.»

⚠️ **En A**, la primera fila de *Modelos por tarea* sale como «functional», en inglés: viene del ejemplo del contrato (PA-345, pendiente de la principal). No te detengas en ella. En B no pasa.

## 5. Qué enseñar de calidad · 1:00 · las tres primeras, imprescindibles
Se puede ir contando a lo largo de la demo:
- **Nada se publica sin aprobación humana:** el recibo, operación a operación, y la huella de la versión revisada (2.5).
- **Lo que llega del modelo se pinta como texto, nunca como HTML:** extractos y estrategia con formato, pero construido por la web (2.1). Ni secretos ni datos reales en el navegador; la sesión, en una cookie que la web no ve.
- **Cada versión es trazable:** quién la pidió, qué cambió, de qué fuentes sale y si se editó a mano (2.3 y 2.4).
- **Accesibilidad:** se maneja entera con el teclado, con foco visible. Las capas (lista y panel en ventanas estrechas) se cierran con Esc y no dejan tabular hacia atrás, y los avisos se anuncian a los lectores de pantalla. Revisada con axe (WCAG 2.1 A/AA) en todas las pantallas.
- **Escalado de Windows:** funciona a 1024, 1280 y 1440 px al 100, 125 y 150 %. Para enseñarlo, con Ctrl + rueda: a partir del 125 % en 1024, la lista se pliega en una franja y el panel pasa a capa.
- **Errores claros:** cada error trae su título y el mensaje del backend tal cual, con su acción (*Reintentar*, *Actualizar*…).
- **Pruebas:** unas 2.500 pruebas automáticas de la web, con la API simulada generada desde el contrato.

## 6. Lo que queda fuera · 0:20 · imprescindible
> «Queda fuera de esta entrega:»
- el **flujo unido HU → QA** (*Pedir sus pruebas a QA*): QA empieza escribiendo la clave de la HU;
- **QA 6 · Registrar la ejecución** y *Reintentar solo los fallidos*;
- **Historial** y **registro de auditoría** («disponible pronto»);
- **editar la suite de QA a mano** y el aviso «CA sin fuente»;
- **elegir el modelo por petición** (el selector está en solo lectura);
- gestionar **documentos y usuarios** desde Ajustes.

## 7. Plan B si algo falla en directo
| Si… | Entonces |
|---|---|
| Una generación o iteración tarda demasiado (B) | No esperes: retoma la conversación preparada desde la lista. «Con el modelo local tarda unos minutos; aquí está la de antes.» |
| Sale una tarjeta de error | Léela: el título y el mensaje son del backend, y la acción (*Reintentar*, *Actualizar*) es la que corresponde. Es parte de la demo. Si se repite, pasa a la API simulada. |
| La API real no responde, Ollama está caído o falla el inicio de sesión | Cambia al otro perfil del navegador, con la API simulada ya arrancada en `http://localhost:5174/?simular=publicado`, y sigue la variante A desde el paso en que ibas. «Os lo enseño con la API simulada, generada desde el mismo contrato.» |
| La API simulada da «Error inesperado» | Es un Service Worker viejo: abre una ventana InPrivate nueva. |
| Falla todo | Capturas de respaldo de cada pantalla, preparadas antes (las de la revisión general del pulido valen). |

## Resumen de tiempos
| Parte | Imprescindible | Con lo opcional |
|---|---|---|
| 1 · Qué hace el agente | 0:30 | 0:30 |
| 2 · HU (2.1, 2.2, 2.4, 2.5, 2.6 · + 2.3) | 3:15 | 4:00 |
| 3 · QA (3.1 a 3.3 · + 3.4) | 1:45 | 2:00 |
| 4 · Administración | — | 0:45 |
| 5 · Calidad (las tres primeras · todo) | 0:30 | 1:00 |
| 6 · Fuera de la entrega | 0:20 | 0:20 |
| **Total** | **≈ 6:20** | **≈ 8:35** |
