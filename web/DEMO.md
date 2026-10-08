# Guion de la demo final de la web (T-56)

Para quien presenta la web en React (`web/`). Entre **5 y 10 minutos**: lo marcado como **imprescindible** cabe en unos 6¼ minutos, y con lo **opcional** se llega a unos 8½ (resumen al final). Los tiempos de cada paso son orientativos.

Hay dos variantes:
- **A · API simulada** (`npm run dev:mock`): todo responde en segundos y se pueden forzar casos con `?simular=`. Es la más segura.
- **B · API real** con la configuración mixta de modelos (PA-443, desde el 2026-10-08): HU, evolución y revisión de calidad con Groq **en segundos**; la suite de QA, con el modelo local, en **6–8 minutos**, así que se lleva preparada. Se hace sobre el proyecto sintético **AFQP** (Biblioteca de Villaficticia), que admite publicar de verdad (`docs/demo/HU-AFQP.md`).

Los datos son siempre ficticios: en A, proyecto `DEMO` y HU `DEMO-3`; en B, proyecto `AFQP`. Usuarios `af-demo`, `qa-demo` y `admin-demo`. En A nunca se escribe en Jira; en B solo se escribe en AFQP lo que se aprueba, si la API está en `JIRA_PUBLISH_MODE=live`.

---

## 0. Antes de empezar

### Variante A · API simulada
1. `cd web && npm ci && npm run dev:mock` y abrir `http://localhost:5173/?simular=publicado` en una ventana **InPrivate** o con un perfil nuevo (un perfil viejo puede guardar un Service Worker de MSW antiguo).
2. Entrar como `af-demo` con la contraseña ficticia `demo`. En la lista ya está «Revisar la calidad de DEMO-3 · Informe listo».
3. Tener a mano `http://localhost:5173/?simular=sin-cubrir` para la parte de QA. Al cambiar la URL se recarga la página, se pierde la sesión simulada y se vuelve a entrar, esta vez como `qa-demo`.
4. Saber que `?simular=publicado` hace que la API simulada responda como una **publicación real** («Publicado en Jira»), aunque nada sale del navegador. Es lo que permite enseñar *Ver la memoria*, que solo aparece tras publicar de verdad (ver la nota del paso 2.6).

### Variante B · API real (modelos mixtos, proyecto AFQP)
1. **Backend:** `uv run python -m api` con PostgreSQL, las migraciones y el corpus indexado (arranque diario en el `README.md`). Con `config/models.yaml` (mixta) hace falta `GROQ_API_KEY` en el `.env`. `JIRA_PUBLISH_MODE=live` publica de verdad en AFQP; con `simulation` no se escribe nada. Comprueba en *Administración → Probar conexiones* que todo está en verde y lanza una suite de prueba 10 minutos antes, para que Ollama tenga el modelo cargado.
   - **Ritmo de Groq:** su nivel gratuito admite 8000 tokens por minuto. Deja unos segundos entre una generación y la siguiente; si Groq pide esperar, el agente espera solo (hasta 60 s).
2. **Web:** `cd web && npm run dev` y abrir `http://localhost:5173` (no `127.0.0.1`) en una ventana InPrivate. Usuarios `af-demo`, `qa-demo` y `admin-demo` con las contraseñas de `core.seed_users`, que no se enseñan en pantalla.
3. **Conversaciones preparadas**, porque cada generación tarda minutos:
   - `af-demo`: con Groq, la revisión de calidad y la evolución salen en segundos y **se pueden hacer en directo**. Ten preparada igualmente una evolución ya iterada por si Groq no responde.
   - `qa-demo`: una **suite ya generada y en revisión** de una HU de AFQP **que aún no tenga casos publicados** (por ejemplo AFQP-28). **No publiques una segunda suite de AFQP-27**, que ya tiene AFQP-29…34: es el hallazgo alto de la auditoría (PA-450). Con `qwen3:1.7b`, las RN saldrán **sin caso** (el modelo no rellena `rule_ids`).
   - **Memorias reales:** AFQP-27 y AFQP-28 se publicaron de verdad el 2026-10-07 y sus memorias están **indexadas**. Si la API está en `simulation`, se enseñan desde *Memoria*; las de ejemplo de `core.memory.seed_demo` ya no hacen falta.
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

Al terminar: «Propuesta lista · Versión N · M cambios frente a Jira» y *Ver la propuesta*. En B, con Groq, sale en unos segundos; si tarda, retoma desde la lista la evolución preparada.

**2.3 · Iterar una vez (opcional).** En A: la sugerencia «Añade un criterio de error» y *Enviar*. Sale «Generando una nueva versión…» y después el resumen de la versión nueva.
> «Cada versión marca qué cambió frente a la anterior (“Cambiado en vN”, “Nueva”). La pestaña *Cambios* compara con Jira; *Impacto*, las HU afectadas; *Fuentes*, de dónde sale cada cosa.»

En B, la iteración de una HU con Groq también tarda segundos y se puede hacer en directo.

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

**En B:** retoma la suite preparada. Lo esperable es ver **RN sin caso que avisan sin bloquear**. El bloqueo por un CA sin caso no se pudo provocar contra la API real (2026-10-08, AFQP-27 y AFQP-28): antes de enseñar la suite, el agente comprueba la cobertura y pide él mismo los casos de un CA que falte (PA-426), y con HU bien escritas los cubre. El bloqueo está verificado por las pruebas del backend (`tests/unit/test_qa_coverage_retry.py`) y en la web con la API simulada: **se enseña en A**. En B se puede contar: «si faltara un caso, el agente lo pide solo; y si aun así faltara, no deja aprobar».

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
| Una generación o iteración tarda demasiado (B) | No esperes: retoma la conversación preparada desde la lista. En QA: «Con el modelo local tarda unos minutos; aquí está la de antes». Si es Groq, puede estar esperando su límite por minuto: unos segundos más y sigue. |
| Sale una tarjeta de error | Léela: el título y el mensaje son del backend, y la acción (*Reintentar*, *Actualizar*) es la que corresponde. Es parte de la demo. Si se repite, pasa a la API simulada. |
| La API real no responde, Ollama está caído o falla el inicio de sesión (varios fallos de contraseña seguidos bloquean a todos unos minutos, PA-455: reiniciar la API lo desbloquea) | Cambia al otro perfil del navegador, con la API simulada ya arrancada en `http://localhost:5174/?simular=publicado`, y sigue la variante A desde el paso en que ibas. «Os lo enseño con la API simulada, generada desde el mismo contrato.» |
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
