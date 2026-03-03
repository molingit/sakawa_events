"""
佐川町イベント統合スクレイパー
-------------------------------
実行: python main.py

将来施設を追加する場合:
  1. scrape_XXX() 関数を追加
  2. SCRAPERS リストに登録するだけ
"""

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar
import json
import os
import re
from datetime import datetime

JSON_FILE = "sakawa_events.json"

# 外部から読み込む追加JSONファイル
EXTRA_JSON_FILES = [
    "manual_events.json",
    "ochi_events.json",
]


# ============================================================
# ユーティリティ
# ============================================================

def to_halfwidth_digits(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def parse_japanese_date(date_text: str):
    date_text = to_halfwidth_digits(date_text)
    m = re.search(r'([0-9]{4})年([0-9]{1,2})月([0-9]{1,2})日', date_text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r'令和([0-9]{1,2})年([0-9]{1,2})月([0-9]{1,2})日', date_text)
    if m:
        year = 2018 + int(m.group(1))
        return year, int(m.group(2)), int(m.group(3))
    m = re.search(r'([0-9]{1,2})月([0-9]{1,2})日', date_text)
    if m:
        return None, int(m.group(1)), int(m.group(2))
    return None, None, None


def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"  読み込み: {path} ({len(data)} 件)")
        return data
    return []


def event_key(e):
    """重複チェック用キー: URLとタイトルの組み合わせ"""
    return (e.get("url", ""), e.get("title", ""))


# ============================================================
# スクレイパー 1: さかわ観光協会
# ============================================================

def scrape_kankou():
    BASE_URL = "https://sakawa-kankou.jp/event"
    new_events = []

    res = requests.get(BASE_URL, timeout=15)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href.startswith("https://sakawa-kankou.jp/event/"):
            continue
        url = href.strip()

        title_div = a_tag.find("div", class_="title")
        title = title_div.get_text(strip=True) if title_div else ""
        if not title:
            continue

        year = month = day = None
        content = ""
        try:
            page_res = requests.get(url, timeout=10)
            page_res.raise_for_status()
            page_soup = BeautifulSoup(page_res.text, "html.parser")
            desc_div = page_soup.find("div", class_="description")
            content = desc_div.get_text("\n", strip=True) if desc_div else ""
            info_dl = page_soup.find("dl", class_="information")
            if info_dl:
                for dt, dd in zip(info_dl.find_all("dt"), info_dl.find_all("dd")):
                    if "開催時期" in dt.get_text(strip=True):
                        year, month, day = parse_japanese_date(dd.get_text(strip=True))
        except Exception as e:
            print(f"    ⚠ 詳細取得失敗: {url} {e}")

        new_events.append({
            "title": title,
            "url": url,
            "site": BASE_URL,
            "year": year,
            "month": month,
            "day": day,
            "content": content,
            "source": "さかわ観光協会",
        })

    return new_events


# ============================================================
# スクレイパー 2: 図書館さくと
# ============================================================

def scrape_library():
    BASE_URL = "https://sakawa-lib.jp/category/event/"
    date_pattern = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
    new_events = []

    res = requests.get(BASE_URL, timeout=15)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    for div in soup.find_all("div", class_="col-12 col-lg-4 mb-3"):
        link = div.find("a")
        if not link:
            continue
        url = link["href"].strip()

        title_div = div.find("div", class_="mb-2")
        title = title_div.get_text(strip=True) if title_div else ""

        year = month = day = None
        date_div = div.find("div", class_="event-date")
        if date_div:
            m = date_pattern.search(date_div.get_text())
            if m:
                year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))

        new_events.append({
            "title": title,
            "url": url,
            "site": BASE_URL,
            "year": year,
            "month": month,
            "day": day,
            "source": "図書館さくと",
        })

    return new_events


# ============================================================
# スクレイパー 3: おもちゃ美術館 (iCal / Google Calendar)
# ============================================================

def scrape_toymuseum():
    SITE_NAME = "sakawa-toymuseum.info"
    EXCLUDE_KEYWORDS = ["団体", "休館日", "事前受付"]

    CALENDAR_IDS = [
        "hpsakawatoymuseum@gmail.com",
        "8db2f0071658f4777a393c6ed76a528e3cabec539bbb48e1c2b34567b316d1b9@group.calendar.google.com",
        "c233444ff2dac8f9873360094fdcf9b125d765e57a5c3c95b228323faa5e7765@group.calendar.google.com",
    ]

    def make_ical_url(calendar_id):
        return f"https://calendar.google.com/calendar/ical/{calendar_id.replace('@', '%40')}/public/basic.ics"

    new_events = []

    for calendar_id in CALENDAR_IDS:
        url = make_ical_url(calendar_id)
        try:
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            cal = Calendar.from_ical(res.content)
        except Exception as e:
            print(f"    ⚠ カレンダー取得失敗: {calendar_id} {e}")
            continue

        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            dtstart = component.get("DTSTART")
            if not dtstart or not hasattr(dtstart.dt, "year"):
                continue

            dt = dtstart.dt
            title = str(component.get("SUMMARY", "（タイトルなし）"))
            content = str(component.get("DESCRIPTION", ""))
            location = str(component.get("LOCATION", ""))
            if location:
                content = f"場所: {location}\n{content}"

            # 除外チェック
            if any(kw in title + content for kw in EXCLUDE_KEYWORDS):
                continue

            new_events.append({
                "title": title,
                "content": content.strip(),
                "site": SITE_NAME,
                "url": "https://sakawa-toymuseum.info",
                "year": dt.year,
                "month": dt.month,
                "day": dt.day,
                "source": "おもちゃ美術館",
            })

    return new_events


# ============================================================
# スクレイパー 4: 青山文庫（静山文庫）
# ============================================================

def scrape_seizanbunko():
    URL = "https://seizanbunko.com/exhibition/"

    def parse_date_range(text):
        try:
            if "～" not in text:
                return None, None, None
            start = text.split("～", 1)[0].strip()
            if "年" in start:
                dt = datetime.strptime(start[:11], "%Y年%m月%d日")
                return dt.year, dt.month, dt.day
        except Exception:
            pass
        return None, None, None

    new_events = []
    resp = requests.get(URL, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    for block in soup.select("div.description_container"):
        title_tag = block.select_one("h2.entry_title.origin_f_size22")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)

        texts = [t.strip() for t in block.stripped_strings]
        year = month = day = None
        for t in texts:
            if "年" in t and "月" in t and "日" in t and "～" in t:
                year, month, day = parse_date_range(t)
                break

        content = "\n".join(texts)
        content = re.sub(r'\b\d{4}:\d{2}:\d{2}:\d{2}:\d{2}:\d{2}\b', '', content)

        new_events.append({
            "title": title,
            "url": URL,
            "site": URL,
            "year": year,
            "month": month,
            "day": day,
            "content": content,
            "source": "青山文庫",
        })

    return new_events


# ============================================================
# スクレイパー 5: 佐川町道の駅（牧野産直市）
# ============================================================

def scrape_michinoeki():
    BASE_URL = "https://makinosan.jp/event/"
    new_events = []

    res = requests.get(BASE_URL, timeout=15)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    for article in soup.find_all("article"):
        time_tag = article.find("time", datetime=True)
        if not time_tag:
            continue
        try:
            dt = datetime.strptime(time_tag["datetime"], "%Y-%m-%d")
            year, month, day = dt.year, dt.month, dt.day
        except Exception:
            year = month = day = None

        a_tag = article.find("a", href=True)
        if not a_tag:
            continue
        url = a_tag["href"].strip()
        title = a_tag.get_text(strip=True)

        if "出店" in title:
            continue

        new_events.append({
            "title": title,
            "url": url,
            "site": BASE_URL,
            "year": year,
            "month": month,
            "day": day,
            "source": "佐川町道の駅",
        })

    return new_events


# ============================================================
# 将来の施設はここに関数を追加して SCRAPERS に登録する
# 例:
#   def scrape_新施設名():
#       ...
#       return new_events  # 必ず list[dict] を返す
# ============================================================

SCRAPERS = [
    ("さかわ観光協会",   scrape_kankou),
    ("図書館さくと",     scrape_library),
    ("おもちゃ美術館",   scrape_toymuseum),
    ("青山文庫",         scrape_seizanbunko),
    ("佐川町道の駅",     scrape_michinoeki),
    # ("新しい施設名",   scrape_新施設名),  ← ここに追加するだけ
]


# ============================================================
# メイン処理
# ============================================================

def main():
    # --- 外部JSONファイルを読み込む ---
    all_events = []
    for path in EXTRA_JSON_FILES:
        all_events.extend(load_json(path))

    # --- 既存の sakawa_events.json を読み込む ---
    existing = load_json(JSON_FILE)
    all_events.extend(existing)

    # 既存キーセットを構築
    existing_keys = {event_key(e) for e in all_events}

    total_added = 0

    # --- 各スクレイパーを順番に実行 ---
    for name, scraper_func in SCRAPERS:
        print(f"\n[{name}] スクレイピング開始...")
        try:
            new_events = scraper_func()
        except Exception as e:
            print(f"  ⚠ {name} 全体エラー: {e}")
            continue

        added = 0
        for ev in new_events:
            k = event_key(ev)
            if k not in existing_keys:
                all_events.append(ev)
                existing_keys.add(k)
                added += 1

        print(f"  → {added} 件追加（取得総数: {len(new_events)} 件）")
        total_added += added

    # --- JSON保存 ---
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=2)

    print(f"\n=== 完了 ===")
    print(f"新規追加合計: {total_added} 件")
    print(f"総イベント数: {len(all_events)} 件")
    print(f"保存先: {JSON_FILE}")


if __name__ == "__main__":
    main()
