# Comparativa de modelos · argumentos de tiempo, coste y calidad

Anexo del dossier para dirección (`DOSSIER.md`). Reúne lo que se midió y se investigó entre el 2 y el 8 de octubre de 2026 para decidir dónde corre el modelo del agente. Solo hechos del repositorio o de fuentes citadas; las estimaciones se marcan como tales.

## 1. En cuatro cifras

| | Dato | Fuente |
|---|---|---|
| **Una HU nueva** | de **~4–5 min** (modelo local) a **11 s** (Groq) | `docs/pruebas/medidas-groq-vs-local-2026-10-07.md` |
| **Una suite de QA** | de **~8 min** (local) a **41 s** (Groq, con esperas por su límite) | ídem |
| **Coste de modelo hoy** | **0 €**: modelos open-weight gratuitos (local y nivel gratuito de Groq) | decisión D-14, `config/README.md` |
| **Coste estimado con un modelo comercial** | **~0,03 $ por suite** con Claude Sonnet 5.5; **~30 $ al mes** por 1000 operaciones | estimación del §5 |

## 2. Qué se comparó y cómo

- **Modelo local:** `qwen3:1.7b` (respaldo `phi4-mini`) con Ollama en Docker, **solo CPU**, en el portátil de desarrollo. Datos privados: nada sale del equipo.
- **Groq (nube, nivel gratuito):** `gpt-oss-120b` y `gpt-oss-20b`, modelos open-weight servidos por un tercero.
- **Claude (comercial, solo como referencia):** Haiku 4.5, Sonnet 5.5 y Opus 5.5. **No se ha probado**: es una estimación con los tokens reales del agente.

**Datos medidos:**
- tiempos por operación, de las trazas de Langfuse (29 operaciones locales, 5–7 oct, mediana) y del registro de la API;
- tokens, de la tabla `llm_usage` (91 llamadas locales del 2 al 7 de octubre, y las de Groq del 7 de octubre);
- calidad, por revisión humana de las propuestas en el proyecto sintético AFQP.

Mismo agente, mismas instrucciones (`prompts/`), misma base de conocimiento.

## 3. Tiempos medidos

| Operación | Local `qwen3:1.7b` (mediana) | Groq `gpt-oss` (medido) | Mejora |
|---|---|---|---|
| HU nueva | 4,0 min (llamada de generación: 5,1 min) | **11 s** | ~25× |
| Evolucionar una HU | 5,2 min | segundos (no medido aparte) | — |
| Revisión de calidad (INVEST) | 7,2 min | **7,7 s** | ~55× |
| Suite de QA | 8,3 min | **41 s** | ~12× |
| Iterar una suite | 5,3 min | **no cabe** en el nivel gratuito (§6) | — |
| Memoria al publicar | 1,4 min | **3 s** | ~28× |

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

### 5.2 Estimación con un modelo comercial (referencia)
Con los **tokens reales** de cada operación del agente y los precios oficiales de Anthropic (por millón de tokens, entrada / salida: **Haiku 4.5 1 / 5 $**, **Sonnet 5.5 2 / 10 $**, **Opus 5.5 4 / 20 $**; tabla de precios de la API, consultada el 2026-10-08):

| Operación | Llamadas | Local (medido) | Haiku 4.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|---|
| HU nueva | 2 | 240 s · 0 $ | ~19 s · 0,012 $ | ~18 s · 0,025 $ | ~26 s · 0,049 $ |
| Evolucionar una HU | 2 | 312 s · 0 $ | ~17 s · 0,013 $ | ~17 s · 0,027 $ | ~24 s · 0,054 $ |
| Suite de QA | 3 | 498 s · 0 $ | ~23 s · 0,017 $ | ~23 s · 0,035 $ | ~33 s · 0,069 $ |
| Iterar una suite | 1 | 318 s · 0 $ | ~13 s · 0,012 $ | ~12 s · 0,023 $ | ~17 s · 0,047 $ |
| Revisión de calidad | 2 | 432 s · 0 $ | ~17 s · 0,015 $ | ~17 s · 0,030 $ | ~24 s · 0,060 $ |
| **Las 91 llamadas medidas** | 91 | 4 h 52 min · 0 $ | ~14 min · ~0,68 $ | ~14 min · ~1,36 $ | ~19 min · ~2,71 $ |
| **1000 operaciones al mes** | — | 0 $ | ~15 $ | ~30 $ | ~60 $ |

**Cómo se estimó el tiempo:** primera respuesta + tokens de salida ÷ velocidad (Haiku ~108 tokens/s y ~0,7 s; Sonnet ~125 tokens/s y ~1,5 s; Opus ~96 tokens/s y ~3 s), según Artificial Analysis (comparativas públicas de modelos de Anthropic, octubre de 2026).

**Márgenes:** ±20 % por la forma de contar tokens de cada modelo. Un modelo más capaz probablemente necesitaría menos reintentos, así que la cifra es conservadora. Aprobar y editar a mano no llaman al modelo: no cuestan nada con ninguno.

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
| **Groq de pago (Dev Tier)** | Segundos en todo | Buena | Sale a un tercero | Por uso (precio a confirmar) | Sí | Quita el límite por minuto; mismo código |
| **GPU propia o en la nube privada** con modelos open-weight | Segundos | Depende del modelo | **Total** | Coste de la GPU | Sí | El agente no cambia: solo la configuración |
| **Modelo comercial** (Claude por API o por una plataforma corporativa) | Segundos | Alta (estimación) | Sale a un tercero, con acuerdo de tratamiento de datos | ~15–60 $ / 1000 operaciones | **No** (requiere revisar D-14) | Estimado, no probado |

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
