"""Lectura, detección de columnas y limpieza. No depende de Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO, StringIO
from pathlib import Path
import re
import unicodedata

import numpy as np
import pandas as pd

from config import DATE_NAMES, OTHER_NAMES, PRICE_NAMES, TICKER_NAMES


class DataValidationError(ValueError):
    """Problema corregible por el usuario al configurar un archivo."""


@dataclass
class CleanAsset:
    ticker: str
    source: str
    prices: pd.Series
    raw_rows: int
    invalid_rows: pd.DataFrame
    duplicate_rows_removed: int


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def base_column(column: str) -> str:
    return re.sub(r" \[\d+\]$", "", column)


def sheet_names(filename: str, content: bytes) -> list[str]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".xlsx":
        try:
            with pd.ExcelFile(BytesIO(content), engine="openpyxl") as book:
                return book.sheet_names
        except Exception as exc:
            raise DataValidationError(f"No se pudo abrir el Excel: {exc}") from exc
    if suffix in {".csv", ".cvc"}:
        return ["CSV"]
    raise DataValidationError("Solo se admiten .xlsx y .csv (.cvc se interpreta como CSV).")


def read_raw(filename: str, content: bytes, sheet: str = "CSV", separator: str = "Auto") -> pd.DataFrame:
    """Lee sin encabezados para poder elegir su fila posteriormente."""
    if not content:
        raise DataValidationError("El archivo está vacío.")
    try:
        if Path(filename).suffix.lower() == ".xlsx":
            return pd.read_excel(BytesIO(content), sheet_name=sheet, header=None, dtype=object, engine="openpyxl")
        if Path(filename).suffix.lower() not in {".csv", ".cvc"}:
            raise DataValidationError("Extensión no admitida.")
        encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            text = content.decode("cp1252")
        sep = None if separator == "Auto" else separator
        return pd.read_csv(StringIO(text), sep=sep, engine="python", header=None, dtype=object)
    except DataValidationError:
        raise
    except Exception as exc:
        raise DataValidationError(f"No se pudo leer el archivo. Revisa la hoja y el separador: {exc}") from exc


def detect_header(raw: pd.DataFrame) -> int:
    """Devuelve la fila base cero que contiene Fecha/Date, hasta las primeras 30 filas."""
    for i in range(min(30, len(raw))):
        names = {normalized(x) for x in raw.iloc[i] if pd.notna(x)}
        if names & DATE_NAMES:
            return i
    return 0


def with_header(raw: pd.DataFrame, header_row: int) -> pd.DataFrame:
    if raw.empty or not 0 <= header_row < len(raw):
        raise DataValidationError("La fila de encabezados no existe.")
    names, counts = [], {}
    for i, item in enumerate(raw.iloc[header_row]):
        name = str(item).strip() if pd.notna(item) else f"Columna {i + 1}"
        counts[name] = counts.get(name, 0) + 1
        names.append(name if counts[name] == 1 else f"{name} [{counts[name]}]")
    frame = raw.iloc[header_row + 1:].copy()
    frame.columns = names
    # Mantener el índice original permite mostrar el número de fila del archivo.
    return frame.dropna(how="all")


def parse_dates(values: pd.Series, day_first: bool = True) -> pd.Series:
    def parse(value: object) -> pd.Timestamp:
        if pd.isna(value):
            return pd.NaT
        try:
            if isinstance(value, (float, int, np.number)) and not isinstance(value, bool):
                if 20000 <= float(value) <= 100000:
                    parsed = pd.to_datetime(float(value), unit="D", origin="1899-12-30")
                elif 19000101 <= float(value) <= 21001231 and float(value).is_integer():
                    parsed = pd.to_datetime(str(int(value)), format="%Y%m%d", errors="coerce")
                else:
                    return pd.NaT
            elif isinstance(value, (datetime, date, pd.Timestamp)):
                parsed = pd.Timestamp(value)
            else:
                text = str(value).strip()
                if not text:
                    return pd.NaT
                parsed = pd.to_datetime(text, dayfirst=day_first, errors="coerce", format="mixed")
            if pd.isna(parsed):
                return pd.NaT
            parsed = pd.Timestamp(parsed)
            if parsed.tzinfo is not None:
                parsed = parsed.tz_localize(None)
            return parsed.normalize()
        except (ValueError, TypeError, OverflowError):
            return pd.NaT
    return pd.to_datetime(values.map(parse), errors="coerce")


def parse_prices(values: pd.Series, decimal: str = ".") -> pd.Series:
    """Admite números de Excel, notación científica y separadores de miles."""
    def parse(value: object) -> float:
        if pd.isna(value) or isinstance(value, bool):
            return float("nan")
        if isinstance(value, (int, float, np.number)):
            return float(value)
        text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace("'", "")
        if any(symbol in text for symbol in ("%", "$", "€", "£")):
            return float("nan")
        text = text.replace(",", "") if decimal == "." else text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except (ValueError, TypeError, OverflowError):
            return float("nan")
    return values.map(parse).astype(float)


def detect_columns(frame: pd.DataFrame, day_first: bool = True, decimal: str = ".") -> tuple[str, list[str]]:
    if frame.empty or len(frame.columns) < 2:
        raise DataValidationError("Se necesitan al menos una columna de fechas y una de precios.")
    dates = [c for c in frame.columns if normalized(base_column(c)) in DATE_NAMES]
    date_col = dates[0] if dates else str(frame.columns[0])
    for alias in PRICE_NAMES:
        hits = [c for c in frame.columns if normalized(base_column(c)) == alias]
        if hits:
            return date_col, [hits[0]]
    valid_dates = parse_dates(frame[date_col], day_first).notna()
    candidates = []
    seen_names = set()
    for col in frame.columns:
        key = normalized(base_column(col))
        if col == date_col or key in OTHER_NAMES or key in seen_names or key.startswith("columna "):
            continue
        numeric = parse_prices(frame.loc[valid_dates, col], decimal)
        if len(numeric) and ((numeric > 0) & np.isfinite(numeric)).mean() >= 0.8:
            candidates.append(col)
            seen_names.add(key)
    return date_col, candidates


def infer_ticker(filename: str, price_column: str, frame: pd.DataFrame) -> str:
    # El ticker explícito tiene prioridad cuando es constante en todo el archivo.
    for col in frame.columns:
        if normalized(base_column(col)) in TICKER_NAMES:
            values = frame[col].dropna().astype(str).str.strip().str.upper().unique()
            if len(values) == 1 and values[0]:
                return values[0]
    name = base_column(price_column).strip()
    if normalized(name) not in PRICE_NAMES and not normalized(name).startswith("columna "):
        return name.upper()
    stem = Path(filename).stem.upper().strip()
    return re.split(r"[ _]", stem)[0] or "ACTIVO"


def clean_asset(frame: pd.DataFrame, date_column: str, price_column: str,
                ticker: str, source: str, day_first: bool = True, decimal: str = ".") -> CleanAsset:
    ticker = ticker.strip().upper()
    if not ticker:
        raise DataValidationError("El ticker no puede estar vacío.")
    if date_column == price_column or date_column not in frame or price_column not in frame:
        raise DataValidationError("Selecciona columnas distintas y existentes para fecha y precio.")
    dates = parse_dates(frame[date_column], day_first)
    prices = parse_prices(frame[price_column], decimal)
    valid = dates.notna() & np.isfinite(prices) & prices.gt(0)
    invalid = pd.DataFrame({
        "Archivo": source, "Ticker": ticker, "Fila del archivo": frame.index + 1,
        "Fecha original": frame[date_column].astype(str),
        "Precio original": frame[price_column].astype(str),
        "Motivo": np.where(dates.isna(), "Fecha inválida o vacía", "Precio vacío, no numérico, infinito o no positivo"),
    }).loc[~valid].reset_index(drop=True)
    cleaned = pd.DataFrame({"Fecha": dates[valid], "Precio": prices[valid]})
    if cleaned.empty:
        raise DataValidationError(f"{ticker}: no hay filas con fecha y precio válidos.")
    conflicts = cleaned.groupby("Fecha")["Precio"].nunique()
    conflicts = conflicts[conflicts > 1]
    if not conflicts.empty:
        example = ", ".join(d.strftime("%Y-%m-%d") for d in conflicts.index[:5])
        raise DataValidationError(f"{ticker}: fechas duplicadas con precios diferentes ({example}). Corrige el archivo.")
    duplicates = int(cleaned.duplicated("Fecha").sum())
    series = cleaned.drop_duplicates("Fecha").set_index("Fecha")["Precio"].sort_index()
    series.name = ticker
    series.index.name = "Fecha"
    return CleanAsset(ticker, source, series, len(frame), invalid, duplicates)
