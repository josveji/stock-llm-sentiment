"""
market_data.py
================
Obtención de datos de mercado: descarga de precios históricos y cálculo de indicadores
técnicos para un universo de empresas (ej. Fortune 100).

Uso:
    python market_data.py --tickers tickers.csv --years 2 --out dataset_precios.csv

Por defecto usa MVP_25_SAMPLE (25 empresas diversificadas por sector, pensadas
para el MVP del proyecto). Si quieres usar el universo completo de ejemplo
(100 tickers), pasa --tickers apuntando a un CSV propio con FORTUNE100_SAMPLE,
o usa --full-universe.

Dependencias:
    pip install yfinance pandas numpy tqdm
"""

import argparse
import time
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # se valida en main()

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, **kwargs):
        return x


# ---------------------------------------------------------------------------
# Lista de ejemplo. El ranking Fortune 100 cambia cada año y Fortune no
# publica los tickers directamente, así que esto es solo un punto de partida
# con grandes empresas estadounidenses. Reemplázalo con tu propia lista
# (ej. extraída de la página de Fortune o de un CSV que ya tengas).
# ---------------------------------------------------------------------------
FORTUNE100_SAMPLE = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "NVDA", "TSLA", "UNH",
    "XOM", "JPM", "JNJ", "V", "PG", "HD", "MA", "CVX", "MRK", "ABBV", "PEP",
    "KO", "COST", "WMT", "BAC", "MCD", "DIS", "CSCO", "ABT", "CRM", "ACN",
    "NFLX", "ADBE", "TMO", "LIN", "DHR", "VZ", "NKE", "TXN", "PM", "NEE",
    "WFC", "RTX", "UPS", "BMY", "QCOM", "HON", "INTC", "AMGN", "UNP", "LOW",
    "IBM", "GE", "CAT", "BA", "GS", "SBUX", "INTU", "AMD", "PLD", "ELV",
    "DE", "MDT", "BLK", "AMT", "ISRG", "GILD", "ADP", "LMT", "SYK", "TJX",
    "MDLZ", "CVS", "C", "MMC", "SCHW", "CI", "ZTS", "MO", "PGR", "BSX",
    "SO", "T", "DUK", "FDX", "BDX", "ITW", "CL", "EOG", "APD", "WM",
    "AON", "SHW", "TGT", "USB", "NSC", "MU", "HCA", "EMR", "PNC", "MCK",
]

# ---------------------------------------------------------------------------
# MVP: 25 empresas diversificadas por sector, todas con alta cobertura
# mediática (importante para que ImpactMean/NewsCount no sean puro ruido).
# Distribución:
#   Tecnología (5):        AAPL, MSFT, GOOGL, NVDA, META
#   Consumo discrecional (4): AMZN, HD, NKE, MCD
#   Salud (4):              UNH, JNJ, ABBV, MRK
#   Financiero (4):         JPM, BAC, V, MA
#   Energía (2):            XOM, CVX
#   Industrial (2):         BA, CAT
#   Consumo básico (3):     PG, KO, WMT
#   Comunicación/Entretenimiento (1): DIS
# ---------------------------------------------------------------------------
MVP_25_SAMPLE = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META",
    "AMZN", "HD", "NKE", "MCD",
    "UNH", "JNJ", "ABBV", "MRK",
    "JPM", "BAC", "V", "MA",
    "XOM", "CVX",
    "BA", "CAT",
    "PG", "KO", "WMT",
    "DIS",
]


TECHNICAL_COLUMNS = [
    "rsi_14", "macd", "macd_signal", "macd_hist",
    "ema_10", "ema_20", "ema_50",
    "volatility_20d", "daily_return", "weekly_return",
]


# ---------------------------------------------------------------------------
# Cálculo de indicadores
# ---------------------------------------------------------------------------

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI con suavizado de Wilder (estándar de la industria)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # neutral cuando no hay suficiente historia o avg_loss=0
    return rsi


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False).mean()
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recibe un DataFrame con columnas Open, High, Low, Close, Volume
    (índice = fecha, ordenado ascendentemente) y agrega los indicadores.
    """
    df = df.copy()
    close = df["Close"]

    df["rsi_14"] = compute_rsi(close, 14)

    macd, macd_signal, macd_hist = compute_macd(close)
    df["macd"] = macd
    df["macd_signal"] = macd_signal
    df["macd_hist"] = macd_hist

    df["ema_10"] = close.ewm(span=10, adjust=False).mean()
    df["ema_20"] = close.ewm(span=20, adjust=False).mean()
    df["ema_50"] = close.ewm(span=50, adjust=False).mean()

    df["daily_return"] = close.pct_change(1)
    df["weekly_return"] = close.pct_change(5)

    # Volatilidad: desviación estándar móvil de los retornos diarios (ventana 20 días)
    df["volatility_20d"] = df["daily_return"].rolling(window=20).std()

    return df


# ---------------------------------------------------------------------------
# Descarga de datos
# ---------------------------------------------------------------------------

def fetch_ticker_data(ticker: str, start: str, end: str, max_retries: int = 3) -> pd.DataFrame | None:
    """Descarga OHLCV de un ticker vía yfinance, con reintentos simples."""
    for attempt in range(1, max_retries + 1):
        try:
            data = yf.download(
                ticker, start=start, end=end,
                progress=False, auto_adjust=True, threads=False,
            )
            if data is None or data.empty:
                return None
            # yfinance a veces devuelve columnas multiindex si se piden varios tickers;
            # acá pedimos uno a uno así que aplanamos por si acaso.
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return data[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            if attempt == max_retries:
                print(f"  [WARN] {ticker}: fallo tras {max_retries} intentos ({e})", file=sys.stderr)
                return None
            time.sleep(2 * attempt)  # backoff simple
    return None


def fetch_ticker_metadata(ticker: str) -> dict:
    """Obtiene sector/industria del ticker (Paso 8: el modelo necesita saber qué empresa observa)."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
        }
    except Exception:
        return {"sector": "Unknown", "industry": "Unknown"}


def build_dataset(tickers: list[str], years: float = 2.0) -> pd.DataFrame:
    end = datetime.today()
    start = end - timedelta(days=int(years * 365.25))
    start_str, end_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    all_rows = []
    for ticker in tqdm(tickers, desc="Descargando tickers"):
        raw = fetch_ticker_data(ticker, start_str, end_str)
        if raw is None or len(raw) < 60:
            # Muy pocos datos para calcular EMA50/RSI de forma confiable
            continue

        meta = fetch_ticker_metadata(ticker)
        enriched = compute_indicators(raw)
        enriched["Empresa"] = ticker
        enriched["sector"] = meta["sector"]
        enriched["industry"] = meta["industry"]
        enriched.index.name = "Fecha"  # robusto sin importar el nombre original del índice
        enriched = enriched.reset_index()
        all_rows.append(enriched)

    if not all_rows:
        raise RuntimeError("No se pudo descargar ningún ticker. Revisa conexión / símbolos.")

    full = pd.concat(all_rows, ignore_index=True)
    full = full.sort_values(["Empresa", "Fecha"]).reset_index(drop=True)
    return full


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Descarga precios y calcula indicadores técnicos.")
    parser.add_argument("--tickers", type=str, default=None,
                         help="CSV con una columna 'ticker'. Si no se da, usa MVP_25_SAMPLE "
                              "(o FORTUNE100_SAMPLE si pasas --full-universe).")
    parser.add_argument("--full-universe", action="store_true",
                         help="Usar la lista completa de 100 tickers (FORTUNE100_SAMPLE) "
                              "en vez del MVP de 25.")
    parser.add_argument("--years", type=float, default=2.0, help="Años de histórico a descargar.")
    parser.add_argument("--out", type=str, default="dataset_precios.csv", help="Ruta del CSV de salida.")
    args = parser.parse_args()

    if yf is None:
        print("Falta yfinance. Instálalo con: pip install yfinance", file=sys.stderr)
        sys.exit(1)

    if args.tickers:
        tickers = pd.read_csv(args.tickers)["ticker"].dropna().unique().tolist()
    elif args.full_universe:
        print("[INFO] Usando FORTUNE100_SAMPLE (100 tickers) — universo completo. "
              "Revísala/reemplázala con tu propia lista del Fortune 100.")
        tickers = FORTUNE100_SAMPLE
    else:
        print(f"[INFO] Usando MVP_25_SAMPLE ({len(MVP_25_SAMPLE)} tickers diversificados por sector) "
              "para la fase de prueba de concepto.")
        tickers = MVP_25_SAMPLE

    print(f"[INFO] {len(tickers)} tickers, últimos {args.years} años.")
    dataset = build_dataset(tickers, years=args.years)

    print(f"[INFO] Dataset final: {dataset.shape[0]} filas, {dataset.shape[1]} columnas.")
    dataset.to_csv(args.out, index=False)
    print(f"[INFO] Guardado en {args.out}")


if __name__ == "__main__":
    main()
