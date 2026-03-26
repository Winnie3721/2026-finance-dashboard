#!/usr/bin/env python3
"""
update_data.py — GitHub Actions 每日執行
- 股市/外匯：yfinance 直接抓 Yahoo Finance（精確、免費）
- 新聞：RSS 優先，不足則 Claude API 補足
"""

import os, json, re, requests, feedparser, time
from datetime import datetime, timezone, timedelta

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False
    print("yfinance not available, falling back to Claude API")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
API_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
}
TW_TZ = timezone(timedelta(hours=8))

# ── Yahoo Finance 代碼對照 ────────────────────────────────────
STOCK_SYMBOLS = {
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "twii":   "^TWII",
    "nikkei": "^N225",
    "hsi":    "^HSI",
    "kospi":  "^KS11",
    "dax":    "^GDAXI",
    "ftse":   "^FTSE",
}

FX_SYMBOLS = {
    "usdtwd": "TWD=X",
    "eurusd": "EURUSD=X",
    "usdjpy": "JPY=X",
    "gbpusd": "GBPUSD=X",
    "usdcny": "CNY=X",
    "audusd": "AUDUSD=X",
    "xauusd": "GC=F",    # 黃金期貨
    "wti":    "CL=F",    # WTI原油期貨
}

# ── RSS 來源 ──────────────────────────────────────────────────
RSS_SOURCES = {
    "markets": [
        {"src": "經濟日報",    "key": "udn_econ",   "url": "https://money.udn.com/rssfeed/news/1001/5591?ch=money"},
        {"src": "工商時報",    "key": "ctee",        "url": "https://www.ctee.com.tw/rss"},
        {"src": "BBC Business","key": "bbc",         "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
        {"src": "CNBC",        "key": "cnbc",        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
        {"src": "MarketWatch", "key": "marketwatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
    ],
    "world": [
        {"src": "聯合新聞網",  "key": "udn_world",  "url": "https://udn.com/rssfeed/news/2/6638?ch=news"},
        {"src": "BBC World",   "key": "bbc",         "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"src": "AP World",    "key": "ap",          "url": "https://feeds.apnews.com/rss/apf-worldnews"},
        {"src": "Reuters",     "key": "reuters",     "url": "https://feeds.reuters.com/Reuters/worldNews"},
    ],
    "tech": [
        {"src": "數位時代",    "key": "bnext",       "url": "https://www.bnext.com.tw/rss"},
        {"src": "TechCrunch",  "key": "techcrunch",  "url": "https://techcrunch.com/feed/"},
        {"src": "The Verge",   "key": "verge",       "url": "https://www.theverge.com/rss/index.xml"},
        {"src": "VentureBeat", "key": "vb",          "url": "https://venturebeat.com/feed/"},
        {"src": "Wired",       "key": "wired",       "url": "https://www.wired.com/feed/rss"},
    ],
    "entertainment": [
        {"src": "Deadline",           "key": "deadline","url": "https://deadline.com/feed/"},
        {"src": "Variety",            "key": "variety", "url": "https://variety.com/feed/"},
        {"src": "Hollywood Reporter", "key": "thr",     "url": "https://www.hollywoodreporter.com/feed/"},
        {"src": "The Wrap",           "key": "thewrap", "url": "https://www.thewrap.com/feed/"},
    ],
}

MAX_PER_COL = 5

# ── 市場資料：yfinance ────────────────────────────────────────
def fmt_val(price, symbol):
    """格式化數字顯示"""
    if price is None:
        return "N/A"
    if symbol in ("GC=F", "CL=F") or price > 100:
        return f"{price:,.2f}"
    return f"{price:.4f}"

def fmt_chg(chg_pct):
    if chg_pct is None:
        return "0.00%"
    sign = "+" if chg_pct >= 0 else ""
    return f"{sign}{chg_pct:.2f}%"

def fetch_markets_yfinance():
    """用 yfinance 抓 Yahoo Finance 即時資料"""
    stocks = {}
    fx = {}

    print("  Fetching stocks from Yahoo Finance...")
    for key, symbol in STOCK_SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = info.last_price
            prev  = info.previous_close
            if price and prev:
                chg_pct = (price - prev) / prev * 100
            else:
                chg_pct = None
            stocks[key] = {
                "val": fmt_val(price, symbol),
                "chg": fmt_chg(chg_pct),
            }
            print(f"    ✓ {key} ({symbol}): {stocks[key]['val']} {stocks[key]['chg']}")
            time.sleep(0.3)
        except Exception as e:
            print(f"    ✗ {key} ({symbol}): {e}")
            stocks[key] = {"val": "N/A", "chg": "—"}

    print("  Fetching FX & commodities from Yahoo Finance...")
    for key, symbol in FX_SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = info.last_price
            prev  = info.previous_close
            if price and prev:
                chg = price - prev
                sign = "+" if chg >= 0 else ""
                chg_str = f"{sign}{chg:.4f}"
            else:
                chg_str = "—"
            fx[key] = {
                "rate": fmt_val(price, symbol),
                "chg":  chg_str,
            }
            print(f"    ✓ {key} ({symbol}): {fx[key]['rate']} {fx[key]['chg']}")
            time.sleep(0.3)
        except Exception as e:
            print(f"    ✗ {key} ({symbol}): {e}")
            fx[key] = {"rate": "N/A", "chg": "—"}

    return {"stocks": stocks, "fx": fx}

def claude_call(prompt, use_search=False, max_tokens=1500):
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if use_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    for attempt in range(2):
        try:
            r = requests.post(API_URL, headers=HEADERS, json=body, timeout=90)
            r.raise_for_status()
            data = r.json()
            return "".join(b["text"] for b in data["content"] if b["type"] == "text")
        except Exception as e:
            print(f"    API attempt {attempt+1} failed: {e}")
            if attempt == 0:
                time.sleep(5)
    return ""

def robust_parse(txt):
    if not txt:
        return None
    for pattern in [txt.strip(),
                    re.sub(r'```(?:json)?\s*', '', txt).strip()]:
        for finder in [
            lambda t: (t.find("{"), t.rfind("}")),
            lambda t: (t.find("["), t.rfind("]")),
        ]:
            s, e = finder(pattern)
            if s != -1 and e != -1:
                try:
                    return json.loads(pattern[s:e+1])
                except:
                    pass
    return None

# ── RSS ───────────────────────────────────────────────────────
def fetch_rss_col(col_name):
    items = []
    for source in RSS_SOURCES.get(col_name, []):
        if len(items) >= MAX_PER_COL:
            break
        try:
            feedparser.USER_AGENT = "Mozilla/5.0 (compatible; NewsDashboard/1.0)"
            d = feedparser.parse(source["url"])
            added = 0
            need = MAX_PER_COL - len(items)
            for entry in d.entries[:need+2]:
                if added >= min(3, need):
                    break
                title = entry.get("title", "").strip()
                if not title:
                    continue
                items.append({
                    "src":      source["src"],
                    "key":      source["key"],
                    "title":    title,
                    "title_zh": "",
                    "link":     entry.get("link", ""),
                    "date":     entry.get("published", ""),
                })
                added += 1
            if added > 0:
                print(f"    ✓ RSS {source['src']}: {added} items")
        except Exception as e:
            print(f"    ✗ RSS {source['src']}: {e}")
    return items

def search_news_col(col_name, existing_count):
    need = MAX_PER_COL - existing_count
    if need <= 0:
        return []
    prompts = {
        "markets":       f"Search AP, CNBC, BBC Business for {need} latest financial news today.",
        "world":         f"Search AP, BBC World, Reuters for {need} latest world news today.",
        "tech":          f"Search TechCrunch, The Verge, VentureBeat for {need} latest tech news today.",
        "entertainment": f"Search Deadline, Variety, Hollywood Reporter for {need} latest entertainment news today.",
    }
    txt = claude_call(
        prompts.get(col_name, f"Search for {need} latest news today.") +
        f"\nReturn ONLY raw JSON array, no markdown, {need} items:\n"
        '[{"src":"AP","key":"ap","title":"headline","title_zh":"繁中","link":"https://...","date":"2小時前"}]',
        use_search=True, max_tokens=1000
    )
    result = robust_parse(txt)
    return result[:need] if isinstance(result, list) else []

def translate_batch(items):
    to_tr = [(i, x) for i, x in enumerate(items) if not x.get("title_zh") and x.get("title")]
    if not to_tr:
        return items
    titles = "\n".join(f"{i+1}. {x['title']}" for i, x in to_tr)
    txt = claude_call(
        f"Translate to Traditional Chinese. Return ONLY raw JSON array of {len(to_tr)} strings, no markdown:\n{titles}",
        max_tokens=800
    )
    result = robust_parse(txt)
    if isinstance(result, list) and len(result) == len(to_tr):
        for (orig_i, _), zh in zip(to_tr, result):
            items[orig_i]["title_zh"] = zh
    return items

# ── Main ──────────────────────────────────────────────────────
def main():
    now_tw = datetime.now(TW_TZ)
    print(f"=== update_data.py {now_tw.strftime('%Y-%m-%d %H:%M')} TW ===\n")

    print("[1/3] Fetching market data via yfinance (Yahoo Finance)...")
    markets = fetch_markets_yfinance()
    print(f"  Result — Stocks: {len(markets['stocks'])} | FX: {len(markets['fx'])}")

    print("\n[2/3] Fetching news...")
    news = {}
    for col in ["markets", "world", "tech", "entertainment"]:
        print(f"  [{col}]")
        items = fetch_rss_col(col)
        if len(items) < MAX_PER_COL:
            extra = search_news_col(col, len(items))
            items.extend(extra)
        news[col] = items[:MAX_PER_COL]
        print(f"    Final: {len(news[col])} items")

    print("\n[3/3] Translating headlines...")
    all_items = []
    for col in ["markets", "world", "tech", "entertainment"]:
        all_items.extend(news[col])
    all_items = translate_batch(all_items)
    idx = 0
    for col in ["markets", "world", "tech", "entertainment"]:
        for i in range(len(news[col])):
            news[col][i] = all_items[idx]; idx += 1

    output = {
        "updated_at":     now_tw.strftime("%Y-%m-%d %H:%M"),
        "updated_at_iso": now_tw.isoformat(),
        "stocks":         markets["stocks"],
        "fx":             markets["fx"],
        "news":           news,
    }

    with open("dashboard-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done.")
    print(f"   Stocks: {len(output['stocks'])} | FX: {len(output['fx'])}")
    for col, items in output["news"].items():
        print(f"   news/{col}: {len(items)} items")

if __name__ == "__main__":
    main()
