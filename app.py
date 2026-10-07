"""Punto de entrada: python -m streamlit run app.py"""

import streamlit as st

from interface import build_context, render_data, render_results


def results_page():
    """Muestra los cálculos del portafolio."""
    render_results(st.session_state["analysis"])


def data_page():
    """Muestra los precios y rendimientos usados en los cálculos."""
    render_data(st.session_state["analysis"])


st.set_page_config(page_title="VaR histórico", page_icon="📊", layout="wide")

page = st.navigation([
    st.Page(results_page, title="Resultados", default=True),
    st.Page(data_page, title="Datos", url_path="datos"),
])
# Los controles comunes se ejecutan en cada navegación para conservar sus valores.
st.session_state["analysis"] = build_context()
page.run()
