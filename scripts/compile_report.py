#!/usr/bin/env python3
"""
compile_report.py
接收标准化 sections JSON 数据，输出格式化的日报文本。

与数据来源完全解耦——可配合 fetch_report_data.py（Notion）或其他任意数据源。

输入（stdin / --data / --file）:
  {"date": "YYYY-MM-DD", "sections": {"本周目标": [...], "近期待办": [...], "AI 应用": [...]}}

输出:
  - --format markdown（默认）: Markdown 纯文本
  - --format html: 完整 HTML 文档

数据变换规则（compile_report 核心逻辑）:
  - "本周目标": 直接透传
  - "近期待办" → "今日完成": 含有已完成 todo 的子项归入今日完成
  - "近期待办" → "明日计划": 含有未完成 todo 的子项归入明日计划
  - "AI 应用": 直接透传
"""
import json
import sys
import argparse


def render_items_markdown(items, indent=0):
    """将标准化 items 列表渲染为 Markdown 无序列表。"""
    lines = []
    pref = "  " * indent
    for item in items:
        lines.append(pref + "- " + item["text"])
        for ch in item.get("children", []):
            if isinstance(ch, dict):
                lines.append(pref + "  - " + ch["text"])
            else:
                lines.append(pref + "  - " + str(ch))
    return "\n".join(lines) if lines else "- （无）"


def render_items_html_cell(items):
    """将标准化 items 列表渲染为 HTML <ul> 列表（用于表格单元格）。"""
    if not items:
        return "（无）"
    
    html_parts = []
    for item in items:
        text = item.get("text", "")
        children = item.get("children", [])
        
        html_parts.append(f"<p><strong>{text}</strong></p>")
        
        if children:
            html_parts.append("<ul>")
            for ch in children:
                if isinstance(ch, dict):
                    child_text = ch["text"]
                else:
                    child_text = str(ch)
                html_parts.append(f"<li>{child_text}</li>")
            html_parts.append("</ul>")
    
    return "\n".join(html_parts)


def render_items_html_table(items, indent=0):
    """将标准化 items 列表渲染为 HTML <tr>/<td> 表格行。"""
    if not items:
        return '<tr><th>任务</th><td>（无）</td></tr>'
    
    html_parts = []
    for item in items:
        text = item.get("text", "")
        children = item.get("children", [])
        
        # 主任务在左侧（表头样式）
        html_parts.append(f'<tr><th style="background:#f5f5f5;border:1px solid #ddd;padding:8px;text-align:left;">{text}</th>')
        
        if children:
            # 子任务渲染在右侧单元格
            html_parts.append('<td style="border:1px solid #ddd;padding:8px;">')
            html_parts.append("<ul>")
            for ch in children:
                if isinstance(ch, dict):
                    child_text = ch["text"]
                else:
                    child_text = str(ch)
                html_parts.append(f"<li>{child_text}</li>")
            html_parts.append("</ul>")
            html_parts.append("</td></tr>")
        else:
            html_parts.append('<td style="border:1px solid #ddd;padding:8px;"></td></tr>')
    
    return "\n".join(html_parts)


def compile_report(date_str, sections, output_format="markdown"):
    """
    将标准化 sections 数据编译为最终日报文本。
    
    核心变换:
      1. 近期待办按子项 checked 状态拆分为「今日完成」和「明日计划」
      2. 有子项的父级：按子项完成状态分流，无子项的独立 todo 按 checked 属性分流
      3. 普通 bullet 子项视为已完成
    """
    
    # 拆分近期待办 -> 今日完成 / 明日计划
    done, not_done = [], []
    for item in sections.get("近期待办", []):
        chs = item.get("children", [])
        if not chs:
            # 没有子项的独立 todo 项，检查 checked 属性
            if item.get("checked", False):
                done.append({"text": item["text"], "children": []})
            else:
                not_done.append({"text": item["text"], "children": []})
            continue
            
        # 子项分两类：直接是 todo，还是嵌套的 bullet
        done_sub, not_done_sub = [], []
        for c in chs:
            if isinstance(c, dict):
                if c.get("kind") == "todo":
                    if c.get("checked"):
                        done_sub.append(c)
                    else:
                        not_done_sub.append(c)
                else:
                    # 普通 bullet 视为已完成
                    done_sub.append(c)
            else:
                done_sub.append(c)

        # 根据子项的完成情况归类
        # 父项文本复用近期待办的原始文本，子项分别列出已完成/未完成的 todo
        if done_sub:
            done.append({"text": item["text"], "children": done_sub})
        if not_done_sub:
            not_done.append({"text": item["text"], "children": not_done_sub})

    # 获取数据
    本周目标 = sections.get("本周目标", [])
    AI应用 = sections.get("AI 应用", [])
    今日完成 = done
    明日计划 = not_done if not_done else [{"text": "（无）", "children": []}]
    
    if output_format == "html":
        # HTML 表格格式输出（四个一级标题作为表格行）
        return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>工作日报 {date}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; }}
        h1 {{ color: #333; border-bottom: 2px solid #4A90D9; padding-bottom: 10px; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f5f5f5; width: 100px; }}
        ul {{ margin: 5px 0; padding-left: 20px; }}
        li {{ margin: 3px 0; }}
    </style>
</head>
<body>
    <h1>工作日报</h1>
    <p><strong>日期：</strong>{date}</p>
    
    <table>
        <tr><th>本周目标</th><td>{本周目标}</td></tr>
        <tr><th>今日完成</th><td>{今日完成}</td></tr>
        <tr><th>明日计划</th><td>{明日计划}</td></tr>
        <tr><th>AI 应用</th><td>{AI应用}</td></tr>
    </table>
</body>
</html>""".format(
            date=date_str,
            本周目标=render_items_html_cell(本周目标),
            今日完成=render_items_html_cell(今日完成),
            明日计划=render_items_html_cell(明日计划),
            AI应用=render_items_html_cell(AI应用)
        )
    else:
        # Markdown 格式输出（默认）
        return """工作日报

日期：{date}

【本周目标】
{本周目标}

【今日完成】
{今日完成}

【明日计划】
{明日计划}

【AI 应用】
{AI应用}
""".format(
            date=date_str,
            本周目标=render_items_markdown(本周目标),
            今日完成=render_items_markdown(今日完成),
            明日计划=render_items_markdown(明日计划) if not_done else "- （无）",
            AI应用=render_items_markdown(AI应用)
        )


def main():
    parser = argparse.ArgumentParser(description="Compile standardized data into daily report")
    parser.add_argument("--data", help="JSON string of sections data")
    parser.add_argument("--file", help="Path to JSON file")
    parser.add_argument("--format", "-f", choices=["markdown", "html"], default="markdown", 
                        help="Output format: markdown or html (default: markdown)")
    parser.add_argument("--output", "-o", help="Output file (print to stdout if not specified)")
    args = parser.parse_args()

    if args.file:
        with open(args.file) as f:
            data = json.load(f)
    elif args.data:
        data = json.loads(args.data)
    else:
        # 从 stdin 读取
        data = json.load(sys.stdin)

    date_str = data.get("date", "")
    sections = data.get("sections", {})
    
    result = compile_report(date_str, sections, args.format)
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"Written to {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()
