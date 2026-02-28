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


import xml.etree.ElementTree as ET
import requests as req
from email.utils import parsedate_to_datetime

NEWS_FEEDS = {
    "Top Stories": "https://www.thehindu.com/feeder/default.rss",
    "Business":    "https://www.thehindu.com/business/feeder/default.rss",
    "Technology":  "https://www.thehindu.com/sci-tech/technology/feeder/default.rss",
    "World":       "https://www.thehindu.com/news/international/feeder/default.rss",
    "Sports":      "https://www.thehindu.com/sport/feeder/default.rss",
    "Science":     "https://www.thehindu.com/sci-tech/science/feeder/default.rss",
    "Markets":     "https://www.thehindu.com/business/markets/feeder/default.rss",
}

@app.route("/news")
def get_news():
    import re
    category = request.args.get("cat", "Top Stories")
    feed_url = NEWS_FEEDS.get(category, NEWS_FEEDS["Top Stories"])
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        r = req.get(feed_url, timeout=15, headers=headers)
        # Check if response is actually XML
        content_type = r.headers.get("Content-Type", "")
        raw = r.content
        # Try to parse as XML
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as pe:
            return jsonify({"error": f"Feed parse error: {str(pe)}", "raw_preview": raw[:200].decode('utf-8','ignore')}), 500
        items = root.findall(".//item")
        articles = []
        for item in items[:20]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            # some feeds use <guid> as link
            if not link:
                link = item.findtext("guid", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            desc = re.sub(r'<[^>]+>', '', desc).strip()[:200]
            try:
                ts = int(parsedate_to_datetime(pub).timestamp()) if pub else 0
            except:
                ts = 0
            if title:
                articles.append({"title": title, "link": link, "desc": desc, "pub": pub, "ts": ts})
        articles.sort(key=lambda x: x["ts"], reverse=True)
        return jsonify({"category": category, "articles": articles, "feeds": list(NEWS_FEEDS.keys())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stats/<ticker>")
def get_stats(ticker):
    yf_sym = TICKER_MAP.get(ticker.upper())
    if not yf_sym:
        return jsonify({"error": f"Unknown ticker: {ticker}"}), 404
    try:
        info = yf.Ticker(yf_sym).info
        def safe(key, fmt=None):
            val = info.get(key)
            if val is None or val == "N/A":
                return "—"
            try:
                if fmt == "cr":
                    return f"₹{round(val/1e7, 2):,} Cr"
                if fmt == "pct":
                    return f"{round(val*100, 2)}%"
                if fmt == "2f":
                    return f"{round(val, 2)}"
                if fmt == "vol":
                    if val >= 1e7: return f"{round(val/1e7,2)}Cr"
                    if val >= 1e5: return f"{round(val/1e5,2)}L"
                    return str(val)
                return str(val)
            except:
                return "—"

        return jsonify({
            "ticker":        ticker,
            "market_cap":    safe("marketCap", "cr"),
            "pe_ratio":      safe("trailingPE", "2f"),
            "eps":           safe("trailingEps", "2f"),
            "week52_high":   safe("fiftyTwoWeekHigh", "2f"),
            "week52_low":    safe("fiftyTwoWeekLow", "2f"),
            "beta":          safe("beta", "2f"),
            "div_yield":     safe("dividendYield", "pct"),
            "volume":        safe("volume", "vol"),
            "avg_volume":    safe("averageVolume", "vol"),
            "sector":        info.get("sector", "—"),
            "industry":      info.get("industry", "—"),
            "yf_symbol":     yf_sym,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=False)
