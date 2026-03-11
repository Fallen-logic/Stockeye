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
    # Check price alerts on every quotes refresh
    try:
        check_and_trigger_alerts(results)
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
                v = 0
                try:
                    raw_v = row.get("Volume", 0) if hasattr(row, 'get') else row["Volume"]
                    if raw_v == raw_v:  # NaN check
                        v = int(float(raw_v))
                except:
                    v = 0
                data.append({
                    "time":   t,
                    "open":   round(o, 2),
                    "high":   round(h, 2),
                    "low":    round(l, 2),
                    "close":  round(c, 2),
                    "volume": v,
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
        if "choices" not in result:
            return jsonify({"error": result.get("error", {}).get("message", str(result))}), 500
        summary = result["choices"][0]["message"]["content"]
        return jsonify({"summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/debug-env")
def debug_env():
    key = os.environ.get("ANTHROPIC_API_KEY", "NOT SET")
    return jsonify({"key_set": key != "NOT SET", "key_preview": key[:10] + "..." if key != "NOT SET" else "NOT SET"})


@app.route("/context", methods=["POST"])
def get_context():
    data = request.get_json()
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "No query provided"}), 400

    prompt = f"""You are a knowledgeable financial and world affairs analyst.

A news article has this headline: "{query}"

Provide background context in this exact format:

BACKGROUND
2-3 sentences of essential background on the topic, companies, or people involved.

KEY FACTORS
- Factor 1
- Factor 2
- Factor 3

INDIA ANGLE
One sentence on how this connects to India or Indian markets.

Be factual and concise. No fluff."""

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
                "max_tokens": 500,
                "temperature": 0.3
            },
            timeout=30
        )
        result = response.json()
        if "choices" not in result:
            return jsonify({"error": result.get("error", {}).get("message", str(result))}), 500
        context_text = result["choices"][0]["message"]["content"]
        return jsonify({"context": context_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    ticker    = data.get("ticker", "")
    tf        = data.get("tf", "1D")
    candles   = data.get("candles", [])   # last 50 OHLCV
    patterns  = data.get("patterns", [])  # detected pattern names
    stats     = data.get("stats", {})     # price, change, pe, 52w high/low, etc
    indicators = data.get("indicators", {})

    # Build candle summary — last 10 for brevity
    recent = candles[-10:] if len(candles) >= 10 else candles
    candle_lines = []
    for c in recent:
        import datetime
        try:
            dt = datetime.datetime.utcfromtimestamp(c["time"]).strftime("%d %b")
        except:
            dt = str(c.get("time",""))
        candle_lines.append(
            f"  {dt}: O={c.get('open',0):.2f} H={c.get('high',0):.2f} L={c.get('low',0):.2f} C={c.get('close',0):.2f} V={c.get('volume',0):,.0f}"
        )
    candle_text = "\n".join(candle_lines)

    pattern_text = ", ".join(patterns) if patterns else "None detected"

    prompt = f"""You are a senior equity analyst at a top Indian brokerage. Analyze this stock chart data and give a professional technical analysis.

STOCK: {ticker}
TIMEFRAME: {tf}
CURRENT PRICE: {stats.get('price', 'N/A')}
CHANGE: {stats.get('change', 'N/A')}
52W HIGH: {stats.get('high52', 'N/A')}
52W LOW: {stats.get('low52', 'N/A')}
P/E RATIO: {stats.get('pe', 'N/A')}
MARKET CAP: {stats.get('marketcap', 'N/A')}
ACTIVE INDICATORS: {', '.join([k for k,v in indicators.items() if v])}

RECENT OHLCV (last 10 candles):
{candle_text}

DETECTED PATTERNS: {pattern_text}

Give a structured technical analysis in this exact format:

TREND
State the current trend (bullish/bearish/sideways) with reasoning based on price action.

SUPPORT & RESISTANCE
Key support: ₹[price]
Key resistance: ₹[price]
Brief reasoning.

PATTERN ANALYSIS
Interpret the detected patterns and what they signal.

MOMENTUM
Comment on volume trends and momentum.

OUTLOOK ({tf})
Short paragraph on the likely near-term direction and what to watch for.

RISK
One key risk to the bullish/bearish case.

Keep it sharp, data-driven, and under 300 words total. Use ₹ for prices."""

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
                "max_tokens": 800,
                "temperature": 0.3
            },
            timeout=30
        )
        result = response.json()
        if "choices" not in result:
            return jsonify({"error": result.get("error", {}).get("message", str(result))}), 500
        analysis = result["choices"][0]["message"]["content"]
        return jsonify({"analysis": analysis})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── NOTION PRICE ALERTS ─────────────────────────────
NOTION_TOKEN   = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID   = os.environ.get("NOTION_DB_ID", "31d9b2ec-6332-806c-b1fc-000b2dd78afa")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
ALERT_EMAIL    = "anshkatiyar4105@gmail.com"

def send_alert_email(stock, current_price, target_price, alert_type):
    """Send price alert email via Resend."""
    try:
        arrow  = "🔼" if alert_type == "Above" else "🔽"
        import datetime
        now    = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        time_str = now.strftime("%d %b %Y, %I:%M %p IST")
        req.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json={
                "from":    "StockEye Alerts <onboarding@resend.dev>",
                "to":      [ALERT_EMAIL],
                "subject": f"🔔 StockEye Alert — {stock} hit ₹{current_price:,.2f}",
                "html":    f"""
                <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;background:#0f0f14;color:#e0e0f0;border-radius:12px;padding:28px;border:1px solid #2a2a3a;">
                  <div style="font-size:22px;font-weight:bold;color:#ffc800;margin-bottom:4px;">🔔 Price Alert Triggered</div>
                  <div style="color:#666;font-size:12px;margin-bottom:24px;">{time_str}</div>
                  <table style="width:100%;border-collapse:collapse;">
                    <tr><td style="color:#888;padding:8px 0;border-bottom:1px solid #1a1a2a;">Stock</td><td style="color:#ffc800;font-weight:bold;text-align:right;padding:8px 0;border-bottom:1px solid #1a1a2a;">{stock}</td></tr>
                    <tr><td style="color:#888;padding:8px 0;border-bottom:1px solid #1a1a2a;">Alert Type</td><td style="text-align:right;padding:8px 0;border-bottom:1px solid #1a1a2a;">{alert_type} {arrow}</td></tr>
                    <tr><td style="color:#888;padding:8px 0;border-bottom:1px solid #1a1a2a;">Target Price</td><td style="text-align:right;padding:8px 0;border-bottom:1px solid #1a1a2a;">₹{target_price:,.2f}</td></tr>
                    <tr><td style="color:#888;padding:8px 0;">Current Price</td><td style="color:{'#00e5a0' if alert_type == 'Above' else '#ff4d6d'};font-weight:bold;text-align:right;padding:8px 0;">₹{current_price:,.2f}</td></tr>
                  </table>
                  <div style="margin-top:24px;font-size:11px;color:#444;">Sent by StockEye • Your personal market dashboard</div>
                </div>
                """
            },
            timeout=10
        )
    except Exception as e:
        print(f"Email error: {e}")

NOTION_HEADERS = lambda: {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def notion_get_watching_alerts():
    """Fetch all alerts with Status = Watching from Notion."""
    try:
        r = req.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=NOTION_HEADERS(),
            json={"filter": {"property": "Status", "select": {"equals": "Watching"}}},
            timeout=10
        )
        return r.json().get("results", [])
    except:
        return []

def notion_trigger_alert(page_id, current_price, stock="", target_price=None, alert_type=""):
    """Mark an alert as Triggered, record price+time, and @mention user via comment."""
    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    NOTION_USER_ID = "2ddd872b-594c-8123-b205-0002d09ca382"
    try:
        # Update page properties
        req.patch(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=NOTION_HEADERS(),
            json={"properties": {
                "Status":        {"select": {"name": "Triggered"}},
                "Current Price": {"number": current_price},
                "Triggered at":  {"date": {"start": now}},
            }},
            timeout=10
        )
        # Add comment with @mention to trigger phone notification
        arrow = "🔼" if alert_type == "Above" else "🔽"
        # Send email notification
        send_alert_email(stock, current_price, target_price, alert_type)

        req.post(
            "https://api.notion.com/v1/comments",
            headers=NOTION_HEADERS(),
            json={
                "parent": {"page_id": page_id},
                "rich_text": [
                    {"type": "mention", "mention": {"type": "user", "user": {"id": NOTION_USER_ID}}},
                    {"type": "text", "text": {"content": f" 🔔 ALERT TRIGGERED! {stock} hit ₹{current_price:,.2f} {arrow} target ₹{target_price:,.2f}"}}
                ]
            },
            timeout=10
        )
    except:
        pass

def notion_create_alert(stock, target_price, alert_type, note=""):
    """Create a new Watching alert in Notion."""
    try:
        props = {
            "Stock":        {"title": [{"text": {"content": stock}}]},
            "Target Price": {"number": target_price},
            "Alert Type":   {"select": {"name": alert_type}},
            "Status":       {"select": {"name": "Watching"}},
        }
        if note:
            props["Note"] = {"rich_text": [{"text": {"content": note}}]}
        r = req.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS(),
            json={"parent": {"database_id": NOTION_DB_ID}, "properties": props},
            timeout=10
        )
        result = r.json()
        if r.status_code != 200:
            return {"error": f"Notion API {r.status_code}: {result.get('message', str(result))}"}
        return result
    except Exception as e:
        return {"error": str(e)}

@app.route("/alerts/test")
def test_notion():
    """Debug: test Notion connection."""
    try:
        key = os.environ.get("NOTION_TOKEN", "NOT SET")
        db  = os.environ.get("NOTION_DB_ID", "NOT SET")
        r = req.get(
            f"https://api.notion.com/v1/databases/{db}",
            headers=NOTION_HEADERS(),
            timeout=10
        )
        return jsonify({
            "token_set": key != "NOT SET",
            "token_preview": key[:12] + "..." if key != "NOT SET" else "NOT SET",
            "db_id": db,
            "notion_status": r.status_code,
            "notion_response": r.json().get("title", r.json().get("message", "ok"))
        })
    except Exception as e:
        return jsonify({"error": str(e)})

def check_and_trigger_alerts(current_prices):
    """Check all watching alerts against current prices and trigger if hit."""
    alerts = notion_get_watching_alerts()
    triggered = []
    for alert in alerts:
        props = alert.get("properties", {})
        try:
            stock        = props["Stock"]["title"][0]["text"]["content"].upper()
            target_price = props["Target Price"]["number"]
            alert_type   = props["Alert Type"]["select"]["name"]  # "Above" or "Below"
            page_id      = alert["id"]
        except:
            continue

        price_data = current_prices.get(stock)
        if not price_data:
            continue
        current_price = price_data.get("price")
        if not current_price:
            continue

        hit = (alert_type == "Above" and current_price >= target_price) or               (alert_type == "Below" and current_price <= target_price)

        if hit:
            notion_trigger_alert(page_id, current_price, stock=stock, target_price=target_price, alert_type=alert_type)
            triggered.append({"stock": stock, "target": target_price, "current": current_price, "type": alert_type})

    return triggered

@app.route("/alerts", methods=["GET"])
def get_alerts():
    try:
        alerts = notion_get_watching_alerts()
        result = []
        for a in alerts:
            props = a.get("properties", {})
            try:
                note_rich = props.get("Note", {}).get("rich_text", [])
                result.append({
                    "id":           a["id"],
                    "stock":        props["Stock"]["title"][0]["text"]["content"],
                    "target_price": props["Target Price"]["number"],
                    "alert_type":   props["Alert Type"]["select"]["name"],
                    "status":       props["Status"]["select"]["name"],
                    "note":         note_rich[0]["text"]["content"] if note_rich else "",
                })
            except Exception as e:
                continue
        return jsonify({"alerts": result})
    except Exception as e:
        return jsonify({"error": str(e), "alerts": []}), 500

@app.route("/alerts", methods=["POST"])
def create_alert():
    data        = request.get_json()
    stock       = data.get("stock", "").upper()
    target      = data.get("target_price")
    alert_type  = data.get("alert_type", "Above")
    note        = data.get("note", "")
    if not stock or target is None:
        return jsonify({"error": "stock and target_price required"}), 400
    result = notion_create_alert(stock, float(target), alert_type, note)
    if "error" in result:
        return jsonify(result), 500
    return jsonify({"ok": True, "id": result.get("id")})
# ── END NOTION PRICE ALERTS ─────────────────────────


# ── BACKGROUND ALERT CHECKER ─────────────────────────────────────
import threading

def _alert_checker_loop():
    """Check price alerts every 30 seconds in background."""
    import time
    while True:
        try:
            results = {}
            for ticker, yf_sym in TICKER_MAP.items():
                try:
                    import yfinance as _yf
                    hist = _yf.Ticker(yf_sym).history(period="1d")
                    if not hist.empty:
                        results[ticker] = {"price": round(float(hist["Close"].iloc[-1]), 2)}
                except:
                    pass
            if results:
                check_and_trigger_alerts(results)
        except Exception as e:
            print(f"Alert checker error: {e}")
        time.sleep(30)

_alert_thread = threading.Thread(target=_alert_checker_loop, daemon=True)
_alert_thread.start()
# ── END BACKGROUND ALERT CHECKER ─────────────────────────────────

# ── IPO AUTO UPDATER ─────────────────────────────────────────────
NOTION_IPO_DB = "30d9b2ec-6332-80a9-abe6-000be9fda68d"

def scrape_ipos():
    """Fetch upcoming/open IPOs from NSE India API."""
    import datetime, re
    ipos = []
    try:
        nse_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }
        # Step 1: establish NSE session
        s = req.Session()
        s.get("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", headers=nse_headers, timeout=10)

        # Step 2: fetch IPO data
        r = s.get("https://www.nseindia.com/api/ipo-current-allotment", headers=nse_headers, timeout=10)
        data = r.json() if r.status_code == 200 else {}

        # Also fetch upcoming
        r2 = s.get("https://www.nseindia.com/api/ipo-current-allotment?category=upcoming", headers=nse_headers, timeout=10)
        data2 = r2.json() if r2.status_code == 200 else {}

        def parse_nse_date(s):
            if not s:
                return None
            for fmt in ["%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"]:
                try:
                    return datetime.datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
                except:
                    continue
            return None

        def determine_status(open_date, close_date):
            today = datetime.date.today()
            if not open_date or not close_date:
                return "🟡 Upcoming"
            od = datetime.date.fromisoformat(open_date)
            cd = datetime.date.fromisoformat(close_date)
            if od <= today <= cd:
                return "🟢 Open"
            elif today > cd:
                return "🔴 Closed"
            return "🟡 Upcoming"

        all_items = []
        if isinstance(data, list):
            all_items += data
        elif isinstance(data, dict):
            all_items += data.get("data", [])
        if isinstance(data2, list):
            all_items += data2
        elif isinstance(data2, dict):
            all_items += data2.get("data", [])

        seen = set()
        for item in all_items:
            try:
                name = item.get("companyName") or item.get("name") or item.get("symbol", "")
                if not name or name in seen:
                    continue
                seen.add(name)
                open_date  = parse_nse_date(item.get("openDate") or item.get("ipoOpenDate") or item.get("bidOpenDate", ""))
                close_date = parse_nse_date(item.get("closeDate") or item.get("ipoCloseDate") or item.get("bidCloseDate", ""))
                price_str  = str(item.get("priceBand") or item.get("issuePrice") or "")
                prices = re.findall(r"[\d,]+", price_str.replace(",", ""))
                price = int(prices[-1]) if prices else None
                lot_str = str(item.get("marketLot") or item.get("lotSize") or "")
                lots = re.findall(r"[\d]+", lot_str)
                lot = int(lots[0]) if lots else None
                exc_raw = str(item.get("exchange") or item.get("listingAt") or "NSE + BSE")
                exc = "NSE + BSE"
                if "NSE" in exc_raw.upper() and "BSE" not in exc_raw.upper():
                    exc = "NSE"
                elif "BSE" in exc_raw.upper() and "NSE" not in exc_raw.upper():
                    exc = "BSE"
                ipos.append({
                    "name": name,
                    "open_date": open_date,
                    "close_date": close_date,
                    "price": price,
                    "lot": lot,
                    "exchange": exc,
                    "status": determine_status(open_date, close_date)
                })
            except Exception as e:
                continue
        print(f"NSE IPO scrape: {len(ipos)} IPOs found")
    except Exception as e:
        print(f"IPO scrape error: {e}")
    return ipos

def get_existing_ipo_names():
    """Get names of IPOs already in Notion."""
    try:
        r = req.post(
            f"https://api.notion.com/v1/databases/{NOTION_IPO_DB}/query",
            headers=NOTION_HEADERS(),
            json={},
            timeout=10
        )
        results = r.json().get("results", [])
        return set(
            p["properties"]["Name of IPO"]["title"][0]["text"]["content"]
            for p in results
            if p["properties"].get("Name of IPO", {}).get("title")
        )
    except:
        return set()

def update_ipo_status():
    """Update Status of existing IPOs based on today's date."""
    import datetime
    try:
        r = req.post(
            f"https://api.notion.com/v1/databases/{NOTION_IPO_DB}/query",
            headers=NOTION_HEADERS(),
            json={"filter": {"or": [
                {"property": "Status", "select": {"equals": "🟡 Upcoming"}},
                {"property": "Status", "select": {"equals": "🟢 Open"}},
            ]}},
            timeout=10
        )
        today = datetime.date.today()
        for page in r.json().get("results", []):
            try:
                props = page["properties"]
                open_d  = props.get("Open Date", {}).get("date", {})
                close_d = props.get("Close Date", {}).get("date", {})
                if not open_d or not close_d:
                    continue
                od = datetime.date.fromisoformat(open_d["start"])
                cd = datetime.date.fromisoformat(close_d["start"])
                new_status = None
                if od <= today <= cd:
                    new_status = "🟢 Open"
                elif today > cd:
                    new_status = "🔴 Closed"
                elif today < od:
                    new_status = "🟡 Upcoming"
                if new_status:
                    req.patch(
                        f"https://api.notion.com/v1/pages/{page['id']}",
                        headers=NOTION_HEADERS(),
                        json={"properties": {"Status": {"select": {"name": new_status}}}},
                        timeout=10
                    )
            except:
                continue
    except Exception as e:
        print(f"IPO status update error: {e}")

def sync_ipos_to_notion():
    """Scrape IPOs and add new ones to Notion."""
    ipos = scrape_ipos()
    if not ipos:
        return {"synced": 0, "message": "No IPOs scraped"}
    existing = get_existing_ipo_names()
    added = 0
    for ipo in ipos:
        if ipo["name"] in existing:
            continue
        try:
            props = {
                "Name of IPO": {"title": [{"text": {"content": ipo["name"]}}]},
                "Status": {"select": {"name": ipo["status"]}},
            }
            if ipo["price"]:
                props["Price Per Share"] = {"number": ipo["price"]}
            if ipo["lot"]:
                props["Lot Size"] = {"number": ipo["lot"]}
            if ipo["open_date"]:
                props["Open Date"] = {"date": {"start": ipo["open_date"]}}
            if ipo["close_date"]:
                props["Close Date"] = {"date": {"start": ipo["close_date"]}}
                props["Due Date"]   = {"date": {"start": ipo["close_date"]}}
            if ipo["exchange"]:
                props["Exchange"] = {"select": {"name": ipo["exchange"]}}
            req.post(
                "https://api.notion.com/v1/pages",
                headers=NOTION_HEADERS(),
                json={"parent": {"database_id": NOTION_IPO_DB}, "properties": props},
                timeout=10
            )
            added += 1
        except Exception as e:
            print(f"IPO add error: {e}")
    # Also update status of existing IPOs
    update_ipo_status()
    return {"synced": added, "total_scraped": len(ipos)}

@app.route("/ipo/sync")
def ipo_sync():
    result = sync_ipos_to_notion()
    return jsonify(result)

@app.route("/ipo/debug")
def ipo_debug():
    """Debug: show raw NSE IPO API response."""
    try:
        nse_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.nseindia.com/",
            "Accept-Language": "en-US,en;q=0.9",
        }
        s = req.Session()
        s.get("https://www.nseindia.com/market-data/all-upcoming-issues-ipo", headers=nse_headers, timeout=10)

        results = {}
        urls = [
            "https://www.nseindia.com/api/ipo-current-allotment",
            "https://www.nseindia.com/api/ipo-current-allotment?category=upcoming",
            "https://www.nseindia.com/api/ipo-current-allotment?category=open",
            "https://www.nseindia.com/api/ipo",
        ]
        for url in urls:
            try:
                r = s.get(url, headers=nse_headers, timeout=10)
                data = r.json() if r.status_code == 200 else {"error": f"status {r.status_code}"}
                # Show first item structure if list
                if isinstance(data, list) and len(data) > 0:
                    results[url] = {"count": len(data), "sample": data[0]}
                elif isinstance(data, dict):
                    results[url] = {"keys": list(data.keys()), "sample": str(data)[:500]}
                else:
                    results[url] = data
            except Exception as e:
                results[url] = {"error": str(e)}
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)})

def _ipo_sync_loop():
    """Sync IPOs to Notion once a day."""
    import time
    while True:
        try:
            sync_ipos_to_notion()
            print("IPO sync complete")
        except Exception as e:
            print(f"IPO sync loop error: {e}")
        time.sleep(24 * 60 * 60)  # once per day

_ipo_thread = threading.Thread(target=_ipo_sync_loop, daemon=True)
_ipo_thread.start()
# ── END IPO AUTO UPDATER ─────────────────────────────────────────


if __name__ == "__main__":
    app.run(debug=False)
