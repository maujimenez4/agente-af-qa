# Comparativa de modelos · argumentos de tiempo, coste y calidad

Anexo del dossier para dirección (`DOSSIER.md`). Reúne lo que se midió y se investigó entre el 2 y el 8 de octubre de 2026 para decidir dónde corre el modelo del agente. Solo hechos del repositorio o de fuentes citadas; las estimaciones se marcan como tales.

## 1. En cuatro cifras

| | Dato | Fuente |
|---|---|---|
| **Una HU nueva** | de **~4–5 min** (modelo local) a **13 s** (Groq, medido el 2026-10-09) | `docs/pruebas/medidas-groq-vs-local-2026-10-07.md` |
| **Evolucionar una HU** | de **~5 min** (local) a **15 s** (Groq, medido el 2026-10-09) | ídem |
| **Una suite de QA** | **~8,5 min** en local, la configuración actual (con Groq, 41 s, pero no cabe en su nivel gratuito) | ídem |
| **Coste de modelo hoy** | **0 €**: modelos open-weight gratuitos (local y nivel gratuito de Groq) | decisión D-14, `config/README.md` |
| **Coste estimado con un modelo de pago** | de **~1,5 $** (GPT-6 Luna, Groq de pago) a **~58 $** (Claude Opus 5.5) por 1000 operaciones | estimación del §5 |

## 2. Qué se comparó y cómo

- **Modelo local:** `qwen3:1.7b` (respaldo `phi4-mini`) con Ollama en Docker, **solo CPU**, en el portátil de desarrollo. Datos privados: nada sale del equipo.
- **Groq (nube, nivel gratuito):** `gpt-oss-120b` y `gpt-oss-20b`, modelos open-weight servidos por un tercero.
- **Comerciales (solo como referencia):** Anthropic (Claude Haiku 4.5, Sonnet 5.5 y Opus 5.5), OpenAI (GPT-6.1 Sol y GPT-6 Luna) y Google (Gemini 3.1 Pro y Gemini 3.8 Flash). **No se han probado**: es una estimación con los tokens reales del agente.

**Datos medidos:**
- tiempos por operación, de las trazas de Langfuse (29 operaciones locales, 5–7 oct, mediana) y del registro de la API;
- tokens, de la tabla `llm_usage` (91 llamadas locales del 2 al 7 de octubre, y las de Groq del 7 de octubre);
- calidad, por revisión humana de las propuestas en el proyecto sintético AFQP.

Mismo agente, mismas instrucciones (`prompts/`), misma base de conocimiento.

## 3. Tiempos medidos

| Operación | Local `qwen3:1.7b` (mediana) | Groq `gpt-oss` (medido) | Mejora |
|---|---|---|---|
| HU nueva | 4,0 min (llamada de generación: 5,1 min) | **13,1 s** | ~18× |
| Evolucionar una HU | 5,2 min | **14,5 s** | ~21× |
| Revisión de calidad (INVEST) | 7,2 min | **10,8 s** | ~40× |
| Suite de QA | 8,3 min (el 2026-10-09: 8 min 28 s) | **41 s** (7-10; hoy va en local) | ~12× |
| Iterar una suite | 5,3 min | **no cabe** en el nivel gratuito (§6) | — |
| Memoria al publicar | 1,4 min | **3 s** | ~28× |

Tiempos de Groq medidos de extremo a extremo (contexto, modelo y validación) el 2026-10-09 con la configuración mixta actual: HU nueva en AFQP, evolución de AFQP-3 y calidad de AFQP-27. La memoria y la suite con Groq son del 2026-10-07.

Además, en total: **4 h 52 min de modelo** en las 91 llamadas locales, frente a unos **14 min** estimados con un modelo en la nube.

## 4. Calidad observada (misma petición, distinto modelo)

| Caso | Local `qwen3:1.7b` | Groq `gpt-oss-120b` |
|---|---|---|
| HU de préstamo de libros electrónicos (AFQP-27) frente a la de reservas (AFQP-28) | **Copió los criterios de otra HU** (HU-08, búsqueda en el catálogo), duplicó el Gherkin y se inventó una regla («2 renovaciones»): hubo que reescribirla a mano | **Casi lista**: 5 CA propios y bien construidos, números exactos y una regla deducida con criterio; solo retoques de redacción |
| Revisión de calidad de AFQP-27 | — | 6 hallazgos útiles, con propuestas de criterios nuevos (PA-445) |
| Suite de AFQP-27 y AFQP-28 | 6 y 5 casos, **un caso por criterio**; las reglas de negocio sin caso | — (la suite con Groq llegó a revisión con la HU recortada, PA-442, ya corregido) |
| Seguir una instrucción concreta («quita el caso CP-06») | **No la siguió** | — |

**Lectura:** el cuello de botella de calidad era el **modelo**, no el agente. El modelo pequeño copia cuando las fuentes se parecen a lo que se pide, y obedece peor las instrucciones.

## 5. Coste

### 5.1 Hoy
**0 €** en modelos: todos son open-weight y gratuitos (D-14). El modelo local solo consume la CPU del equipo; Groq, su nivel gratuito.

### 5.2 Estimación con modelos comerciales y con Groq de pago (referencia)
Con los **tokens reales** de cada operación del agente (medias de `llm_usage`: HU nueva 5005 de entrada / 1880 de salida; evolucionar 4138 / 1788; suite 6915 / 2244; iterar una suite 4846 / 1350; calidad 7151 / 1729) y los **precios oficiales** por millón de tokens (entrada / salida), consultados en octubre de 2026:

| Modelo | Proveedor | Tipo | $/M entrada · salida | HU nueva | Suite de QA | Calidad | **1000 operaciones** |
|---|---|---|---|---|---|---|---|
| qwen3:1.7b (local) | Ollama | Open-weight · **medido** | — | 4 min | 8,3 min | 7,2 min | **0 $** |
| gpt-oss (nivel gratuito) | Groq | Open-weight · **medido** | 0 · 0 | 13 s | 41 s | 11 s | **0 $** |
| gpt-oss-120b (de pago) | Groq | Open-weight | 0,15 · 0,60 | ~13 s | ~41 s | ~11 s | **~1,92 $** |
| GPT-6 Luna | OpenAI | Comercial · estimado | 0,10 · 0,50 | ~19 s | ~22 s | ~18 s | **~1,46 $** |
| Gemini 3.8 Flash | Google | Comercial · estimado | 0,75 · 3,75 ¹ | ~20 s | ~23 s | ~18 s | **~10,95 $** ¹ |
| Claude Haiku 4.5 | Anthropic | Comercial · estimado | 1 · 5 | ~19 s | ~22 s | ~17 s | **~14,60 $** |
| Claude Sonnet 5.5 | Anthropic | Comercial · estimado | 2 · 10 | ~18 s | ~21 s | ~17 s | **~29,20 $** |
| GPT-6.1 Sol | OpenAI | Comercial · estimado | 2 · 10 | ~38 s | ~44 s | ~35 s | **~29,20 $** |
| Gemini 3.1 Pro | Google | Comercial · estimado | 2 · 12 | ~20 s | ~23 s | ~19 s | **~32,80 $** |
| Claude Opus 5.5 | Anthropic | Comercial · estimado | 4 · 20 | ~26 s | ~29 s | ~24 s | **~58,41 $** |

¹ Precio de lanzamiento hasta el 31-12-2026; se duplica el 1-1-2027 (~21,90 $ por 1000 operaciones).

**Cómo se estimó el tiempo:** latencia inicial por llamada + tokens de salida ÷ velocidad. Velocidades de Artificial Analysis (octubre de 2026): Haiku 4.5 ~108 tokens/s, Sonnet 5.5 ~125, Opus 5.5 ~96, GPT-6.1 Sol 55,6, GPT-6 Luna 127,5, Gemini 3.1 Pro 115,3 y Gemini 3.8 Flash 120,2. Latencia inicial: Claude 0,7 / 1,5 / 3 s; OpenAI y Gemini, 2 s supuestos con razonamiento bajo (con el razonamiento al máximo, Artificial Analysis mide entre 25 y 314 s antes de la primera palabra).

**Fuentes de precios:** Anthropic (tabla de precios de la API), OpenAI (`developers.openai.com/api/docs/pricing`), Google (`ai.google.dev/gemini-api/docs/pricing`, actualizado el 2026-10-07). Groq de pago: fuente secundaria (`usagepricing.com`); confirmar en Groq.

**Márgenes:** ±20 % por la forma de contar tokens de cada modelo. Un modelo más capaz probablemente necesitaría menos reintentos. Aprobar y editar a mano no llaman al modelo: no cuestan nada con ninguno.

**Lectura:** los modelos pequeños de la nube (GPT-6 Luna, Groq de pago) cuestan menos de 2 $ por 1000 operaciones; los grandes, entre 29 y 58 $. En todos los casos, céntimos por HU o suite frente al tiempo de las personas.

**Gráfica:** `grafica-comparativa.html`, en esta carpeta (se abre en el navegador).

## 6. Límites del nivel gratuito de Groq (comprobados el 2026-10-07)

| Modelo | Límite | Efecto en el agente |
|---|---|---|
| `gpt-oss-120b` | **8000 tokens por minuto** (entrada + salida prevista) | La HU y la revisión de calidad caben; la suite cabe ajustando contexto y salida; **iterar una suite no cabe** (~9500 tokens) |
| `qwen3.8-27b` (en Groq) | **1000 tokens de salida por minuto** | No sirve para generar HU ni suites |
| Cuota diaria | independiente por modelo | Una HU gasta ~13 500 tokens: unas 12 operaciones al día sin agotar el aviso interno |

**Solución adoptada (PA-443):** configuración **mixta**: Groq para HU, evolución, calidad, impacto y memoria; local para QA y como respaldo de todo; esperar a Groq antes de pasar al local. Fuente: `config/README.md`.

## 7. Opciones de despliegue

| Opción | Velocidad | Calidad | Privacidad | Coste de modelo | Cumple D-14 | Comentario |
|---|---|---|---|---|---|---|
| **Todo local (CPU)** | Minutos | Baja con modelos pequeños | **Total**: nada sale | 0 € | Sí | Viable solo para demostración o volúmenes muy bajos |
| **Mixta (actual)** | Segundos en HU, minutos en QA | Buena en HU | La HU sale a Groq | 0 € | Sí | Solo con datos sintéticos (`config/README.md`) |
| **Groq de pago (Dev Tier)** | Segundos en todo | Buena | Sale a un tercero | ~1,9 $ / 1000 operaciones (a confirmar) | Sí | Quita el límite por minuto; mismo código |
| **GPU propia o en la nube privada** con modelos open-weight | Segundos | Depende del modelo | **Total** | Coste de la GPU | Sí | El agente no cambia: solo la configuración |
| **Modelo comercial** (Anthropic, OpenAI o Google, por API o por una plataforma corporativa) | Segundos | Alta (estimación) | Sale a un tercero, con acuerdo de tratamiento de datos | ~1,5–58 $ / 1000 operaciones | **No** (requiere revisar D-14) | Estimado, no probado |

**Lo que no cambia en ninguna opción:** el agente cambia de modelo solo por configuración (`MODELS_CONFIG_PATH`, `config/README.md`), sin tocar código, y siempre con aprobación humana antes de publicar.

## 8. Argumentos para la presentación

1. **La velocidad depende del modelo, no del agente:** el mismo agente pasa de minutos a segundos al cambiar de modelo, sin tocar código.
2. **El coste por operación es marginal:** céntimos por HU o suite incluso con un modelo comercial. El coste relevante es el tiempo de las personas.
3. **La privacidad es una decisión de despliegue:** se puede tener todo dentro de la empresa (local o GPU propia) o ir más rápido con un tercero y un acuerdo de datos.
4. **La calidad sube con el modelo,** y la aprobación humana protege en cualquier caso: nada llega a Jira sin revisión.

## 9. Lo que falta para cerrar la comparativa

- **Precio real de Groq Dev Tier** y de una GPU (propia o en la nube) para el volumen esperado.
- **Medir con un modelo comercial de verdad** (no estimado) sobre las mismas HU de AFQP.
- **Medir con un modelo open-weight mediano en GPU** (p. ej. `gpt-oss-120b` en infraestructura propia).
- **Volumen mensual esperado** de HU y suites, para pasar del coste por operación al coste mensual.
- **Política de la empresa** sobre enviar requisitos a un proveedor en la nube.
