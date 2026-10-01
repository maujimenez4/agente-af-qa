"""Animaciones propias de la Q (`docs/specs/UI.md` §8, PA-44): fase y «escribiendo».

Solo SVG y CSS propios en `st.html`; nunca contenido de Jira, del RAG ni del LLM. Todas se
desactivan con «reducir movimiento». Las funciones devuelven HTML fijo y no reciben texto
libre: la fase es un entero validado.
"""

# Logotipo Q de Qaracter (trazo del lienzo de diseño).
Q_PATH = (
    "M110.806 87.9929H215.094C227.693 87.9929 237.907 98.2067 237.907 110.806V168.557C230.545 "
    "167.016 222.914 166.206 215.095 166.206H166.21V237.904H215.095C236.693 237.904 254.203 "
    "255.413 254.203 277.012V325.898H325.901V277.012C325.901 225.051 290.135 181.444 241.879 "
    "169.465H325.9V110.806C325.9 49.6095 276.29 0 215.094 0H110.806C49.6095 0 0 49.6095 0 "
    "110.806V215.094C0 276.29 49.6095 325.9 110.806 325.9L166.21 325.897V237.907H110.806C98.2067 "
    "237.907 87.9929 227.693 87.9929 215.094V110.806C87.9929 98.2067 98.2067 87.9929 110.806 "
    "87.9929Z"
)
ORANGE = "#FF7932"
TRACK = "#E6EAEE"
_EASE = "cubic-bezier(.2,.7,.2,1)"
_REDUCED = (
    "@media (prefers-reduced-motion: reduce){.qa-anim *{animation:none!important;"
    "transition:none!important}}"
)
_SIZE = 326.0


def phase_q(phase: int, previous: int | None = None, size: int = 28) -> str:
    """Q de fase: se llena un cuarto por fase y sube desde la fase anterior en 0,42 s."""
    if not 1 <= phase <= 4:
        raise ValueError("La fase debe estar entre 1 y 4.")
    start = previous if previous is not None and 0 <= previous <= 4 else phase
    y_to = _SIZE * (1 - phase / 4)
    y_from = _SIZE * (1 - start / 4)
    return (
        f'<div class="qa-anim" role="img" aria-label="Avance: fase {phase} de 4">'
        f"<style>@keyframes qa-ph{{from{{transform:translateY({y_from:.1f}px)}}"
        f"to{{transform:translateY({y_to:.1f}px)}}}}"
        f".qa-ph{{animation:qa-ph .42s {_EASE} both}}{_REDUCED}</style>"
        f'<svg viewBox="0 0 326 326" width="{int(size)}" height="{int(size)}" aria-hidden="true">'
        f'<defs><clipPath id="qa-ph-clip"><rect class="qa-ph" x="0" y="0" width="326" '
        f'height="326" style="transform:translateY({y_to:.1f}px)"></rect></clipPath></defs>'
        f'<path d="{Q_PATH}" fill="{TRACK}"></path>'
        f'<path d="{Q_PATH}" fill="{ORANGE}" clip-path="url(#qa-ph-clip)"></path></svg></div>'
    )


def typing_q(size: int = 22) -> str:
    """Q de «escribiendo»: parpadeo suave mientras el modelo responde."""
    return (
        '<div class="qa-anim" role="status" aria-label="Escribiendo la respuesta" '
        'style="display:flex;align-items:center;gap:8px">'
        "<style>@keyframes qa-blink{0%,100%{opacity:.35}50%{opacity:1}}"
        f".qa-typing{{animation:qa-blink 1.2s {_EASE} infinite}}{_REDUCED}</style>"
        f'<svg class="qa-typing" viewBox="0 0 326 326" width="{int(size)}" '
        f'height="{int(size)}" aria-hidden="true"><path d="{Q_PATH}" fill="{ORANGE}"></path>'
        "</svg><span>Escribiendo la respuesta</span></div>"
    )
