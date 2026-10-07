# Medidas: Groq (nivel gratuito) frente al modelo local · 2026-10-07

Datos para la comparativa de la presentación y para elegir el modelo de la demo. Salen del registro de la API y de la tabla `llm_usage`, en el proyecto sintético AFQP, con la misma base de conocimiento (embeddings `bge-m3` locales) y las mismas instrucciones (`prompts/`).

- **Local:** Ollama 0.35.0 en Docker, solo CPU, `qwen3:1.7b` (respaldo `phi4-mini`), ventana de 8192 (10 240 desde PA-440), contexto de 3300.
- **Groq:** `config/models.groq.yaml`, nivel gratuito. `openai/gpt-oss-120b` para HU, evolución, calidad y QA, y `openai/gpt-oss-20b` para impacto y memoria. Contexto de 2000 y, en la suite, tope de salida de 2500 y razonamiento «low» (PA-441).

## Operación por operación

| Operación | Groq: tiempo total | Groq: llamadas (entrada / salida) | Local `qwen3:1.7b`: mediana por llamada | Calidad observada |
|---|---|---|---|---|
| **HU nueva** (HU 2, AFQP-28) | **11 s** | generación 7,3 s (5568 / 2854) + impacto 3,2 s (2787 / 2289) | generación **5,1 min** (14 llamadas, ~4000 / ~1570) | Groq: casi lista, retoques menores. Local (HU 1, AFQP-27): copió los CA de otra HU (HU-08) y se inventó una regla; hubo que reescribirla a mano |
| **Memoria al publicar** | **3 s** | 3236 / 1714 (`gpt-oss-20b`) | **1,4 min** (2244 / 478) | Ambas se indexaron |
| **Suite de QA** (AFQP-27) | **41 s** | estructurar 3,3 s (1928 / 1293) + suite 17,4 s, con 12 s de espera por el límite (4249 / 2272) + reintento dirigido 5,4 s (5929 / 2160, respaldo `qwen3.8-27b`) | suite **4,9 min** (16 llamadas, ~4850 / ~1350); una suite completa, con estructurar y reintentos, ~8,3 min de mediana | Groq: 6 casos claros con datos sintéticos, pero CP-05 y CP-06 enlazados a CA equivocados. Ver PA-442: la HU de origen llegó recortada a 4 CA |
| **Revisión de calidad (INVEST)** (AFQP-4) | **7,7 s** | estructurar 2,1 s (1461 / 705) + revisión 3,1 s (3712 / 1180) | revisión **3,8 min** (6 llamadas, ~5080 / ~835) | Groq: 6 hallazgos |
| **Iterar una suite** | **no cabe** | la petición pide ~9500-9800 tokens > 8000 TPM (413) | ~5,3 min (mediana de iterar) | — |

Medianas locales: todas las llamadas con salida registradas en `llm_usage` (2026-10-01 a 2026-10-07).

## Límites del nivel gratuito de Groq (comprobados con el parche de diagnóstico, PA-441)

| Modelo | Límite | Efecto |
|---|---|---|
| `openai/gpt-oss-120b` | **8000 tokens por minuto** (entrada + salida prevista) | La suite solo cabe con poco contexto y tope de salida; iterar una suite no cabe (413). Entre dos operaciones hay que esperar el minuto (429) |
| `qwen/qwen3.8-27b` (respaldo) | **1000 tokens de salida por minuto** | No sirve para HU ni suites |
| OpenRouter `qwen/qwen3.8-27b:free` (respaldo) | **404**: ya no hay versión gratuita | Cadena de respaldo sin salida |

## Avisos para leer los datos

- `llm_usage` también registra las llamadas **rechazadas** (413) con la entrada estimada y el tope de salida (p. ej. 7245 / 2500 a las 21:22): no son tokens consumidos. Por eso el anillo de la web pasa del 100 %, que además suma el consumo local. Es solo un aviso, no bloquea (RNF-27).
- Groq trabajó con menos contexto (2000) que el local (3300), y la HU 2 se generó con el razonamiento por defecto, antes de pasar a «low».
- Una sola medida por operación en Groq; las locales son medianas de varios días.

## Conclusión provisional

Con Groq, las operaciones bajan de minutos a segundos (entre 12 y 30 veces más rápido) y la calidad de las HU mejora mucho. El nivel gratuito, en cambio, no da para QA: la suite apenas cabe y la iteración no cabe. Opciones para la demo: Groq de pago (Dev Tier, por uso), un modo mixto (Groq para HU, memoria y calidad; local para QA) o todo local.
