from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
import os

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

# Livemint RSS feeds — direct
NEWS_FEEDS = {
    "News":      "https://www.livemint.com/rss/news",
    "Markets":   "https://www.livemint.com/rss/markets",
    "Companies": "https://www.livemint.com/rss/companies",
    "Economy":   "https://www.livemint.com/rss/economy",
    "Tech":      "https://www.livemint.com/rss/technology",
    "Money":     "https://www.livemint.com/rss/money",
}

@app.route("/news")
def get_news():
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    category = request.args.get("cat", "News")
    url = NEWS_FEEDS.get(category, NEWS_FEEDS["News"])

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.livemint.com/",
        }
        r = req.get(url, headers=headers, timeout=10)
        root = ET.fromstring(r.content)
        ns = {"media": "http://search.yahoo.com/mrss/"}
        articles = []
        for item in root.findall(".//item")[:20]:
            title = (item.findtext("title") or "").strip()
            link  = item.findtext("link") or ""
            desc  = (item.findtext("description") or "")[:200].strip()
            pub   = item.findtext("pubDate") or ""
            # timestamp
            try: ts = int(parsedate_to_datetime(pub).timestamp())
            except: ts = 0
            # image
            image = None
            mc = item.find("media:content", ns)
            if mc is not None: image = mc.get("url")
            if not image:
                mt = item.find("media:thumbnail", ns)
                if mt is not None: image = mt.get("url")
            if not image:
                enc = item.find("enclosure")
                if enc is not None and "image" in (enc.get("type") or ""):
                    image = enc.get("url")
            if not image and "<img" in desc:
                import re
                m = re.search("src=[\"']([\"']*[^\"']+[\"']*)", desc)
                if m: image = m.group(1)
            articles.append({"title": title, "link": link, "desc": desc, "image": image, "ts": ts, "pub": pub})

        return jsonify({"category": category, "articles": articles, "feeds": list(NEWS_FEEDS.keys())})
    except Exception as e:
        return jsonify({"error": str(e), "url": url}), 500


@app.route("/stats/<ticker>")
def get_stats(ticker):
    yf_sym = TICKER_MAP.get(ticker.upper())
    if not yf_sym:
        return jsonify({"error": f"Unknown ticker: {ticker}"}), 404

    cache = _load_cache()
    cached = cache.get(ticker)
    if cached and (_time.time() - cached.get("_ts", 0)) < 43200:
        return jsonify(cached)

    def fmt_cr(val):
        try:
            v = float(val)
            if v > 0: return f"₹{round(v/1e7, 2):,} Cr"
        except: pass
        return "—"

    def fmt_vol(val):
        try:
            v = float(val)
            if v >= 1e7: return f"{round(v/1e7,2)}Cr"
            if v >= 1e5: return f"{round(v/1e5,2)}L"
            return str(int(v))
        except: pass
        return "—"

    def fmt_f(val, dec=2):
        try:
            if val not in (None, "", "—", 0):
                return str(round(float(val), dec))
        except: pass
        return "—"

    try:
        nse_sym  = NSE_MAP.get(ticker.upper())
        idx_name = NSE_INDEX_MAP.get(ticker.upper())

        if nse_sym:
            s = get_nse_session()
            r = s.get(
                f"https://www.nseindia.com/api/quote-equity?symbol={nse_sym}",
                headers=NSE_HEADERS, timeout=10
            )
            data    = r.json()
            info    = data.get("priceInfo", {})
            meta    = data.get("metadata", {})
            secInfo = data.get("securityInfo", {})
            indInfo = data.get("industryInfo", {})
            w52     = info.get("weekHighLow", {})
            # Market cap = issued shares × LTP
            issued  = secInfo.get("issuedSize", 0)
            ltp     = info.get("lastPrice", 0)
            mcap    = fmt_cr(float(issued) * float(ltp)) if issued and ltp else "—"

            result = {
                "ticker":      ticker,
                "market_cap":  mcap,
                "pe_ratio":    fmt_f(meta.get("pdSymbolPe")),
                "eps":         "—",
                "week52_high": f"₹{fmt_f(w52.get('max'))}",
                "week52_low":  f"₹{fmt_f(w52.get('min'))}",
                "beta":        "—",
                "div_yield":   "—",
                "volume":      fmt_vol(info.get("totalTradedVolume")),
                "avg_volume":  "—",
                "sector":      indInfo.get("sector", "—"),
                "industry":    indInfo.get("industry", "—"),
                "yf_symbol":   yf_sym,
                "_ts":         _time.time(),
            }

        elif idx_name:
            s = get_nse_session()
            r = s.get("https://www.nseindia.com/api/allIndices", headers=NSE_HEADERS, timeout=10)
            items = r.json().get("data", [])
            data  = next((x for x in items if x.get("index") == idx_name), {})
            result = {
                "ticker":      ticker,
                "market_cap":  "—",
                "pe_ratio":    fmt_f(data.get("pe")),
                "eps":         fmt_f(data.get("eps")),
                "week52_high": f"₹{fmt_f(data.get('yearHigh'))}",
                "week52_low":  f"₹{fmt_f(data.get('yearLow'))}",
                "beta":        "—",
                "div_yield":   fmt_f(data.get("dy")) + "%" if data.get("dy") else "—",
                "volume":      "—",
                "avg_volume":  "—",
                "sector":      "Index",
                "industry":    "—",
                "yf_symbol":   yf_sym,
                "_ts":         _time.time(),
            }

        else:
            # SENSEX — yfinance fast_info fallback
            fi = yf.Ticker(yf_sym).fast_info
            result = {
                "ticker":      ticker,
                "market_cap":  "—",
                "pe_ratio":    "—",
                "eps":         "—",
                "week52_high": fmt_f(getattr(fi, "year_high", None)),
                "week52_low":  fmt_f(getattr(fi, "year_low", None)),
                "beta":        "—",
                "div_yield":   "—",
                "volume":      "—",
                "avg_volume":  "—",
                "sector":      "Index",
                "industry":    "—",
                "yf_symbol":   yf_sym,
                "_ts":         _time.time(),
            }

        cache[ticker] = result
        _save_cache(cache)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

import json as _json, os as _os

DRAWINGS_FILE = '/tmp/drawings.json'

def load_drawings():
    try:
        if _os.path.exists(DRAWINGS_FILE):
            with open(DRAWINGS_FILE) as f:
                return _json.load(f)
    except: pass
    return {}

def save_drawings(data):
    try:
        with open(DRAWINGS_FILE, 'w') as f:
            _json.dump(data, f)
    except: pass

@app.route("/drawings/<ticker>/<tf>", methods=["GET"])
def get_drawings(ticker, tf):
    data = load_drawings()
    key = f"{ticker.upper()}_{tf}"
    return jsonify(data.get(key, []))

@app.route("/drawings/<ticker>/<tf>", methods=["POST"])
def set_drawings(ticker, tf):
    data = load_drawings()
    key = f"{ticker.upper()}_{tf}"
    data[key] = request.json
    save_drawings(data)
    return jsonify({"ok": True})

@app.route("/summarize", methods=["POST"])
def summarize():
    data = request.get_json()
    title = data.get("title", "")
    desc  = data.get("desc", "")
    link  = data.get("link", "")

    # Try to fetch article content
    article_text = ""
    try:
        r = req.get(link, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }, timeout=8)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script","style","nav","header","footer","aside"]):
            tag.decompose()
        article_text = " ".join(soup.get_text(" ", strip=True).split())[:3000]
    except:
        article_text = desc

    prompt = f"""You are a sharp financial news analyst. Summarize this article concisely.

Title: {title}
Content: {article_text}

Provide:
1. A 2-sentence TL;DR
2. 3-4 key bullet points
3. One line on why it matters for Indian investors

Be concise and direct. No fluff."""

    try:
        groq_key = os.environ.get("GROQ_API_KEY")
        response = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1000,
                "temperature": 0.5
            },
            timeout=30
        )
        result = response.json()
        summary = result["choices"][0]["message"]["content"]
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/debug-env")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "NOT SET")
    return jsonify({"key_set": key != "NOT SET", "key_preview": key[:10] + "..." if key != "NOT SET" else "NOT SET"})


if __name__ == "__main__":
    app.run(debug=False)
