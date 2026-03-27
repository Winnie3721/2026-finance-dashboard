#!/usr/bin/env python3
"""
update_data.py — GitHub Actions 每日執行
股市/外匯：yfinance 從 Yahoo Finance 抓
新聞：Claude API web search（4 欄各自搜尋，穩定不依賴 RSS）
"""

import os, json, re, requests, time
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

# ── Yahoo Finance 代碼 ────────────────────────────────────────
STOCKS = {
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

FX = {
    "usdtwd": "TWD=X",
    "eurusd": "EURUSD=X",
    "usdjpy": "JPY=X",
    "gbpusd": "GBPUSD=X",
    "usdcny": "CNY=X",
    "audusd": "AUDUSD=X",
    "xauusd": "GC=F",
    "wti":    "CL=F",
}

def fmt(price, is_index=False):
    if price is None: return "N/A"
    if is_index or price > 500: return f"{price:,.2f}"
    if price > 10: return f"{price:.2f}"
    return f"{price:.4f}"

def pct(price, prev):
    if not price or not prev: return "0.00%"
    v = (price - prev) / prev * 100
    return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"

def diff(price, prev):
    if not price or not prev: return "0.00"
    v = price - prev
    return f"+{v:.4f}" if v >= 0 else f"{v:.4f}"

def fetch_markets():
    stocks, fx = {}, {}

    print("  [Stocks] yfinance...")
    for key, sym in STOCKS.items():
        for attempt in range(3):
            try:
                t = yf.Ticker(sym)
                info = t.fast_info
                p = info.last_price
                prev = info.previous_close
                stocks[key] = {"val": fmt(p, True), "chg": pct(p, prev)}
                print(f"    ✓ {key}: {stocks[key]['val']} {stocks[key]['chg']}")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    ✗ {key}: {e}")
                    stocks[key] = {"val": "N/A", "chg": "—"}
                time.sleep(1)
        time.sleep(0.3)

    print("  [FX] yfinance...")
    for key, sym in FX.items():
        for attempt in range(3):
            try:
                t = yf.Ticker(sym)
                info = t.fast_info
                p = info.last_price
                prev = info.previous_close
                fx[key] = {"rate": fmt(p), "chg": diff(p, prev)}
                print(f"    ✓ {key}: {fx[key]['rate']} {fx[key]['chg']}")
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    ✗ {key}: {e}")
                    fx[key] = {"rate": "N/A", "chg": "—"}
                time.sleep(1)
        time.sleep(0.3)

    return {"stocks": stocks, "fx": fx}

def claude(prompt, max_tokens=1200):
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        "messages": [{"role": "user", "content": prompt}],
    }
    for attempt in range(2):
        try:
            r = requests.post(API_URL, headers=HEADERS, json=body, timeout=90)
            r.raise_for_status()
            return "".join(b["text"] for b in r.json()["content"] if b["type"] == "text")
        except Exception as e:
            print(f"    Claude attempt {attempt+1} failed: {e}")
            if attempt == 0: time.sleep(5)
    return ""

def parse_arr(txt):
    if not txt: return []
    txt = re.sub(r'```(?:json)?\s*', '', txt).strip()
    s, e = txt.find("["), txt.rfind("]")
    if s != -1 and e != -1:
        try: return json.loads(txt[s:e+1])
        except: pass
    return []

def fetch_news(col, query):
    print(f"  [{col}] Searching...")
    txt = claude(
        f"{query}\n"
        "Find 5 real news stories published today or within the past 24 hours.\n"
        "Return ONLY a raw JSON array, no markdown:\n"
        '[{"src":"AP","key":"ap","title":"English headline",'
        '"title_zh":"繁體中文翻譯","link":"https://...","date":"2小時前"}]\n'
        "key options: ap, reuters, cnbc, bbc, bloomberg, wsj, techcrunch, "
        "vb, verge, wired, deadline, variety, thr, thewrap, bnext, ctee, udn_econ, other"
    )
    items = parse_arr(txt)
    print(f"    Got {len(items)} items")
    return items[:5]

def main():
    now_tw = datetime.now(TW_TZ)
    print(f"=== update_data.py {now_tw.strftime('%Y-%m-%d %H:%M')} TW ===\n")

    # 1. 市場資料（yfinance）
    print("[1/5] Market data via yfinance (Yahoo Finance)...")
    markets = fetch_markets()
    s_ok = sum(1 for v in markets["stocks"].values() if v["val"] != "N/A")
    f_ok = sum(1 for v in markets["fx"].values() if v["rate"] != "N/A")
    print(f"  → Stocks: {s_ok}/9 OK | FX: {f_ok}/8 OK\n")

    # 2~5. 新聞（Claude API web search，4欄各自搜尋）
    news_markets = fetch_news("markets",
        "Search AP, CNBC, BBC Business, Bloomberg, 經濟日報 for today's top "
        "financial and business news. Include both Taiwan and global finance news.")

    news_world = fetch_news("world",
        "Search AP, BBC World, Reuters, 聯合新聞網 for today's top international "
        "news and geopolitics. Include Asia-Pacific news.")

    news_tech = fetch_news("tech",
        "Search TechCrunch, The Verge, VentureBeat, 數位時代 for today's top "
        "technology and AI news.")

    news_ent = fetch_news("entertainment",
        "Search Deadline, Variety, Hollywood Reporter, The Wrap for today's top "
        "entertainment, film, TV and streaming industry news.")

    output = {
        "updated_at":     now_tw.strftime("%Y-%m-%d %H:%M"),
        "updated_at_iso": now_tw.isoformat(),
        "stocks":         markets["stocks"],
        "fx":             markets["fx"],
        "news": {
            "markets":       news_markets,
            "world":         news_world,
            "tech":          news_tech,
            "entertainment": news_ent,
        },
    }

    with open("dashboard-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Done.")
    print(f"   Stocks: {s_ok}/9 | FX: {f_ok}/8")
    for col, items in output["news"].items():
        srcs = list(set(i.get("src","?") for i in items))
        print(f"   news/{col}: {len(items)} items — {srcs}")

if __name__ == "__main__":
    main()
