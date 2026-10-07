"""Punto de entrada: python -m streamlit run app.py"""

import streamlit as st

from interface import build_context

st.set_page_config(page_title="VaR histórico", page_icon="📊", layout="wide")

page = st.navigation([
    st.Page("views/results.py", title="Resultados", default=True),
    st.Page("views/data.py", title="Datos"),
])
# Los controles comunes se ejecutan en cada navegación, evitando que se pierdan sus valores.
st.session_state["analysis"] = build_context()
page.run()
