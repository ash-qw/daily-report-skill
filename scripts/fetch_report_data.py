#!/usr/bin/env python3
"""
fetch_report_data.py
从 Notion「工作进度」页面读取指定日期的日报原始数据，输出标准化 JSON。

输出格式:
  {
    "date": "YYYY-MM-DD",
    "page_id": "<notion-page-id>",
    "sections": {
      "本周目标": [...],
      "近期待办": [...],
      "AI 应用": [...]
    }
  }

section item 结构:
  {"text": "父级文本", "children": [{"kind": "todo|bullet", "text": "...", "checked": bool}]}
"""
import json
import sys
import ssl
import urllib.request
from datetime import datetime

NOTION_KEY_PATH = "/home/node/.openclaw/workspace/api-keys/notion_api_key"
WORKSPACE_PAGE = "328a66c2-a53f-80d8-9611-f7c6ede3e9c7"
NOTION_VERSION = "2025-09-03"


def notion_req(method, endpoint, body=None, retries=3):
    """向 Notion API 发起请求，自动携带认证头和重试逻辑。"""
    import os
    proxy = os.environ.get('https_proxy') or os.environ.get('http_proxy')
    ctx = ssl.create_default_context()
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({'https': proxy, 'http': proxy})
        opener = urllib.request.build_opener(proxy_handler)
    else:
        opener = urllib.request.build_opener()
    with open(NOTION_KEY_PATH) as f:
        key = f.read().strip()
    url = "https://api.notion.com/v1" + endpoint
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Notion-Version", NOTION_VERSION)
    if body:
        req.add_header("Content-Type", "application/json")

    last_err = None
    for attempt in range(retries):
        try:
            with opener.open(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                import time
                time.sleep(1 * (attempt + 1))   # 1, 2, 3 秒退避
    raise last_err


def notion_search(query):
    """在 workspace 中搜索页面，返回匹配结果列表。"""
    result = notion_req("POST", "/search", {"query": query})
    return result.get("results", [])


def notion_blocks(page_id):
    """获取页面的一级子 blocks。"""
    result = notion_req("GET", "/blocks/" + page_id + "/children")
    return result.get("results", [])


def find_date_page(date_str):
    """根据日期字符串（如 "2026-04-27"）在 Notion 中查找对应页面，返回 page_id 或 None。"""
    results = notion_search(date_str)
    for p in results:
        props = p.get("properties", {})
        title_arr = props.get("title", {}).get("title", [])
        if title_arr:
            title = title_arr[0]["plain_text"].strip()
            # 页面标题可能是 "2026-04-27" 或 " 2026-04-27"（带前导空格）
            if title == date_str or title == (" " + date_str):
                return p["id"]
    return None


def parse_blocks(page_id):
    """
    解析页面 blocks，按 section 分组返回标准化结构。
    
    解析逻辑:
    - heading_1 → 切换当前 section
    - bulleted_list_item → 收集为当前 section 的条目，递归解析 to_do/bulleted_list_item 子项
    - to_do（无父级）→ 直接收入当前 section
    """
    SECTION_KEYS = {"本周目标", "近期待办", "AI 应用"}
    sections = {"本周目标": [], "近期待办": [], "AI 应用": []}
    current = None
    current_bullets = []

    def flush():
        if current:
            sections[current].extend(current_bullets)

    def get_todo_text(td):
        return "".join(x["plain_text"] for x in td.get("rich_text", []))

    blocks = notion_blocks(page_id)
    for b in blocks:
        t = b["type"]
        if t == "heading_1":
            flush()
            text = b["heading_1"]["rich_text"][0]["plain_text"]
            current = text if text in SECTION_KEYS else None
            current_bullets = []
        elif t == "bulleted_list_item":
            rich = b["bulleted_list_item"]["rich_text"]
            text = "".join(x["plain_text"] for x in rich)
            children = []
            if b.get("has_children"):
                for sb in notion_blocks(b["id"]):
                    if sb["type"] == "to_do":
                        td = sb["to_do"]
                        children.append({
                            "kind": "todo",
                            "text": get_todo_text(td),
                            "checked": td.get("checked", False)
                        })
                    elif sb["type"] == "bulleted_list_item":
                        srich = sb["bulleted_list_item"]["rich_text"]
                        children.append({
                            "kind": "bullet",
                            "text": "".join(x["plain_text"] for x in srich)
                        })
            current_bullets.append({"text": text, "children": children})
        elif t == "to_do":
            if current:
                td = b["to_do"]
                current_bullets.append({
                    "text": get_todo_text(td),
                    "checked": td.get("checked", False)
                })

    flush()
    return sections


def fetch_for_date(date_str):
    """Fetch and return report data for a given date. Used by daily_report.py."""
    page_id = find_date_page(date_str)
    if not page_id:
        return None
    sections = parse_blocks(page_id)
    return {
        "date": date_str,
        "page_id": page_id,
        "sections": sections
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch report raw data from Notion")
    parser.add_argument("date", help="YYYY-MM-DD")
    args = parser.parse_args()
    date_str = args.date.strip()

    result = fetch_for_date(date_str)
    if not result:
        print(json.dumps({"error": f"No page found for {date_str}"}))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
