# web/ · Frontend propio en React (T-56)

Frontend del agente, con el aspecto del lienzo «Propuesta mixta» (D-04 revisada, 2026-10-02). Lo construye el responsable del área B. Streamlit (`app/`) queda como plan B hasta el punto de control T-57.

## Alcance
- Pantallas del flujo de HU:
  - Inicio y Elegir en Jira;
  - Origen y fuentes;
  - Generando;
  - Iterar: chat, versiones, propuesta, cambios, impacto y fuentes; *editar a mano*, en los días 6 a 8 (DESIGN-DECISIONS.md §4 bis);
  - Recibo de aprobación y Resultado;
  - Revisar la calidad.
- Pantallas del flujo de QA (Qa*), incluido «Preparar pruebas» desde una HU aprobada (T-54).
- Piezas comunes:
  - carril y barra de conversaciones;
  - la Q animada de fase, carga y escritura;
  - estados vacío, cargando y error.

  Todo respeta `prefers-reduced-motion`.
- Referencias:
  - diseño: `docs/diseno/lienzo/` y el lienzo en claude.ai;
  - comportamiento: `docs/specs/UI.md`;
  - datos: `docs/api/openapi.yaml` (T-55).

## Cómo habla con el backend
- **Solo a través de la API HTTP de T-55:** nunca directamente con Jira ni con el LLM.
- **Antes de la API real:** contra una API simulada generada a partir del contrato OpenAPI.
- **Para aprobar:** se devuelve exactamente la `fingerprint` del último payload de revisión (UI.md §5).

## Reglas
- El texto que llega de la API (Jira, RAG, LLM) se muestra como texto: **nunca** `dangerouslySetInnerHTML` ni Markdown con HTML.
- Ni secretos ni claves en el frontend. La sesión, como diga el contrato; nunca en `localStorage`.
- En mocks y pruebas, solo datos sintéticos.

## Stack
Vite, React y TypeScript; CSS con variables (los tokens del lienzo y DM Sans); Vitest y Testing Library; API simulada con MSW sobre los ejemplos del contrato de T-55 (`npm run dev:mock`). Versiones y motivos en [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md) §7.

## Cómo arrancar
Requisito: Node.js 22.12 o superior (lo pide MSW).

```bash
cd web
npm ci            # instala exactamente lo del package-lock.json
npm run dev       # servidor de desarrollo en http://localhost:5173, contra la API real (proxy a 127.0.0.1:8000)
npm run dev:mock  # igual, pero contra la API simulada (MSW): no hace falta Python ni Docker
```

- **Usuarios de la API simulada:** `af-demo`, `qa-demo` y `admin-demo`, con la contraseña ficticia `demo` (solo existe en MSW).
- **Casos que la pantalla no provoca sola**, añadiendo `?simular=` a la URL (solo con `npm run dev:mock`; los de aprobación se aplican a cada *Aprobar y publicar* de esa pestaña):
  - `?simular=huella`: la huella no casa → vuelve al recibo con «No se aprobó» y el motivo;
  - `?simular=aprobacion-rechazada`: 409 `approval_rejected` → *Empezar de nuevo*;
  - `?simular=no-en-revision`: 409 `not_in_review` → *Actualizar*;
  - `?simular=publicado`: publicación real (fase 4, «Publicado en Jira»; en una suite, «Suite publicada en Jira» con subtareas ficticias DEMO-21…), sin escribir en ningún Jira;
  - `?simular=parcial`: publicación en parte, con un error ficticio de vínculo (en una suite falla el último caso y la conversación queda en `approved`);
  - `?simular=ya-recogida`: al recoger una HU pendiente de pruebas (QA), otra persona se adelantó (409 `handoff_unavailable`). Solo con el flujo unido activado (`QA_HANDOFF_ENABLED`, hoy fuera de la entrega);
  - `?simular=sin-cubrir`: la suite de QA llega con CA y RN sin ningún caso (`uncovered` con CA-03 y RN-03 ficticios): distintivo «1 CA y 1 RN sin caso» y filas «Sin caso» en Cobertura (PA-326);
  - `?simular=cobertura-desconocida`: la suite llega con `uncovered: null` («no se sabe»): sin distintivo de cobertura ni «Todos los CA cubiertos»;
  - `?simular=muchas-conversaciones`: 120 conversaciones ficticias en 30 días, para revisar la lista larga (este se aplica al cargar la página).

  Quita el parámetro y recarga para volver al comportamiento normal (al recargar se pierde la sesión simulada: vuelve a iniciar sesión).
- **Catálogo del sistema de diseño:** `http://localhost:5173/?catalogo`, solo en desarrollo.
- **API real:** `uv run python -m api` en la raíz del repo (ver `docs/api/README.md`). El destino del proxy se cambia con `API_PROXY_TARGET`. Recorrido y lista de comprobación: [PRUEBA-API-REAL.md](PRUEBA-API-REAL.md).

Antes de cada entrega: `npm run lint`, `npm run test` y `npm run build` sin errores.

## Tipos del contrato
`src/api/schema.d.ts` se genera desde `docs/api/openapi.yaml` y se versiona. No se edita a mano.

```bash
npm run api:types   # regenera los tipos cuando cambia el contrato
npm run api:check   # falla si los tipos no coinciden con el contrato
```

El generador (`openapi-typescript`) vive aislado en `tools/api-types/`, con su propio lockfile, porque pide TypeScript 5 y `web/` usa la 6. El resto del código importa los tipos desde `src/api/types.ts`.

## Decisiones de diseño
Las incoherencias del lienzo y las demás decisiones (tokens, foco, fuentes, la Q) están resueltas en [DESIGN-DECISIONS.md](DESIGN-DECISIONS.md).
