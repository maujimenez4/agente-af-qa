# PROMPT-03 · Seed de Jira importable por CSV (T-15) · Sesión área A

Abre la sesión en el worktree del área A (`cd .claude\worktrees\area-a; claude`) y pega todo lo que hay debajo de la línea como primer mensaje.

---

Eres la sesión del **área A (Integraciones y núcleo)** del proyecto "Agente de IA de Análisis Funcional y QA". Trabajas en el worktree `area-a` (rama `area-a`). La tarea es **T-15: seed de Jira**. Por decisión del día 1, se entrega como un **CSV importable desde la interfaz de Jira Cloud** en lugar de un script por API.

## Antes de nada
1. Trae lo último de la sesión principal: `git rebase main`.
2. Lee completos: `CLAUDE.md`, `docs/specs/SPEC-00-fundacional.md` (congelada, v1.2, con el anexo §11), `docs/KANBAN.md` (T-09, T-15, T-21, T-30 y "Decisiones del día 1") y `docs/decisiones/01_declaraciones_proyecto.md` (§6.2, D-06, D-09, R-05, RF-14 a RF-19).
3. Lee `tests/fakes/dataset.py`. Si ya existe, lee también `data/seed/corpus/README.md` (índice del corpus de T-09, con los temas de épica).
4. Cambia T-15 a 🔄 en el Kanban.

## Qué hay que construir
En `data/seed/jira/`:

1. **`seed-villaficticia.csv`**: épicas e HU sintéticas del servicio digital de la **Biblioteca Municipal de Villaficticia**.
   - Entre **3 y 4 épicas** y entre **10 y 15 HU**, repartidas entre las épicas.
   - La épica de **préstamo digital**, con sus HU de reservar un libro, renovar un préstamo y consultar el historial, debe equivaler a `DEMO-1` a `DEMO-4` de los fakes. Las demás épicas salen del índice del corpus si existe; si no, de temas coherentes (reservas, socios, catálogo, sanciones, notificaciones).
   - Mezcla **a propósito** HU de distinta calidad, para probar el agente:
     - unas completas, con criterios de aceptación en Gherkin y reglas de negocio;
     - otras incompletas o ambiguas, para la revisión (RF-18);
     - al menos 2 pares de HU relacionadas o con dependencias, para el análisis de impacto (RF-19).
   - **Sin subtareas de caso de prueba**: esas las genera y publica el agente (D-09).
2. **`README.md`**:
   - pasos de importación en Jira Cloud;
   - tabla de columnas del CSV y su campo de Jira;
   - qué valores hay que mapear en el asistente (tipos de incidencia, prioridades);
   - cómo crear a mano los vínculos "relates to" si el importador no los admite.
3. **`tests/unit/test_seed_jira_csv.py`**, con el subagente `test-writer`. Debe comprobar:
   - que el CSV se lee con `csv` en UTF-8 y tiene las columnas esperadas;
   - que hay 3–4 épicas y 10–15 HU;
   - que cada HU tiene un `Parent` que existe y es una épica, y que los `Issue ID` son únicos;
   - que los títulos de las HU llevan el prefijo `[HU-XX]` (R-05) sin repetirse;
   - que no hay emails, teléfonos ni DNI/NIE;
   - que las reglas del dominio no se contradicen con `tests/fakes/dataset.py`: 3 reservas activas, reserva de 48 h, préstamo de 21 días y 2 renovaciones.

## Formato del CSV (importador de Jira Cloud)
- UTF-8, separado por comas, cabecera en la primera fila y campos con saltos de línea entre comillas dobles.
- Columnas mínimas:
  - `Issue ID`: número único que solo sirve para relacionar filas dentro del CSV.
  - `Parent`: el `Issue ID` de la épica.
  - `Issue Type`: `Epic` / `Story`.
  - `Summary`, `Description`, `Priority` y `Labels`. Usa varias columnas `Labels` si hay varias etiquetas; al menos `seed-villaficticia` en todas las filas.
- Vínculos opcionales: una columna `Link "Relates"` con el `Issue ID` destino. Documenta en el README que, si el importador del espacio no la admite, se crean a mano.
- La `Description` va en **formato wiki de Jira** (`h2.`, `*negrita*`, listas con `*` y `#`, `{code}`), no en Markdown, porque el importador la convierte a ADF. Plantilla para las HU completas:
  - Como / Quiero / Para
  - Objetivo de negocio
  - Alcance (incluye / excluye)
  - Criterios de aceptación `CA-01…` en Gherkin (Dado / Cuando / Entonces)
  - Reglas de negocio `RN-01…`
  - Dependencias
- Los valores de `Issue Type` y `Priority` pueden no coincidir con los del espacio del usuario (por ejemplo, "Historia" en lugar de "Story"). Déjalo explicado en el README: el asistente de importación permite mapear los valores.

## Restricciones
- **Datos 100 % ficticios.** Nada de nombres de personas, emails, teléfonos, DNI ni organizaciones o productos reales. Usa roles ("persona socia", "responsable de sala") y sistemas inventados ("CatálogoVF", "AvisosVF").
- **No escribas en Jira** ni llames a su API. La importación la hace el usuario desde el navegador (principio de aprobación humana).
- Ningún secreto ni URL real: no uses el `.env` para nada.
- No toques directorios del área B ni los contratos congelados. Si necesitas un cambio en ellos, para y propónlo. Si ves mejoras, anótalas en el Kanban como "Propuesta adicional".

## Cierre de la tarea
1. Ejecuta `uv run pytest -m "not integration"` y `uv run ruff check .`.
2. Pasa `spec-checker` y `security-reviewer`, y corrige lo que marquen.
3. Pon T-15 en ✅ y anota en el registro diario que la importación real la hace el usuario.
4. Haz commit en la rama `area-a` con `T-15: seed de Jira importable por CSV [D-06]`. No fusiones en `main`.
5. Dame un resumen de 3–5 líneas (épicas, HU por épica, cuáles están incompletas a propósito y qué vínculos hay) y los pasos exactos de importación.

Empieza leyendo la documentación y presenta el plan (épicas, títulos de HU y su calidad prevista) **antes de escribir**. Espera mi confirmación.
