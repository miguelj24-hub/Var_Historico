"""Valores iniciales y nombres reconocidos. Modifica aquí los valores por defecto."""

DEFAULT_CAPITAL = 300.0
DEFAULT_CONFIDENCE = 95.0
DEFAULT_PERIODS_PER_YEAR = 252
MIN_RETURN_OBSERVATIONS = 2
SMALL_SAMPLE_THRESHOLD = 100
DATE_NAMES = {"fecha", "date", "datetime", "timestamp", "time", "dia"}
PRICE_NAMES = (
    "adj close", "adjusted close", "cierre ajustado", "precio ajustado",
    "close", "cierre", "ultimo", "last", "precio", "price",
)
OTHER_NAMES = {
    "open", "apertura", "high", "maximo", "low", "minimo", "volume", "volumen",
    "vol.", "change", "change %", "% var.", "variacion", "rendimiento",
    "return", "returns", "portafolio", "perdida", "var (.95)", "ticker", "symbol",
    "simbolo", "activo", "fecha", "date", "datetime", "timestamp", "time", "dia",
}
TICKER_NAMES = {"ticker", "symbol", "simbolo", "activo"}
