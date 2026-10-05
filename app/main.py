"""Punto de entrada de la UI «Propuesta mixta» (D-04): `uv run streamlit run app/main.py`.

Navega entre las pantallas según el estado de la sesión. Toda la composición está en
`app/session.py`; las pantallas, en `app/views/`.
"""

import sys
from pathlib import Path

# El proyecto no se instala como paquete (`package = false`): Streamlit solo añade `app/` al
# path, así que se añade la raíz para importar `app`, `core`, `adapters` y `schemas`.
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from app.session import compose, retry_compose, state  # noqa: E402
from app.text import md_escape  # noqa: E402
from app.views import (  # noqa: E402
    administracion,
    calidad,
    frame,
    generando,
    inicio,
    iterar,
    login,
    memoria,
    origen,
    recibo,
)

SCREENS = {
    "inicio": inicio.render,
    "origen": origen.render,
    "generando": generando.render,
    "iterar": iterar.render,
    "recibo": recibo.render,
    "calidad": calidad.render,
    "memoria": memoria.render,
    "administracion": administracion.render,
}


def main() -> None:
    st.set_page_config(page_title="Agente AF y QA", page_icon=":material/task_alt:", layout="wide")
    session = state()
    compose(session)  # build_container configura los logs con los secretos enmascarados
    if session.compose_error:
        st.title("Agente de Análisis Funcional y QA")
        st.error(md_escape(session.compose_error))
        st.caption("Revisa la configuración (`.env` y `config/models.yaml`) y la base de datos.")
        if st.button("Reintentar", type="primary", key="retry_compose"):
            retry_compose(session)
        return
    if session.user is None:
        login.render(session)
        return
    frame.sidebar(session)
    SCREENS.get(session.screen, inicio.render)(session)


main()
