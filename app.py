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
    # Livemint — India business & finance
    "Mint: News":      "https://www.livemint.com/rss/news",
    "Mint: Markets":   "https://www.livemint.com/rss/markets",
    "Mint: Companies": "https://www.livemint.com/rss/companies",
    "Mint: Economy":   "https://www.livemint.com/rss/economy",
    "Mint: Money":     "https://www.livemint.com/rss/money",
    "Mint: Tech":      "https://www.livemint.com/rss/technology",
    # The Economist — global analysis
    "Eco: Finance":    "https://www.economist.com/finance-and-economics/rss.xml",
    "Eco: Business":   "https://www.economist.com/business/rss.xml",
    "Eco: World":      "https://www.economist.com/international/rss.xml",
    "Eco: Leaders":    "https://www.economist.com/leaders/rss.xml",
    "Eco: Asia":       "https://www.economist.com/asia/rss.xml",
    "Eco: Science":    "https://www.economist.com/science-and-technology/rss.xml",
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
        media_ns = {'media': 'http://search.yahoo.com/mrss/'}
        for item in items[:20]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            if not link:
                link = item.findtext("guid", "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "").strip()
            desc = re.sub(r'<[^>]+>', '', desc).strip()[:200]
            try:
                ts = int(parsedate_to_datetime(pub).timestamp()) if pub else 0
            except:
                ts = 0
            # Extract image from RSS
            image = None
            for tag in ['media:content','media:thumbnail']:
                el = item.find(tag, media_ns)
                if el is not None:
                    image = el.get('url')
                    if image: break
            if not image:
                enc = item.find('enclosure')
                if enc is not None and enc.get('type','').startswith('image'):
                    image = enc.get('url')
            if not image:
                raw_desc = item.findtext("description","")
                img_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_desc)
                if img_m: image = img_m.group(1)
            if title:
                articles.append({"title": title, "link": link, "desc": desc, "pub": pub, "ts": ts, "image": image})
        articles.sort(key=lambda x: x["ts"], reverse=True)
        return jsonify({"category": category, "articles": articles, "feeds": list(NEWS_FEEDS.keys())})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


import json, os, time as _time

CACHE_FILE = "/tmp/stats_cache.json"

def _load_cache():
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                return json.load(f)
    except: pass
    return {}

def _save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except: pass

# NSE symbol map for equity stocks
NSE_MAP = {
    "TCS": "TCS", "SBI": "SBIN", "HDFC": "HDFCBANK", "ICICI": "ICICIBANK",
    "TITAN": "TITAN", "INFOSYS": "INFY", "CIPLA": "CIPLA",
    "ULTRATECH": "ULTRACEMCO", "RELIANCE": "RELIANCE",
}
NSE_INDEX_MAP = {
    "NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "INDIAVIX": "INDIA VIX",
}
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com",
}

def get_nse_session():
    s = req.Session()
    base_headers = {**NSE_HEADERS, "Accept": "text/html,application/xhtml+xml"}
    s.get("https://www.nseindia.com", headers=base_headers, timeout=10)
    s.get("https://www.nseindia.com/market-data/live-equity-market", headers=base_headers, timeout=10)
    return s

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

if __name__ == "__main__":
    app.run(debug=False)
