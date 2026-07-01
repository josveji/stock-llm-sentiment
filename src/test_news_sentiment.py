"""
test_news_sentiment.py
========================
Prueba puntual del endpoint NEWS_SENTIMENT de Alpha Vantage.
Objetivo: confirmar que el histórico de noticias cubre al menos ~2 años
hacia atrás, ANTES de programar el pipeline completo.

Gasta exactamente 1 request de tu cuota diaria (25/día en el tier gratuito).

Uso:
    1) Crea un archivo .env en la raíz del proyecto con:
           ALPHAVANTAGE_API_KEY=tu_key_aqui
    2) pip install python-dotenv requests
    3) python test_news_sentiment.py
"""

import os
import sys
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()  # busca un archivo .env en el directorio actual (o superiores) y carga sus variables

API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY")
if not API_KEY:
    print("[ERROR] No se encontró ALPHAVANTAGE_API_KEY.")
    print("  Crea un archivo .env en la raíz del proyecto con esta línea:")
    print('  ALPHAVANTAGE_API_KEY=tu_key_aqui')
    sys.exit(1)

TICKER = "AAPL"  # empresa con altísima cobertura mediática, buen caso de prueba
TWO_YEARS_AGO = (datetime.today() - timedelta(days=730)).strftime("%Y%m%dT0000")

params = {
    "function": "NEWS_SENTIMENT",
    "tickers": TICKER,
    "time_from": TWO_YEARS_AGO,   # pedimos noticias desde hace ~2 años
    "sort": "EARLIEST",            # para ver qué tan atrás realmente responde
    "limit": 1000,                 # máximo permitido, mismo costo de 1 request
    "apikey": API_KEY,
}

print(f"[INFO] Consultando NEWS_SENTIMENT para {TICKER} desde {TWO_YEARS_AGO}...")
resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
data = resp.json()

# Manejo de errores comunes de Alpha Vantage (no siempre devuelven HTTP error code)
if "Note" in data:
    print("[RATE LIMIT]", data["Note"])
    sys.exit(1)
if "Information" in data:
    print("[INFO/ERROR]", data["Information"])
    sys.exit(1)
if "feed" not in data:
    print("[ERROR] Respuesta inesperada:", data)
    sys.exit(1)

feed = data["feed"]
print(f"\n[RESULTADO] {len(feed)} artículos devueltos.")

if feed:
    dates = [a["time_published"][:8] for a in feed]  # YYYYMMDD
    earliest = datetime.strptime(min(dates), "%Y%m%d")
    latest = datetime.strptime(max(dates), "%Y%m%d")
    days_covered = max((latest - earliest).days, 1)

    print(f"  Fecha más antigua en la respuesta: {min(dates)}")
    print(f"  Fecha más reciente en la respuesta: {max(dates)}")
    print(f"  Solicitamos desde: {TWO_YEARS_AGO[:8]}")
    print(f"  Días cubiertos por estos {len(feed)} artículos: {days_covered}")
    print(f"  Densidad: ~{len(feed) / days_covered:.1f} artículos/día para {TICKER}")

    if len(feed) == 1000:
        est_days_total = 730
        est_requests_per_ticker = est_days_total / days_covered
        print(f"  [PROYECCIÓN] Si la densidad se mantiene constante, cubrir 2 años "
              f"de {TICKER} solo tomaría ~{est_requests_per_ticker:.1f} requests "
              f"(trayendo 1000 artículos por llamada y avanzando time_from).")
    print()
    print("  Ejemplo de artículo:")
    sample = feed[0]
    print(f"    Título: {sample.get('title')}")
    print(f"    Fecha: {sample.get('time_published')}")
    print(f"    Fuente: {sample.get('source')}")
    ticker_sent = [t for t in sample.get("ticker_sentiment", []) if t["ticker"] == TICKER]
    if ticker_sent:
        print(f"    Sentiment score ({TICKER}): {ticker_sent[0].get('ticker_sentiment_score')}")
        print(f"    Relevance score ({TICKER}): {ticker_sent[0].get('relevance_score')}")
else:
    print("  No se devolvieron artículos. Puede que el rango de fechas no tenga cobertura.")
