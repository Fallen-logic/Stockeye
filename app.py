from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf

app = Flask(__name__)
CORS(app)  # Allow all origins so your dashboard can call this API

TICKER_MAP = {
    "TCS":       "TCS.NS",
    "SBI":       "SBIN.NS",
    "HDFC":      "HDFCBANK.NS",
    "ICICI":     "ICICIBANK.NS",
    "TITAN":     "TITAN.NS",
    "INFOSYS":   "INFY.NS",
    "CIPLA":     "CIPLA.NS",
    "ULTRATECH": "ULTRACEMCO.NS",
    "RELIANCE":  "RELIANCE.NS",
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "INDIAVIX":  "^INDIAVIX",
    "SENSEX":    "^BSESN",
}

TIMEFRAME_MAP = {
    "1D": {"period": "1d",  "interval": "5m"},
    "1W": {"period": "5d",  "interval": "30m"},
    "1M": {"period": "1mo", "interval": "1d"},
    "3M": {"period": "3mo", "interval": "1d"},
    "1Y": {"period": "1y",  "interval": "1wk"},
}

@app.route("/")
def index():
    return jsonify({"status": "StockEye API is running!"})

@app.route("/quote/<ticker>")
def get_quote(ticker):
    yf_sym = TICKER_MAP.get(ticker.upper())
    if not yf_sym:
        return jsonify({"error": f"Unknown ticker: {ticker}"}), 404
    try:
        t = yf.Ticker(yf_sym)
        hist = t.history(period="2d")
        info = t.fast_info
        if hist.empty:
            return jsonify({"error": "No data"}), 404
        price = round(float(hist["Close"].iloc[-1]), 2)
        prev  = round(float(hist["Close"].iloc[-2]) if len(hist) > 1 else hist["Close"].iloc[-1], 2)
        return jsonify({
            "ticker": ticker,
            "price":  price,
            "prev":   prev,
            "open":   round(float(hist["Open"].iloc[-1]), 2),
            "high":   round(float(hist["High"].iloc[-1]), 2),
            "low":    round(float(hist["Low"].iloc[-1]),  2),
            "change": round(price - prev, 2),
            "change_pct": round((price - prev) / prev * 100, 2),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/quotes")
def get_all_quotes():
    results = {}
    for ticker, yf_sym in TICKER_MAP.items():
        try:
            hist = yf.Ticker(yf_sym).history(period="2d")
            if hist.empty:
                continue
            price = round(float(hist["Close"].iloc[-1]), 2)
            prev  = round(float(hist["Close"].iloc[-2]) if len(hist) > 1 else price, 2)
            results[ticker] = {
                "price": price, "prev": prev,
                "open":  round(float(hist["Open"].iloc[-1]), 2),
                "high":  round(float(hist["High"].iloc[-1]), 2),
                "low":   round(float(hist["Low"].iloc[-1]),  2),
                "change": round(price - prev, 2),
                "change_pct": round((price - prev) / prev * 100, 2),
            }
        except:
            pass
    return jsonify(results)

@app.route("/chart/<ticker>")
def get_chart(ticker):
    tf = request.args.get("tf", "1D").upper()
    yf_sym = TICKER_MAP.get(ticker.upper())
    if not yf_sym:
        return jsonify({"error": f"Unknown ticker: {ticker}"}), 404
    cfg = TIMEFRAME_MAP.get(tf, TIMEFRAME_MAP["1D"])
    try:
        hist = yf.Ticker(yf_sym).history(period=cfg["period"], interval=cfg["interval"])
        if hist.empty:
            # fallback: try a broader period
            hist = yf.Ticker(yf_sym).history(period="5d", interval="30m")
        if hist.empty:
            return jsonify({"data": []})

        # Normalize timezone-aware index to UTC timestamps
        import pandas as pd
        if hist.index.tz is not None:
            hist.index = hist.index.tz_convert("UTC")
        else:
            hist.index = hist.index.tz_localize("UTC")

        data = []
        seen = set()
        for ts, row in hist.iterrows():
            try:
                t = int(pd.Timestamp(ts).timestamp())
                if t in seen:
                    continue
                seen.add(t)
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                c = float(row["Close"])
                # skip NaN rows
                if any(v != v for v in [o, h, l, c]):
                    continue
                data.append({
                    "time":  t,
                    "open":  round(o, 2),
                    "high":  round(h, 2),
                    "low":   round(l, 2),
                    "close": round(c, 2),
                })
            except:
                continue

        data.sort(key=lambda x: x["time"])
        return jsonify({"ticker": ticker, "tf": tf, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False)
