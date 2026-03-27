#!/usr/bin/env python3
"""
update_data.py — GitHub Actions 每日執行
股市/外匯：yfinance 直接從 Yahoo Finance 抓（精確、穩定）
新聞：RSS 優先，不足則 Claude API 補足
"""

import os, json, re, requests, feedparser, time
from datetime import datetime, timezone, timedelta
import yfinance as yf

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
API_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
}
TW_TZ = timezone(timedelta(hours=8))

# ── Yahoo Finance 代碼對照表 ──────────────────────────────────
STOCK_TICKERS = {
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

FX_TICKERS = {
    "usdtwd": "TWD=X",
    "eurusd": "EURUSD=X",
    "usdjpy": "JPY=X",
    "gbpusd": "GBPUSD=X",
    "usdcny": "CNY=X",
    "audusd": "AUDUSD=X",
    "xauusd": "GC=F",
    "wti":    "CL=F",
}

# ── RSS 新聞來源 ──────────────────────────────────────────────
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
    ],
    "tech": [
        {"src": "數位時代",    "key": "bnext",       "url": "https://www.bnext.com.tw/rss"},
        {"src": "TechCrunch",  "key": "techcrunch",  "url": "https://techcrunch.com/feed/"},
        {"src": "The Verge",   "key": "verge",       "url": "https://www.theverge.com/rss/index.xml"},
        {"src": "VentureBeat", "key": "vb",          "url": "https://venturebeat.com/feed/"},
    ],
    "entertainment": [
        {"src": "Deadline",           "key": "deadline","url": "https://deadline.com/feed/"},
        {"src": "Variety",            "key": "variety", "url": "https://variety.com/feed/"},
        {"src": "Hollywood Reporter", "key": "thr",     "url": "https://www.hollywoodreporter.com/feed/"},
        {"src": "The Wrap",           "key": "thewrap", "url": "https://www.thewrap.com/feed/"},
    ],
}

MAX_PER_COL = 5

# ── yfinance 抓市場資料 ───────────────────────────────────────
def fmt_price(price, key):
    if price is None:
        return "N/A"
    if key in ("xauusd", "sp500", "nasdaq", "dow", "twii", "nikkei", "hsi", "kospi", "dax", "ftse"):
        return f"{price:,.2f}"
    if price > 10:
        return f"{price:.2f}"
    return f"{price:.4f}"

def fmt_chg_pct(price, prev):
    if not price or not prev:
        return "0.00%"
    pct = (price - prev) / prev * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"

def fmt_chg_abs(price, prev):
    if not price or not prev:
        return "0.00"
    diff = price - prev
    sign = "+" if diff >= 0 else ""
    if abs(diff) < 1:
        return f"{sign}{diff:.4f}"
    return f"{sign}{diff:.2f}"

def fetch_markets():
    stocks = {}
    fx = {}

    print("  [Stocks] Fetching from Yahoo Finance...")
    all_stock_syms = list(STOCK_TICKERS.values())
    try:
        tickers = yf.Tickers(" ".join(all_stock_syms))
        for key, sym in STOCK_TICKERS.items():
            try:
                info = tickers.tickers[sym].fast_info
                price = info.last_price
                prev  = info.previous_close
                stocks[key] = {
                    "val": fmt_price(price, key),
                    "chg": fmt_chg_pct(price, prev),
                }
                print(f"    ✓ {key}: {stocks[key]['val']} {stocks[key]['chg']}")
            except Exception as e:
                print(f"    ✗ {key}: {e}")
                stocks[key] = {"val": "N/A", "chg": "—"}
            time.sleep(0.2)
    except Exception as e:
        print(f"    Batch fetch failed: {e}, trying individually...")
        for key, sym in STOCK_TICKERS.items():
            try:
                info = yf.Ticker(sym).fast_info
                price = info.last_price
                prev  = info.previous_close
                stocks[key] = {
                    "val": fmt_price(price, key),
                    "chg": fmt_chg_pct(price, prev),
                }
                print(f"    ✓ {key}: {stocks[key]['val']} {stocks[key]['chg']}")
            except Exception as e2:
                print(f"    ✗ {key}: {e2}")
                stocks[key] = {"val": "N/A", "chg": "—"}
            time.sleep(0.5)

    print("  [FX] Fetching from Yahoo Finance...")
    for key, sym in FX_TICKERS.items():
        try:
            info = yf.Ticker(sym).fast_info
            price = info.last_price
            prev  = info.previous_close
            fx[key] = {
                "rate": fmt_price(price, key),
                "chg":  fmt_chg_abs(price, prev),
            }
            print(f"    ✓ {key}: {fx[key]['rate']} {fx[key]['chg']}")
        except Exception as e:
            print(f"    ✗ {key}: {e}")
            fx[key] = {"rate": "N/A", "chg": "—"}
        time.sleep(0.3)

    return {"stocks": stocks, "fx": fx}

# ── Claude API 呼叫 ──────────────────────────────────────────
def claude_call(prompt, use_search=False, max_tokens=1200):
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
            return "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")
        except Exception as e:
            print(f"    API attempt {attempt+1} failed: {e}")
            if attempt == 0:
                time.sleep(5)
    return ""

def parse_arr(txt):
    if not txt:
        return []
    txt = re.sub(r'```(?:json)?\s*', '', txt).strip()
    s, e = txt.find("["), txt.rfind("]")
    if s != -1 and e != -1:
        try:
            return json.loads(txt[s:e+1])
        except:
            pass
    return []

# ── RSS 抓取 ─────────────────────────────────────────────────
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

def search_news(col_name, need):
    if need <= 0:
        return []
    prompts = {
        "markets":       f"Search AP, CNBC, BBC Business for {need} latest financial news stories published today.",
        "world":         f"Search AP, BBC World, Reuters for {need} latest world news stories published today.",
        "tech":          f"Search TechCrunch, The Verge, VentureBeat for {need} latest technology news stories published today.",
        "entertainment": f"Search Deadline, Variety, Hollywood Reporter for {need} latest entertainment industry news published today.",
    }
    txt = claude_call(
        prompts.get(col_name, f"Search for {need} latest news stories today.") +
        f"\nReturn ONLY a raw JSON array (no markdown) of {need} items:\n"
        '[{"src":"AP","key":"ap","title":"English headline","title_zh":"繁體中文翻譯","link":"https://...","date":"2小時前"}]\n'
        "key options: ap, bbc, cnbc, reuters, bloomberg, techcrunch, vb, verge, wired, deadline, variety, thr, thewrap, bnext, ctee, udn_econ, other",
        use_search=True
    )
    return parse_arr(txt)[:need]

def translate_batch(items):
    to_tr = [(i, x) for i, x in enumerate(items) if not x.get("title_zh") and x.get("title")]
    if not to_tr:
        return items
    titles = "\n".join(f"{i+1}. {x['title']}" for i, x in to_tr)
    txt = claude_call(
        f"Translate to Traditional Chinese (繁體中文), keep proper nouns in Chinese form.\n"
        f"Return ONLY a raw JSON array of {len(to_tr)} strings (no markdown):\n{titles}",
        max_tokens=800
    )
    result = parse_arr(txt)
    if len(result) == len(to_tr):
        for (orig_i, _), zh in zip(to_tr, result):
            items[orig_i]["title_zh"] = zh
    return items

# ── Main ─────────────────────────────────────────────────────
def main():
    now_tw = datetime.now(TW_TZ)
    print(f"=== update_data.py {now_tw.strftime('%Y-%m-%d %H:%M')} TW ===\n")

    print("[1/3] Fetching market data via yfinance (Yahoo Finance)...")
    markets = fetch_markets()
    s_ok = sum(1 for v in markets["stocks"].values() if v["val"] != "N/A")
    f_ok = sum(1 for v in markets["fx"].values() if v["rate"] != "N/A")
    print(f"  Result: {s_ok}/{len(markets['stocks'])} stocks, {f_ok}/{len(markets['fx'])} fx OK")

    print("\n[2/3] Fetching news (RSS + Claude supplement)...")
    news = {}
    for col in ["markets", "world", "tech", "entertainment"]:
        print(f"  [{col}]")
        items = fetch_rss_col(col)
        if len(items) < MAX_PER_COL:
            extra = search_news(col, MAX_PER_COL - len(items))
            items.extend(extra)
        news[col] = items[:MAX_PER_COL]
        print(f"    Final: {len(news[col])} items")

    print("\n[3/3] Translating RSS headlines...")
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
    print(f"   Stocks: {s_ok} OK | FX: {f_ok} OK")
    for col, items in output["news"].items():
        srcs = list(set(i["src"] for i in items))
        print(f"   news/{col}: {len(items)} items — {srcs}")

if __name__ == "__main__":
    main()
