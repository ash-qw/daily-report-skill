#!/usr/bin/env python3
"""
create_from_template.py
根据指定日期的日报内容，在 Notion 中创建新一天（明日）的日报模板页面。

用法:
  python3 create_from_template.py <YYYY-MM-DD>

模板创建规则:
  - 本周目标: 直接复制全部内容
  - 近期待办: 仅保留含未完成 todo 的子项，已完成的不复制
  - 待办清单: 直接复制（昨日有什么就复制什么）
  - AI 应用: 仅保留标题，内容清空
  - 其他一级标题: 完全复制

这是 create_template.py 的重写版本，模块化程度更高、函数职责更清晰。
Notion API Key 从 ~/.openclaw/workspace/api-keys/notion_api_key 读取。
"""

import argparse
import json
import os
import subprocess
from datetime import datetime

# 配置
NOTION_KEY = ""
PARENT_PAGE_ID = "328a66c2-a53f-80d8-9611-f7c6ede3e9c7"  # 工作进度页面


def curl_get(url: str) -> dict:
    """向 Notion API 发起 GET 请求。"""
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


def get_page_blocks(page_id: str) -> list:
    """获取页面的所有子 blocks（一级，不递归）。"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    return curl_get(url).get("results", [])


def get_block_children(block_id: str) -> list:
    """获取 block 的子 blocks。"""
    url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
    return curl_get(url).get("results", [])


def has_unchecked_todo(blocks: list) -> bool:
    """检查 blocks 列表中是否存在未勾选的 to_do 类型 block。"""
    for block in blocks:
        if block.get("type") == "to_do":
            if not block.get("to_do", {}).get("checked", False):
                return True
    return False


def get_text_content(rich_text: list) -> str:
    """从 Notion rich_text 数组提取纯文本字符串。"""
    if not rich_text:
        return ""
    return "".join([t.get("text", {}).get("content", "") for t in rich_text])


def convert_block_to_json(block: dict, include_children: bool = True) -> dict:
    """
    将 Notion block 对象转换为可用于 API 创建的精简 JSON 格式。
    
    支持类型: heading_1/2/3, bulleted_list_item, numbered_list_item, to_do, paragraph
    include_children=True 时会递归获取并转换子 blocks。
    """
    block_type = block.get("type")
    
    if block_type == "heading_1":
        text = get_text_content(block.get("heading_1", {}).get("rich_text", []))
        return {
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    elif block_type == "heading_2":
        text = get_text_content(block.get("heading_2", {}).get("rich_text", []))
        return {
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    elif block_type == "heading_3":
        text = get_text_content(block.get("heading_3", {}).get("rich_text", []))
        return {
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    elif block_type == "bulleted_list_item":
        text = get_text_content(block.get("bulleted_list_item", {}).get("rich_text", []))
        result = {
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
        if include_children and block.get("has_children"):
            children = get_block_children(block["id"])
            child_blocks = []
            for c in children:
                converted = convert_block_to_json(c, False)
                if converted:
                    child_blocks.append(converted)
            if child_blocks:
                result["bulleted_list_item"]["children"] = child_blocks
        return result
    
    elif block_type == "numbered_list_item":
        text = get_text_content(block.get("numbered_list_item", {}).get("rich_text", []))
        result = {
            "object": "block",
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
        if include_children and block.get("has_children"):
            children = get_block_children(block["id"])
            child_blocks = []
            for c in children:
                converted = convert_block_to_json(c, False)
                if converted:
                    child_blocks.append(converted)
            if child_blocks:
                result["numbered_list_item"]["children"] = child_blocks
        return result
    
    elif block_type == "to_do":
        text = get_text_content(block.get("to_do", {}).get("rich_text", []))
        checked = block.get("to_do", {}).get("checked", False)
        return {
            "object": "block",
            "type": "to_do",
            "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": checked}
        }
    
    elif block_type == "paragraph":
        text = get_text_content(block.get("paragraph", {}).get("rich_text", []))
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]}
        }
    
    return None


def create_page(date: str, blocks: list) -> str:
    """
    根据源 blocks 内容和日期创建新页面。
    
    date 参数为源日期（昨日），页面标题固定为今天（当前日期）。
    按 section 分组处理 blocks，应用各自的复制规则后创建 Notion 页面。
    """
    # 页面标题固定为今天（定时任务场景下即创建模板的当天）
    title = datetime.now().strftime("%Y-%m-%d")
    
    # 解析 blocks，按 section 分组
    # section 是从 heading_1 到下一个 heading_1 之间的内容
    sections = {}  # {section_name: [blocks]}
    current_section = None
    
    for block in blocks:
        block_type = block.get("type")
        
        if block_type == "heading_1":
            text = get_text_content(block.get("heading_1", {}).get("rich_text", []))
            current_section = text
            sections[current_section] = []
        elif current_section:
            sections[current_section].append(block)
    
    # 构建新页面内容
    children = []
    
    # 本周目标：直接复制
    if "本周目标" in sections:
        children.append({
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": "本周目标"}}]}
        })
        for block in sections["本周目标"]:
            converted = convert_block_to_json(block)
            if converted:
                children.append(converted)
    
    # 近期待办：保留含未完成 todo 的子项
    if "近期待办" in sections:
        children.append({
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": "近期待办"}}]}
        })
        for block in sections["近期待办"]:
            if block.get("type") == "bulleted_list_item" and block.get("has_children"):
                # 检查是否有未完成的 todo
                sub_children = get_block_children(block["id"])
                if sub_children and has_unchecked_todo(sub_children):
                    item_text = get_text_content(block.get("bulleted_list_item", {}).get("rich_text", []))
                    
                    # 构建子内容（只包含未完成的 todo）
                    todo_children = []
                    for sub in sub_children:
                        if sub.get("type") == "to_do" and not sub.get("to_do", {}).get("checked", False):
                            todo_text = get_text_content(sub.get("to_do", {}).get("rich_text", []))
                            todo_children.append({
                                "object": "block",
                                "type": "to_do",
                                "to_do": {"rich_text": [{"type": "text", "text": {"content": todo_text}}], "checked": False}
                            })
                    
                    if todo_children:
                        children.append({
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": [{"type": "text", "text": {"content": item_text}}],
                                "children": todo_children
                            }
                        })
    
    # 待办清单：直接复制
    if "待办清单" in sections:
        children.append({
            "object": "block",
            "type": "heading_1",
            "heading_1": {"rich_text": [{"type": "text", "text": {"content": "待办清单"}}]}
        })
        for block in sections["待办清单"]:
            converted = convert_block_to_json(block)
            if converted:
                children.append(converted)
    
    # AI 应用：仅保留标题
    children.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": "AI 应用"}}]}
    })
    
    # 其他一级标题：完全复制
    for section_name, section_blocks in sections.items():
        if section_name not in ["本周目标", "近期待办", "待办清单", "AI 应用"]:
            children.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": section_name}}]}
            })
            for block in section_blocks:
                converted = convert_block_to_json(block)
                if converted:
                    children.append(converted)
    
    # 创建页面
    url = "https://api.notion.com/v1/pages"
    data = {
        "parent": {"page_id": PARENT_PAGE_ID},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        },
        "children": children
    }
    
    result = curl_post(url, data)
    return result.get("url", "")


def find_page_by_date(date: str) -> str:
    """在工作进度父页面下查找指定日期的子页面，返回 page_id 或 None。"""
    # 查询工作进度页面下的所有子页面
    url = f"https://api.notion.com/v1/blocks/{PARENT_PAGE_ID}/children?page_size=100"
    blocks = curl_get(url).get("results", [])
    
    for block in blocks:
        if block.get("type") == "child_page":
            title = block.get("child_page", {}).get("title", "").strip()
            if title == date:
                return block["id"]
    
    return None


def main():
    parser = argparse.ArgumentParser(description="根据指定日期创建新日报模板")
    parser.add_argument("date", help="源日期 (YYYY-MM-DD)")
    args = parser.parse_args()
    
    # 加载 API Key
    api_key_path = os.path.expanduser("~/.openclaw/workspace/api-keys/notion_api_key")
    if os.path.exists(api_key_path):
        with open(api_key_path) as f:
            global NOTION_KEY
            NOTION_KEY = f.read().strip()
    
    if not NOTION_KEY:
        print("Error: NOTION_API_KEY not found")
        return
    
    # 查找源页面
    page_id = find_page_by_date(args.date)
    if not page_id:
        print(f"Error: Page for {args.date} not found")
        return
    
    # 获取页面内容
    blocks = get_page_blocks(page_id)
    
    # 创建新页面
    url = create_page(args.date, blocks)
    print(f"Created: {url}")


if __name__ == "__main__":
    main()
