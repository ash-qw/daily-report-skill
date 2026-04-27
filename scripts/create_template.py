#!/usr/bin/env python3
"""
create_template.py
根据指定日期的日报内容，在 Notion 中创建新一天（明日）的日报模板页面。

用法:
  python3 create_template.py [YYYY-MM-DD]
  # 不指定日期时默认取昨天

模板创建规则（process_blocks 核心逻辑）:
  - 本周目标: 直接复制全部内容（含嵌套子项）
  - 近期待办: 仅保留含未完成 todo 的子项；所有已完成 todo 不复制
  - 待办清单: 直接复制（昨日有什么就复制什么）
  - AI 应用: 仅保留标题，内容清空
  - 其他一级标题: 完全复制

Notion API Key 读取顺序:
  1. 环境变量 NOTION_KEY
  2. ~/.openclaw/conf/daily-report/config.env
  3. ~/.openclaw/workspace/api-keys/notion_api_key
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

# 配置从环境变量读取
NOTION_KEY = os.environ.get("NOTION_KEY", "")
PARENT_PAGE_ID = os.environ.get("PARENT_PAGE_ID", "328a66c2-a53f-80d8-9611-f7c6ede3e9c7")


def curl_get(url: str) -> dict:
    """向 Notion API 发起 GET 请求（通过 curl 子进程）。"""
    cmd = [
        "curl", "-s", "-X", "GET", url,
        "-H", f"Authorization: Bearer {NOTION_KEY}",
        "-H", "Notion-Version: 2022-06-28"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def curl_post(url: str, data: dict) -> dict:
    """向 Notion API 发起 POST 请求（创建资源）。"""
    cmd = [
        "curl", "-s", "-X", "POST", url,
        "-H", f"Authorization: Bearer {NOTION_KEY}",
        "-H", "Content-Type: application/json",
        "-H", "Notion-Version: 2022-06-28",
        "-d", json.dumps(data)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def curl_patch(url: str, data: dict) -> dict:
    """向 Notion API 发起 PATCH 请求（更新资源）。"""
    cmd = [
        "curl", "-s", "-X", "PATCH", url,
        "-H", f"Authorization: Bearer {NOTION_KEY}",
        "-H", "Content-Type: application/json",
        "-H", "Notion-Version: 2022-06-28",
        "-d", json.dumps(data)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def get_page_blocks(page_id: str) -> list:
    """获取页面的一级子 blocks（不递归）。"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    return curl_get(url).get("results", [])


def get_block_children(block_id: str) -> list:
    """获取 block 的子 blocks（递归入口，每次请求一层）。"""
    url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
    return curl_get(url).get("results", [])


def get_text_content(rich_text: list) -> str:
    """从 Notion rich_text 数组提取纯文本字符串。"""
    if not rich_text:
        return ""
    return "".join([t.get("text", {}).get("content", "") for t in rich_text])


def find_page_by_date(date: str) -> str:
    """在工作进度父页面下查找指定日期的子页面，返回 page_id 或 None。"""
    url = f"https://api.notion.com/v1/blocks/{PARENT_PAGE_ID}/children?page_size=100"
    blocks = curl_get(url).get("results", [])
    
    for block in blocks:
        if block.get("type") == "child_page":
            title = block.get("child_page", {}).get("title", "").strip()
            if title == date:
                return block["id"]
    return None


def create_page(date: str) -> str:
    """在 PARENT_PAGE_ID 下创建标题为 date 的新页面，返回 page_id。"""
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "properties": {"title": {"title": [{"text": {"content": date}}]}},
        "children": []
    }
    result = curl_post(url, data)
    return result.get("id", "")


def process_blocks(source_blocks: list) -> list:
    """
    遍历源页面 blocks，按 section 规则处理后返回新 blocks 列表。
    
    Section 规则（由 current_section 控制）:
      - 本周目标/近期待办/待办清单: 复制条目及其子项
      - AI 应用: 仅复制标题，清空内容
      - 其他 heading_1: 完全复制
    
    递归: 通过 get_block_children 获取并处理嵌套层级。
    """
    new_blocks = []
    current_section = None
    
    for block in source_blocks:
        btype = block.get("type")
        
        if btype == "heading_1":
            text = get_text_content(block.get("heading_1", {}).get("rich_text", []))
            current_section = text
            
            if text in ["本周目标", "近期待办", "待办清单"]:
                new_blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                })
            elif text == "AI 应用":
                # 仅保留标题
                new_blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                })
                current_section = "AI 应用"
        
        elif btype == "bulleted_list_item":
            text = get_text_content(block.get("bulleted_list_item", {}).get("rich_text", []))
            has_children = block.get("has_children", False)
            
            if current_section in ["本周目标", "近期待办", "待办清单"]:
                # 近期待办：检查是否有未完成的 todo
                if current_section == "近期待办" and has_children:
                    if not has_uncompleted_todos(block["id"]):
                        # 所有 todo 都已完成，跳过不复制
                        continue
                
                block_obj = {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                }
                
                # 递归处理子项
                if has_children:
                    children = get_block_children(block["id"])
                    child_blocks = process_children(children, current_section)
                    if child_blocks:
                        block_obj["bulleted_list_item"]["children"] = child_blocks
                
                new_blocks.append(block_obj)
        
        elif btype == "to_do":
            text = get_text_content(block.get("to_do", {}).get("rich_text", []))
            checked = block.get("to_do", {}).get("checked", False)
            
            if current_section == "近期待办" and not checked:
                new_blocks.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": False}
                })
    
    return new_blocks


def has_uncompleted_todos(block_id: str) -> bool:
    """递归检查 block 及其嵌套子块中是否存在未勾选的 to_do。"""
    children = get_block_children(block_id)
    for child in children:
        if child.get("type") == "to_do":
            if not child.get("to_do", {}).get("checked", False):
                return True
        if child.get("has_children", False):
            if has_uncompleted_todos(child["id"]):
                return True
    return False


def collect_todos(children: list) -> list:
    """递归收集所有层级的 to_do 项（text + checked 状态）。"""
    todos = []
    for child in children:
        if child.get("type") == "to_do":
            todos.append({
                "text": get_text_content(child.get("to_do", {}).get("rich_text", [])),
                "checked": child.get("to_do", {}).get("checked", False)
            })
        if child.get("has_children", False):
            grandchildren = get_block_children(child["id"])
            todos.extend(collect_todos(grandchildren))
    return todos


def process_children(children: list, section: str) -> list:
    """
    递归处理子 blocks，根据当前 section 应用不同规则:
      - 近期待办: 只保留未完成的 to_do
      - 待办清单/本周目标: 保留全部（checked 状态不变）
    支持 to_do / bulleted_list_item / numbered_list_item / paragraph / heading_2/3
    """
    result = []
    
    for child in children:
        ctype = child.get("type")
        
        if ctype == "to_do":
            text = get_text_content(child.get("to_do", {}).get("rich_text", []))
            checked = child.get("to_do", {}).get("checked", False)
            
            if section == "近期待办":
                # 近期待办：只保留未完成的
                if not checked:
                    result.append({
                        "object": "block",
                        "type": "to_do",
                        "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": False}
                    })
            elif section == "待办清单":
                # 待办清单：全部保留
                result.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": checked}
                })
            elif section == "本周目标":
                # 本周目标：全部保留
                result.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": checked}
                })
        
        elif ctype == "bulleted_list_item":
            text = get_text_content(child.get("bulleted_list_item", {}).get("rich_text", []))
            has_children = child.get("has_children", False)
            
            block_obj = {
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            }
            
            # 递归处理子项
            if has_children:
                grandchildren = get_block_children(child["id"])
                child_blocks = process_children(grandchildren, section)
                if child_blocks:
                    block_obj["bulleted_list_item"]["children"] = child_blocks
            
            result.append(block_obj)
        
        elif ctype == "numbered_list_item":
            text = get_text_content(child.get("numbered_list_item", {}).get("rich_text", []))
            has_children = child.get("has_children", False)
            
            block_obj = {
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            }
            
            if has_children:
                grandchildren = get_block_children(child["id"])
                child_blocks = process_children(grandchildren, section)
                if child_blocks:
                    block_obj["numbered_list_item"]["children"] = child_blocks
            
            result.append(block_obj)
        
        elif ctype == "paragraph":
            text = get_text_content(child.get("paragraph", {}).get("rich_text", []))
            if text:
                result.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                })
        
        elif ctype == "heading_2":
            text = get_text_content(child.get("heading_2", {}).get("rich_text", []))
            result.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
        
        elif ctype == "heading_3":
            text = get_text_content(child.get("heading_3", {}).get("rich_text", []))
            result.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
    
    return result


def add_blocks_to_page(page_id: str, blocks: list):
    """将处理后的 blocks 追加到目标页面。"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    curl_patch(url, {"children": blocks})


def main():
    global NOTION_KEY
    
    # 从环境变量或配置文件读取
    if not NOTION_KEY:
        config_path = os.path.expanduser("~/.openclaw/conf/daily-report/config.env")
        if os.path.exists(config_path):
            with open(config_path) as f:
                for line in f:
                    if line.strip().startswith("NOTION_KEY="):
                        NOTION_KEY = line.strip().split("=", 1)[1]
    
    if not NOTION_KEY:
        key_path = os.path.expanduser("~/.openclaw/workspace/api-keys/notion_api_key")
        if os.path.exists(key_path):
            with open(key_path) as f:
                NOTION_KEY = f.read().strip()
    
    if not NOTION_KEY:
        print("Error: NOTION_KEY not found")
        sys.exit(1)
    
    # 获取命令行参数（内容来源日期）
    if len(sys.argv) < 2:
        # 默认昨天
        source_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        source_date = sys.argv[1]
    
    # 页面标题始终为今天（当天日期）
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 查找源页面
    page_id = find_page_by_date(source_date)
    if not page_id:
        print(f"Error: Page for {source_date} not found")
        sys.exit(1)
    
    # 获取页面内容
    blocks = get_page_blocks(page_id)
    
    # 创建新页面（标题为今天）
    new_page_id = create_page(today)
    if not new_page_id:
        print("Error: Failed to create page")
        sys.exit(1)
    
    # 处理 blocks（包含递归子项）
    new_blocks = process_blocks(blocks)
    
    # 添加到页面
    add_blocks_to_page(new_page_id, new_blocks)
    
    # 输出结果
    print(f"https://www.notion.so/{new_page_id.replace('-', '')}")


if __name__ == "__main__":
    main()
