"""Controles compartidos y presentación. Los cálculos están en core.py."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import math

import numpy as np
import pandas as pd
import streamlit as st

from config import (DEFAULT_CAPITAL, DEFAULT_CONFIDENCE, DEFAULT_PERIODS_PER_YEAR,
                    SMALL_SAMPLE_THRESHOLD)
from core import align_assets, calculate_portfolio_statistics, calculate_var
from loaders import (DataValidationError, clean_asset, detect_columns, detect_header,
                     infer_ticker, is_excel_date, parse_dates, read_raw, sheet_names, with_header)

ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False, max_entries=20)
def cached_sheets(name: str, content: bytes) -> list[str]:
    return sheet_names(name, content)


@st.cache_data(show_spinner=False, max_entries=20)
def cached_raw(name: str, content: bytes, sheet: str, separator: str) -> pd.DataFrame:
    return read_raw(name, content, sheet, separator)


def csv_bytes(frame: pd.DataFrame, index: bool = True) -> bytes:
    return frame.to_csv(index=index, date_format="%Y-%m-%d").encode("utf-8-sig")


def build_context() -> dict:
    """Se ejecuta en el entrypoint para conservar los controles entre páginas."""
    context = {"errors": [], "assets": [], "alignment": None, "result": None,
               "statistics": None, "currency": "u.m."}
    st.sidebar.title("VaR histórico")
    st.sidebar.caption("Precios, ponderaciones y riesgo del portafolio")
    demo = st.sidebar.checkbox("Usar ejemplo del Excel", key="use_demo")
    uploads = st.sidebar.file_uploader(
        "1. Carga uno o varios archivos", type=["xlsx", "csv", "cvc"],
        accept_multiple_files=True, key="uploads",
        help="Una serie por archivo o varias columnas de precios en una misma hoja.",
    )
    if demo:
        sources = [(p.name, p.read_bytes()) for p in sorted((ROOT / "examples").glob("*.csv"))]
        st.sidebar.caption("Ejemplo: los 251 precios por activo de tu Excel.")
    else:
        sources = [(file.name, file.getvalue()) for file in uploads]
    if not sources:
        return context

    with st.sidebar.expander("Formato de fechas y números", expanded=False):
        date_format = st.selectbox(
            "Formato de fechas", ["dd/mm/aaaa", "mm/dd/aaaa"], key="date_format",
            index=0 if st.session_state.get("day_first", True) else 1,
            help="Determina cómo interpretar fechas ambiguas escritas como texto. "
                 "Las fechas ISO (aaaa-mm-dd) se reconocen en ambos modos.",
        )
        day_first = date_format == "dd/mm/aaaa"
        st.caption("10/02/2026 = " + ("10 de febrero de 2026." if day_first else "2 de octubre de 2026."))
        decimal = st.selectbox("Separador decimal de precios", [".", ","], key="decimal")
        st.caption("Se interpreta el otro símbolo como separador de miles. No incluyas símbolos de moneda.")

    assets = []
    for i, (name, content) in enumerate(sources):
        token = f"file_{i}_{sha256(content).hexdigest()[:12]}"
        with st.sidebar.expander(f"Archivo {i + 1}: {name}", expanded=len(sources) == 1):
            try:
                sheets = cached_sheets(name, content)
                sheet = st.selectbox("Hoja", sheets, key=f"{token}_sheet")
                separator = "Auto"
                if Path(name).suffix.lower() in {".csv", ".cvc"}:
                    separator = st.selectbox("Separador de columnas", ["Auto", ",", ";", "\t", "|"],
                                             key=f"{token}_separator",
                                             format_func=lambda x: "Tabulación" if x == "\t" else x)
                raw = cached_raw(name, content, sheet, separator)
                if raw.empty:
                    raise DataValidationError("El archivo no contiene datos.")
                header = st.number_input("Fila de encabezados", min_value=1, max_value=len(raw),
                                         value=detect_header(raw) + 1, step=1, key=f"{token}_header")
                frame = with_header(raw, int(header) - 1)
                suggested_date, suggested_prices = detect_columns(frame, day_first, decimal)
                columns = list(frame.columns)
                date_col = st.selectbox("Columna de fecha", columns, index=columns.index(suggested_date),
                                        key=f"{token}_{header}_date")
                original_dates = parse_dates(frame[date_col], day_first)
                swap_excel_dates = False
                has_excel_dates = (Path(name).suffix.lower() == ".xlsx"
                                   and frame[date_col].map(is_excel_date).any())
                if has_excel_dates:
                    swap_excel_dates = st.checkbox(
                        "Corregir fechas de Excel con día y mes invertidos",
                        value=False, key=f"{token}_{header}_{date_col}_swap_excel_dates",
                        help="Actívalo si Excel ya convirtió incorrectamente las fechas. "
                             "Intercambia día y mes cuando ambos son de 1 a 12. "
                             "Los textos se interpretan mediante el formato elegido arriba.",
                    )
                    corrected_dates = parse_dates(frame[date_col], day_first, True)
                    changed = int((original_dates.notna() & corrected_dates.notna()
                                   & original_dates.ne(corrected_dates)).sum())
                    valid_original = original_dates.dropna()
                    valid_corrected = corrected_dates.dropna()
                    original_ordered = (valid_original.is_monotonic_increasing
                                        or valid_original.is_monotonic_decreasing)
                    corrected_ordered = (valid_corrected.is_monotonic_increasing
                                         or valid_corrected.is_monotonic_decreasing)
                    if changed and len(valid_original) >= 3 and not original_ordered and corrected_ordered:
                        if not swap_excel_dates:
                            st.warning("Posible día y mes invertidos: al intercambiarlos, las fechas "
                                       "recuperan una secuencia cronológica. Revisa la vista previa y "
                                       "activa la corrección si corresponde a tu archivo.")
                    if swap_excel_dates:
                        st.info(f"Corrección aplicada a {changed:,} fechas de Excel.")
                interpreted_dates = (corrected_dates if swap_excel_dates else original_dates)
                preview = pd.DataFrame({
                    "Fecha original": frame[date_col].astype(str).str.replace(" 00:00:00", "", regex=False),
                    "Fecha usada": interpreted_dates.dt.strftime("%Y-%m-%d").fillna("Inválida"),
                }).head(5)
                st.caption("Vista previa: la fecha usada se muestra como aaaa-mm-dd.")
                st.dataframe(preview, hide_index=True, width="stretch")
                options = [c for c in columns if c != date_col]
                price_cols = st.multiselect("Columnas de precios a incluir", options,
                                            default=[c for c in suggested_prices if c in options],
                                            key=f"{token}_{header}_{date_col}_prices")
                if not price_cols:
                    raise DataValidationError("Selecciona al menos una columna de precios.")
                if Path(name).suffix.lower() == ".cvc":
                    st.warning("La extensión .cvc se está leyendo como CSV.")
                for col in price_cols:
                    ticker = st.text_input(f"Ticker para {col}", value=infer_ticker(name, col, frame),
                                           key=f"{token}_{header}_{col}_ticker")
                    asset = clean_asset(frame, date_col, col, ticker, f"{name} / {sheet}",
                                        day_first, decimal, swap_excel_dates)
                    assets.append(asset)
                    st.success(f"{asset.ticker}: fechas y precios válidos ({len(asset.prices):,} fechas).")
                    if len(asset.invalid_rows):
                        st.warning(f"{asset.ticker}: se descartaron {len(asset.invalid_rows):,} filas inválidas.")
                    if asset.duplicate_rows_removed:
                        st.warning(f"{asset.ticker}: se eliminaron {asset.duplicate_rows_removed:,} duplicados idénticos.")
                st.caption("Si hay varios tickers en una misma columna, sepáralos por archivo o por columna de precios.")
            except DataValidationError as exc:
                message = f"{name}: {exc}"
                context["errors"].append(message)
                st.error(str(exc))
    context["assets"] = assets
    if context["errors"]:
        return context
    try:
        alignment = align_assets(assets)
    except DataValidationError as exc:
        context["errors"].append(str(exc))
        return context
    context["alignment"] = alignment
    st.sidebar.divider()
    st.sidebar.subheader("2. Define el portafolio")
    capital = st.sidebar.number_input("Capital total", min_value=0.01, value=DEFAULT_CAPITAL,
                                      step=100.0, format="%.2f", key="capital")
    currency = st.sidebar.selectbox("Unidad del capital", ["u.m.", "USD", "MXN", "EUR"], key="currency")
    context["currency"] = currency
    st.sidebar.caption("Usa precios en una moneda común. La app no realiza conversiones de divisas.")
    identity = "_".join(sorted(a.ticker for a in assets))
    tickers = list(alignment.prices.columns)
    mode = st.sidebar.radio("Ponderación", ["Iguales (1/n)", "Personalizadas"], key="weight_mode")
    # En modo igual se conserva 1/n completo, reproduciendo las posiciones del Excel.
    # En modo manual distribuir centésimas evita que los valores iniciales sumen 99.99%.
    base, remaining = divmod(10000, len(tickers))
    defaults = [(base + (i < remaining)) / 100.0 for i in range(len(tickers))]
    if mode == "Iguales (1/n)":
        weights = {ticker: 100.0 / len(tickers) for ticker in tickers}
        st.sidebar.caption(f"Cada activo recibe 1/{len(tickers)} del capital ({100.0 / len(tickers):.4f}%).")
    else:
        if st.sidebar.button("Restablecer distribución inicial", key="reset_weights"):
            for ticker, default in zip(tickers, defaults):
                st.session_state[f"weight_{identity}_{ticker}"] = default
        weights = {}
        for ticker, default in zip(tickers, defaults):
            key = f"weight_{identity}_{ticker}"
            if key not in st.session_state:
                st.session_state[key] = default
            value = st.sidebar.number_input(f"{ticker} (%)", min_value=0.0, max_value=100.0,
                                             value=None, step=0.01, format="%.2f", key=key)
            if value is None:
                context["errors"].append(f"Falta la ponderación de {ticker}.")
            else:
                weights[ticker] = value
        if context["errors"]:
            return context
    total = sum(weights.values())
    if not math.isclose(total, 100.0, abs_tol=1e-6, rel_tol=0):
        st.sidebar.error(f"Total: {total:.2f}%. Ajusta hasta llegar a 100.00%.")
    else:
        st.sidebar.success("Ponderaciones: 100.00%")
    confidence_pct = st.sidebar.slider("Confianza (%)", min_value=90.0, max_value=99.9,
                                       value=DEFAULT_CONFIDENCE, step=0.1, key="confidence")
    with st.sidebar.expander("Anualización"):
        periods_per_year = st.number_input(
            "Sesiones por año", min_value=1, max_value=366,
            value=DEFAULT_PERIODS_PER_YEAR, step=1, key="annualization_periods",
            help="252 para una referencia bursátil; 365 si tus precios son diarios, incluidos fines de semana.",
        )
    context["weights"] = weights
    context["capital"] = capital
    try:
        result = calculate_var(alignment.prices, weights, capital, confidence_pct / 100.0)
        statistics = calculate_portfolio_statistics(result, periods_per_year)
        context["result"] = result
        context["statistics"] = statistics
    except DataValidationError as exc:
        context["errors"].append(str(exc))
    return context


def show_alignment(context: dict) -> None:
    alignment = context["alignment"]
    removed = int(alignment.summary["Fechas no compartidas"].sum())
    if removed:
        st.warning(f"Se descartaron {removed:,} registros de precios con fechas no compartidas. "
                   f"Se conservan {len(alignment.prices):,} fechas presentes en todos los activos.")
    else:
        st.success(f"Las series tienen las mismas {len(alignment.prices):,} fechas válidas.")
    invalid = sum(len(a.invalid_rows) for a in context["assets"])
    if invalid:
        st.warning(f"La limpieza descartó {invalid:,} filas inválidas. Puedes consultarlas en Datos.")
    with st.expander("Validación por activo", expanded=bool(removed or invalid)):
        st.dataframe(alignment.summary, hide_index=True, width="stretch")


def show_errors(context: dict) -> None:
    for message in context["errors"]:
        st.error(message)


def render_results(context: dict) -> None:
    st.title("VaR histórico del portafolio")
    st.caption("Carga los precios, revisa las fechas y define cuánto invertir en cada activo.")
    if not context["assets"] and not context["errors"]:
        st.info("Carga archivos en la barra lateral o activa «Usar ejemplo del Excel».")
        st.markdown("**Formatos de entrada**\n\n"
                    "- Un archivo por activo con columnas `Fecha` y `Close` o `Cierre`.\n"
                    "- Una hoja con `Fecha` y una columna de precios por ticker.\n"
                    "- Encabezados en otra fila: puedes corregirla en las opciones del archivo.")
        st.code("Fecha,Close\n2025-01-02,100.00\n2025-01-03,101.50\n2025-01-06,99.80", language="text")
        st.caption("Por defecto: capital de 300 u.m., posiciones largas y confianza de 95%.")
        return
    if context["alignment"] is None:
        show_errors(context)
        st.info("Corrige la configuración de los archivos para continuar.")
        return
    show_alignment(context)
    show_errors(context)
    result = context["result"]
    if result is None:
        return
    prices = context["alignment"].prices
    unit = context["currency"]
    a, b, c, d = st.columns(4)
    a.metric(f"VaR ({result.confidence:.1%})", f"{result.var_fraction:.2%}")
    b.metric("VaR en dinero", f"{result.var_amount:,.2f} {unit}")
    c.metric("Capital", f"{result.capital:,.2f} {unit}")
    d.metric("Escenarios históricos", f"{len(result.log_returns):,}")
    st.caption(f"Precios: {prices.index.min():%d/%m/%Y} al {prices.index.max():%d/%m/%Y}. "
               f"Rendimientos: {result.log_returns.index.min():%d/%m/%Y} al {result.log_returns.index.max():%d/%m/%Y}.")
    alpha = 1.0 - result.confidence
    if result.percentile_pnl < 0:
        st.markdown(f"El umbral histórico de pérdida es **{result.var_amount:,.2f} {unit} "
                    f"({result.var_fraction:.2%})** por intervalo observado, a una confianza del "
                    f"**{result.confidence:.1%}**. La cola inferior corresponde al **{alpha:.1%}** "
                    "de la distribución estimada. El VaR no mide cuánto se puede perder más allá de ese umbral.")
    else:
        st.info("El percentil de la cola es positivo: representa una ganancia en esta muestra. "
                "Se conserva el VaR con signo negativo para mantener el cálculo del Excel.")
    if len(result.log_returns) < SMALL_SAMPLE_THRESHOLD:
        st.warning("La muestra es pequeña. El percentil de la cola se basa en pocos escenarios históricos.")
    if not context["alignment"].removed_dates.empty:
        st.caption("Cada rendimiento compara dos fechas comunes consecutivas. Al descartar fechas, "
                   "un intervalo puede cubrir más de una sesión. Los extremos se muestran en Datos.")
    stats = context["statistics"]
    st.subheader("Rendimiento y riesgo del portafolio")
    statistics_table = pd.DataFrame({
        "Indicador": ["E(rp). Diario", "E(rp). Anual", "Var diario",
                      "Desv. Std diaria", "Desv. Std Anual", "CV anual"],
        "Valor": [f"{stats.mean_daily_return:.5%}",
                  "N/D" if stats.annualized_return is None else f"{stats.annualized_return:.2%}",
                  f"{stats.daily_variance:.10g}", f"{stats.daily_volatility:.2%}",
                  f"{stats.annual_volatility:.2%}",
                  "N/D" if stats.annual_cv is None else f"{stats.annual_cv:.2%}"],
    })
    st.dataframe(statistics_table, hide_index=True, width="stretch")
    st.caption(f"Calculado con los rendimientos LN ponderados del VaR. "
               f"{stats.periods_per_year} sesiones/año. "
               "Var diario es la varianza muestral, expresada en rendimientos al cuadrado.")
    st.caption("E(rp). Diario es la media histórica LN. E(rp). Anual es su equivalente compuesto: "
               "EXP(media × sesiones/año) − 1. La anualización supone observaciones diarias "
               "y ausencia de autocorrelación para la volatilidad; es una referencia histórica.")
    if stats.annualized_return is None:
        st.info("Rendimiento anual: N/D porque la anualización supera el rango numérico.")
    st.caption("CV anual = Desv. Std Anual / E(rp). Anual. Se muestra como porcentaje. "
               "El CV anual utiliza el rendimiento anualizado mostrado en esta tabla.")
    if stats.annual_cv is None:
        st.info("CV anual: N/D cuando el rendimiento anualizado es cero o prácticamente cero "
                "o el cálculo anualizado no está disponible.")
    if stats.mean_daily_return < -1e-12:
        st.info("El rendimiento medio es negativo: se conserva el signo negativo del CV. "
                "Ese valor no debe interpretarse como menor riesgo por unidad de rendimiento positivo.")
    st.caption("Un rendimiento cercano a cero puede producir un CV muy grande y sensible a pequeños cambios.")
    with st.expander("Fórmulas de rendimiento y riesgo"):
        st.markdown("- `r_t = suma(ponderación_i / 100 × LN(P_i,t / P_i,t−1))`.\n"
                    "- `E(rp). Diario = PROMEDIO(r_t)`.\n"
                    "- `E(rp). Anual = EXP(E(rp). Diario × N) − 1`.\n"
                    "- `Var diario = VAR.S(r_t)`.\n"
                    "- `Desv. Std diaria = DESVEST.M(r_t)`.\n"
                    "- `Desv. Std Anual = Desv. Std diaria × RAÍZ(N)`.\n"
                    "- `CV anual = Desv. Std Anual / E(rp). Anual`.")
        st.caption("N es el número de sesiones por año. Las tasas de estas fórmulas son fracciones: 5% = 0.05. "
                   "El CV se calcula como cociente y se multiplica por 100 solo al mostrarlo como porcentaje. "
                   "La media LN ponderada aproxima el rendimiento del portafolio, igual que en el VaR.")
    st.subheader("Composición del portafolio")
    composition = pd.DataFrame({"Ticker": result.positions.index,
                                "Ponderación (%)": [context["weights"][t] for t in result.positions.index],
                                f"Monto ({unit})": result.positions.to_numpy()})
    st.dataframe(composition, hide_index=True, width="stretch",
                 column_config={"Ponderación (%)": st.column_config.NumberColumn(format="%.2f"),
                                f"Monto ({unit})": st.column_config.NumberColumn(format="%.2f")})
    left, right = st.columns(2)
    with left:
        st.subheader("Distribución de resultados")
        st.vega_lite_chart(result.scenarios.reset_index(), {
            "layer": [
                {"mark": {"type": "bar", "color": "#286f8c"},
                 "encoding": {"x": {"field": "Ganancia o pérdida aproximada", "type": "quantitative", "bin": {"maxbins": 30}, "title": f"Ganancia o pérdida ({unit})"},
                              "y": {"aggregate": "count", "type": "quantitative", "title": "Escenarios"}}},
                {"data": {"values": [{"Umbral": result.percentile_pnl}]},
                 "mark": {"type": "rule", "color": "#c03a43", "strokeWidth": 2},
                 "encoding": {"x": {"field": "Umbral", "type": "quantitative"}}},
            ], "height": 260,
        }, width="stretch")
        st.caption(f"Línea roja: percentil {alpha:.1%} = {result.percentile_pnl:,.4f} {unit}.")
    with right:
        st.subheader("Resultados a lo largo del tiempo")
        st.line_chart(result.scenarios[["Ganancia o pérdida aproximada"]], height=260)
        st.caption("Importes aproximados obtenidos al aplicar los rendimientos logarítmicos a los montos invertidos.")
    with st.expander("Metodología del VaR histórico"):
        st.markdown("1. Se ordenan los precios del más antiguo al más reciente y se conservan las fechas comunes.\n"
                    "2. Rendimiento por activo: `LN(precio actual / precio anterior)`.\n"
                    "3. Monto por activo: `capital × ponderación / 100`.\n"
                    "4. Ganancia o pérdida aproximada: `suma(rendimiento logarítmico × monto)`.\n"
                    "5. Percentil de la cola: `PERCENTILE.INC(resultados, 1 − confianza)`.\n"
                    "6. VaR monetario: `−percentil`. VaR porcentual: `−percentil / capital`.")
        st.caption("No se supone una distribución normal o lognormal. Se utiliza la distribución histórica empírica. "
                   "Se excluye la primera fecha del cálculo de rendimientos porque no tiene precio anterior.")
    summary = pd.DataFrame([{
        "Confianza": result.confidence, "Capital": result.capital, "Unidad": unit,
        "Escenarios": len(result.log_returns), "Percentil de resultados": result.percentile_pnl,
        "VaR monetario": result.var_amount, "VaR fracción": result.var_fraction,
        "E(rp). Diario": stats.mean_daily_return,
        "E(rp). Anual": stats.annualized_return,
        "Var diario": stats.daily_variance,
        "Desv. Std diaria": stats.daily_volatility,
        "Desv. Std Anual": stats.annual_volatility,
        "CV anual": stats.annual_cv,
        "Sesiones por año": stats.periods_per_year,
    }])
    st.download_button("Descargar resumen CSV", csv_bytes(summary, False), "resumen_var.csv", "text/csv")


def render_data(context: dict) -> None:
    st.title("Datos del portafolio")
    st.caption("Precios alineados, rendimientos logarítmicos y registros descartados.")
    if context["alignment"] is None:
        show_errors(context)
        st.info("Carga y configura los archivos en la barra lateral para consultar los datos.")
        return
    show_alignment(context)
    alignment = context["alignment"]
    show_errors(context)
    result = context["result"]
    tabs = st.tabs(["Precios alineados", "Rendimientos logarítmicos", "Resultados por fecha", "Descartados"])
    with tabs[0]:
        st.caption("Todas las columnas comparten las mismas fechas, ordenadas de la más antigua a la más reciente.")
        st.dataframe(alignment.prices, width="stretch",
                     column_config={t: st.column_config.NumberColumn(format="%.10g") for t in alignment.prices.columns})
        st.download_button("Descargar precios CSV", csv_bytes(alignment.prices), "precios_alineados.csv", "text/csv")
    with tabs[1]:
        st.caption("Son rendimientos LN(Pt/Pt−1). La transformación no implica que los datos sigan una distribución lognormal.")
        if result is None:
            st.info("Ajusta las ponderaciones y corrige los errores para calcular los rendimientos.")
        else:
            st.dataframe(result.log_returns, width="stretch",
                         column_config={t: st.column_config.NumberColumn(format="%.8f") for t in result.log_returns.columns})
            st.line_chart(result.log_returns, height=300)
            st.download_button("Descargar rendimientos CSV", csv_bytes(result.log_returns), "rendimientos_logaritmicos.csv", "text/csv")
    with tabs[2]:
        if result is None:
            st.info("Ajusta las ponderaciones y corrige los errores para obtener los escenarios.")
        else:
            st.dataframe(result.scenarios, width="stretch")
            st.download_button("Descargar resultados CSV", csv_bytes(result.scenarios), "escenarios_var.csv", "text/csv")
            with st.expander("Contribución de cada activo a la ganancia o pérdida"):
                st.dataframe(result.contributions, width="stretch")
                st.download_button("Descargar contribuciones CSV", csv_bytes(result.contributions), "contribuciones.csv", "text/csv")
    with tabs[3]:
        st.markdown("**Fechas no compartidas**")
        if alignment.removed_dates.empty:
            st.success("No se descartaron fechas por diferencias entre activos.")
        else:
            st.dataframe(alignment.removed_dates, hide_index=True, width="stretch")
            st.download_button("Descargar fechas descartadas CSV", csv_bytes(alignment.removed_dates, False), "fechas_descartadas.csv", "text/csv")
        st.markdown("**Filas inválidas y duplicados**")
        invalid = pd.concat([a.invalid_rows for a in context["assets"]], ignore_index=True)
        if invalid.empty:
            st.success("No se encontraron filas inválidas.")
        else:
            st.dataframe(invalid, hide_index=True, width="stretch")
            st.download_button("Descargar filas inválidas CSV", csv_bytes(invalid, False), "filas_invalidas.csv", "text/csv")
        duplicates = sum(a.duplicate_rows_removed for a in context["assets"])
        st.caption(f"Duplicados con la misma fecha y precio eliminados: {duplicates:,}. "
                   "Si una fecha tiene precios contradictorios, se bloquea el cálculo hasta corregir el archivo.")
