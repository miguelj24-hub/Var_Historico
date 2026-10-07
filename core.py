"""Alineación y VaR histórico. Funciones independientes de la interfaz."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np
import pandas as pd

from config import MIN_RETURN_OBSERVATIONS
from loaders import CleanAsset, DataValidationError


@dataclass
class Alignment:
    prices: pd.DataFrame
    summary: pd.DataFrame
    removed_dates: pd.DataFrame


@dataclass
class VarResult:
    log_returns: pd.DataFrame
    contributions: pd.DataFrame
    scenarios: pd.DataFrame
    positions: pd.Series
    percentile_pnl: float
    var_amount: float
    var_fraction: float
    confidence: float
    capital: float


def align_assets(assets: list[CleanAsset]) -> Alignment:
    if not assets:
        raise DataValidationError("Carga al menos un activo.")
    tickers = [a.ticker for a in assets]
    if len(set(tickers)) != len(tickers):
        raise DataValidationError("Hay tickers repetidos. Corrige los nombres o elimina el archivo duplicado.")
    prices = pd.concat([a.prices for a in assets], axis=1, join="inner").sort_index()
    if prices.empty:
        raise DataValidationError("Los activos no tienen fechas comunes después de limpiar los datos.")
    if len(prices) < MIN_RETURN_OBSERVATIONS + 1:
        raise DataValidationError(f"Se requieren al menos {MIN_RETURN_OBSERVATIONS + 1} fechas comunes para calcular el VaR.")
    summary, discarded = [], []
    for asset in assets:
        missing = asset.prices.index.difference(prices.index)
        summary.append({
            "Ticker": asset.ticker, "Archivo": asset.source,
            "Filas leídas": asset.raw_rows, "Filas inválidas": len(asset.invalid_rows),
            "Duplicados iguales": asset.duplicate_rows_removed,
            "Fechas válidas": len(asset.prices), "Fechas no compartidas": len(missing),
            "Fechas utilizadas": len(prices),
        })
        discarded.extend({"Ticker": asset.ticker, "Archivo": asset.source, "Fecha descartada": d}
                         for d in missing)
    removed = pd.DataFrame(discarded, columns=["Ticker", "Archivo", "Fecha descartada"])
    return Alignment(prices, pd.DataFrame(summary), removed)


def calculate_var(prices: pd.DataFrame, weight_percentages: dict[str, float],
                  capital: float = 300.0, confidence: float = 0.95) -> VarResult:
    """Replica LN, SUMPRODUCT y PERCENTILE.INC del Excel para posiciones largas.

    H = sum(log(precio_t / precio_t-1) * monto_i).
    Se mantiene el signo de -percentil, incluso si toda la cola contiene ganancias.
    """
    if not np.isfinite(capital) or capital <= 0:
        raise DataValidationError("El capital debe ser un número positivo y finito.")
    if not np.isfinite(confidence) or not 0 < confidence < 1:
        raise DataValidationError("La confianza debe estar entre 0 y 1, sin incluir los extremos.")
    if set(weight_percentages) != set(prices.columns):
        raise DataValidationError("Las ponderaciones deben corresponder exactamente a los activos.")
    weights = pd.Series(weight_percentages, dtype=float).reindex(prices.columns)
    if not np.isfinite(weights.to_numpy()).all() or (weights < 0).any() or (weights > 100).any():
        raise DataValidationError("Las ponderaciones deben estar entre 0% y 100%.")
    if not np.isclose(weights.sum(), 100.0, rtol=0, atol=1e-6):
        raise DataValidationError(f"Las ponderaciones suman {weights.sum():.6f}%. Deben sumar 100%.")
    if len(prices) < MIN_RETURN_OBSERVATIONS + 1:
        raise DataValidationError("No hay suficientes precios para calcular rendimientos.")
    if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.hasnans or prices.index.has_duplicates:
        raise DataValidationError("Los precios deben tener un índice de fechas válidas y únicas.")
    ordered = prices.sort_index().astype(float)
    if not np.isfinite(ordered.to_numpy()).all() or (ordered <= 0).any().any():
        raise DataValidationError("Todos los precios deben ser positivos, finitos y sin datos faltantes.")
    log_returns = np.log(ordered / ordered.shift(1)).iloc[1:]
    positions = capital * weights / 100.0
    positions.name = "Monto invertido"
    contributions = log_returns.mul(positions, axis=1)
    pnl = contributions.sum(axis=1)
    # Interpolación lineal inclusiva: equivale a PERCENTILE.INC de Excel.
    quantile = float(np.quantile(pnl.to_numpy(), 1.0 - confidence, method="linear"))
    scenarios = pd.DataFrame({
        "Fecha anterior": ordered.index[:-1].to_numpy(),
        "Días calendario del intervalo": np.diff(ordered.index.to_numpy()).astype("timedelta64[D]").astype(int),
        "Rendimiento ponderado": pnl / capital,
        "Ganancia o pérdida aproximada": pnl,
        "Por debajo del percentil": pnl < quantile,
    }, index=log_returns.index)
    scenarios.index.name = "Fecha"
    return VarResult(log_returns, contributions, scenarios, positions, quantile,
                     -quantile, -quantile / capital, confidence, capital)
