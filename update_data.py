#!/usr/bin/env python3
"""
update_data.py
每天由 GitHub Actions 執行：
1. 抓 RSS 新聞
2. 呼叫 Claude API 取得股市、外匯資料
3. 用 Claude 翻譯新聞標題成繁體中文
4. 寫入 dashboard-data.json
"""

import os, json, time, requests, feedparser
from datetime import datetime, timezone, timedelta

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
API_URL = "https://api.anthropic.com/v1/messages"
HEADERS = {
    "Content-Type": "application/json",
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
}

TW_TZ = timezone(timedelta(hours=8))

# ── RSS 來源 ──────────────────────────────────────────────
RSS_FEEDS = [
    # 欄1：市場 & 商業
    {"col": "markets",  "src": "Reuters",    "key": "reuters",    "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"col": "markets",  "src": "CNN Business","key": "cnn",       "url": "https://rss.cnn.com/rss/money_latest.rss"},
    {"col": "markets",  "src": "BBC Business","key": "bbc",       "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    # 欄2：全球 & 總經
    {"col": "world",    "src": "Reuters",    "key": "reuters",    "url": "https://feeds.reuters.com/Reuters/worldNews"},
    {"col": "world",    "src": "BBC World",  "key": "bbc",        "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    # 欄3：科技 & 產業
    {"col": "tech",     "src": "TechCrunch", "key": "techcrunch", "url": "https://techcrunch.com/feed/"},
    {"col": "tech",     "src": "VentureBeat","key": "vb",         "url": "https://venturebeat.com/feed/"},
]

MAX_PER_COL = 5   # 每欄最多幾則

def fetch_rss():
    """抓取所有 RSS，回傳 {col: [items]}"""
    cols = {"markets": [], "world": [], "tech": []}
    for feed in RSS_FEEDS:
        col = feed["col"]
        if len(cols[col]) >= MAX_PER_COL:
            continue
        try:
            d = feedparser.parse(feed["url"])
            for entry in d.entries[:4]:
                if len(cols[col]) >= MAX_PER_COL:
                    break
                cols[col].append({
                    "src":   feed["src"],
                    "key":   feed["key"],
                    "title": entry.get("title", ""),
                    "link":  entry.get("link", ""),
                    "date":  entry.get("published", ""),
                })
            print(f"  ✓ {feed['src']} ({col}): {len(d.entries)} entries")
        except Exception as e:
            print(f"  ✗ {feed['src']}: {e}")
    return cols

def claude(prompt, use_search=False, max_tokens=1500):
    """呼叫 Claude API，回傳文字"""
    body = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if use_search:
        body["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    r = requests.post(API_URL, headers=HEADERS, json=body, timeout=60)
    r.raise_for_status()
    data = r.json()
    return "".join(b["text"] for b in data["content"] if b["type"] == "text")

def parse_json(txt):
    """從 Claude 回傳文字中安全解析 JSON"""
    txt = txt.replace("```json", "").replace("```", "").strip()
    s, e = txt.find("{"), txt.rfind("}")
    if s != -1 and e != -1:
        return json.loads(txt[s:e+1])
    return json.loads(txt)

def fetch_markets():
    """用 Claude + web search 取得股市與外匯資料"""
    print("Fetching market data...")
    txt = claude(
        """Search for today's latest stock market index values and foreign exchange rates.
Return ONLY valid JSON, no markdown:
{
  "stocks": {
    "sp500":  {"val":"5,500","chg":"+0.5%"},
    "nasdaq": {"val":"17,200","chg":"+0.8%"},
    "dow":    {"val":"43,000","chg":"+0.3%"},
    "twii":   {"val":"22,500","chg":"-0.2%"},
    "nikkei": {"val":"38,000","chg":"+1.1%"},
    "hsi":    {"val":"17,000","chg":"-0.5%"},
    "kospi":  {"val":"2,500","chg":"+0.4%"},
    "dax":    {"val":"18,000","chg":"+0.6%"},
    "ftse":   {"val":"8,200","chg":"+0.2%"}
  },
  "fx": {
    "usdtwd": {"rate":"32.50","chg":"+0.12"},
    "eurusd": {"rate":"1.0850","chg":"-0.0020"},
    "usdjpy": {"rate":"149.50","chg":"+0.30"},
    "gbpusd": {"rate":"1.2650","chg":"+0.0030"},
    "usdcny": {"rate":"7.2400","chg":"-0.0050"},
    "audusd": {"rate":"0.6550","chg":"+0.0010"},
    "xauusd": {"rate":"3,050","chg":"+5.20"},
    "wti":    {"rate":"71.50","chg":"-0.80"}
  }
}
Use actual current data. Values as formatted strings with commas.""",
        use_search=True,
    )
    return parse_json(txt)

def translate_titles(items):
    """批次翻譯新聞標題為繁體中文，失敗則回傳原標題"""
    if not items:
        return []
    titles = "\n".join(f"{i+1}. {n['title']}" for i, n in enumerate(items))
    try:
        txt = claude(
            f"""Translate these news headlines to Traditional Chinese (繁體中文).
Keep proper nouns (company names, people, countries) in their common Chinese form.
Return ONLY a JSON array of translated strings, same order, no markdown:
{titles}""",
            max_tokens=800,
        )
        txt = txt.replace("```json", "").replace("```", "").strip()
        s, e = txt.find("["), txt.rfind("]")
        arr = json.loads(txt[s:e+1]) if s != -1 else []
        if len(arr) == len(items):
            return arr
    except Exception as ex:
        print(f"  ✗ Translation failed: {ex}")
    return [n["title"] for n in items]   # fallback: 原英文標題

# ── Main ─────────────────────────────────────────────────
def main():
    now_tw = datetime.now(TW_TZ)
    print(f"=== update_data.py started at {now_tw.strftime('%Y-%m-%d %H:%M')} TW ===")

    # 1. 抓 RSS
    print("\n[1/3] Fetching RSS feeds...")
    news_cols = fetch_rss()

    # 2. 抓市場資料
    print("\n[2/3] Fetching market data via Claude API...")
    try:
        markets = fetch_markets()
    except Exception as e:
        print(f"  ✗ Market fetch failed: {e}")
        markets = {"stocks": {}, "fx": {}}

    # 3. 翻譯新聞標題
    print("\n[3/3] Translating news titles...")
    all_items = news_cols["markets"] + news_cols["world"] + news_cols["tech"]
    translated = translate_titles(all_items)

    # 把翻譯塞回
    i = 0
    for col_key in ["markets", "world", "tech"]:
        for item in news_cols[col_key]:
            item["title_zh"] = translated[i] if i < len(translated) else item["title"]
            i += 1

    # 4. 組合最終 JSON
    output = {
        "updated_at": now_tw.strftime("%Y-%m-%d %H:%M"),
        "updated_at_iso": now_tw.isoformat(),
        "stocks": markets.get("stocks", {}),
        "fx":     markets.get("fx", {}),
        "news":   news_cols,
    }

    with open("dashboard-data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ dashboard-data.json written successfully.")
    print(f"   Stocks: {len(output['stocks'])} indices")
    print(f"   FX:     {len(output['fx'])} pairs")
    for col, items in output["news"].items():
        print(f"   News/{col}: {len(items)} items")

if __name__ == "__main__":
    main()
