---
name: daily-report
description: 生成并发送工作日报。触发场景：博士说"发送日报"、"生成日报"、"发送工作日报"、"创建日报模板"。流程：读取 Notion → 编译日报 → 保存草稿箱（待确认）→ 发送。日报结构：本周目标/今日完成/明日计划/AI 应用。近期待办中已完成todo归今日完成，未完成归明日计划，子标题结构保留。

**注意**：邮件发送成功后**不再**自动创建明日日报模板。
---

# daily-report

根据 Notion「工作进度」页面生成并发送工作日报。

**✅ 独立运行**：本技能不依赖其他技能，所有邮件功能已内联实现。

## 触发场景

- 博士说"发送日报"、"发送工作日报" → 读取 Notion → 编译日报 → 保存草稿箱 → 博士确认后发送
- 博士说"生成日报"、"创建日报模板" → 在 Notion 中重新创建/更新当天（T+0）的日报模板页，不发送
- **定时任务（自动）**：
  - **09:20** — 日报模板-自动创建：每周一至周五，通过 `is_workday.py` 判断是否为工作日，非节假日则自动创建当天模板（基于昨日页面）
  - **17:55** — 日报发送确认-询问加班：每周一至周五，询问博士是否加班；博士回复"不加班"/"不需要加班"/"不加班了"时，立即生成草稿箱并等待确认，确认后说"发送"即可实际发送
  - **21:35** — 日报发送-工作汇报：每周一至周五，若 17:55 后博士未回复"不加班"，则自动发送草稿（使用 `is_workday.py` 判断是否为工作日，非工作日跳过）

## 架构（模块）

```
is_workday.py           → 判断今天是否为工作日（排除周末和法定节假日）
fetch_report_data.py    → 从 Notion 读取数据，输出标准化 JSON
compile_report.py       → 接收标准化 JSON，输出格式化日报文本
create_from_template.py → 根据指定日期内容创建新日报模板（支持递归子项，模块化版本）
daily_report.py         → 编排脚本：fetch → compile → 发送（不再创建明日页面）
```

## 脚本说明

### is_workday.py
`~/.openclaw/scripts/is_workday.py`
- 判断今天是否为工作日（排除周末和法定节假日）
- 输出：`SKIP: 周末` / `SKIP: 节假日名假期` / `WORKDAY: today=YYYY-MM-DD source=YYYY-MM-DD`
- 节假日列表内置，支持完整假期时段判断（2026年）
- 由定时任务"日报模板-自动创建"调用

### fetch_report_data.py
- 读取 Notion 指定日期页面，输出标准化 JSON
- sections 结构：`{"本周目标": [], "近期待办": [], "AI 应用": []}`

### compile_report.py
- 接收 JSON（`--data` 或 `--file`），输出格式化日报文本
- 支持 `--format markdown`（默认）或 `--format html`

### create_from_template.py
- 根据指定日期的日报内容，创建新一天的日报模板
- 规则：
  - 本周目标：直接复制（包含嵌套子项）
  - 近期待办：保留含未完成 todo 的子项，递归复制所有层级，已完成的不复制
  - 待办清单：直接复制（昨日有什么就复制什么，包含所有嵌套子项）
  - AI 应用：仅保留标题
  - 其他一级标题：完全复制
- 支持递归处理：自动获取并复制嵌套的 bulleted_list_item、to_do、numbered_list_item 等

### daily_report.py
- 主编排脚本，调用 fetch + compile 完成全流程
- **独立实现邮件功能**：内联 `save_draft_to_imap()`, `send_email_native()` 等函数，不依赖其他技能
- `get_profile_to_cc()` — 从配置文件读取发送 profile
- `create_profile_to_cc()` — 创建或更新发送 profile 并写入配置文件

## 使用方式

```bash
# 判断今天是否为工作日（非定时任务调用）
python3 ~/.openclaw/scripts/is_workday.py

# 根据指定日期创建模板（博士说"创建日报模板"时触发）
python3 create_from_template.py <YYYY-MM-DD>

# 创建发送 profile
python3 daily_report.py --create-profile '{"name":"团队名","to":["a@a.com"],"cc":["b@b.com"]}'

# 保存草稿（推荐）
python3 daily_report.py <YYYY-MM-DD> --save-draft [--profile NAME]
python3 daily_report.py --send-draft UID [--profile NAME]   # 发送草稿

# 直接发送（旧模式，兼容）
python3 daily_report.py <YYYY-MM-DD> [--profile NAME]
```

## 日报结构规范

| 顶层字段 | 来源规则 |
|---------|---------|
| 本周目标 | Notion 直接读取 |
| 今日完成 | 近期待办中**已完成**的 todo（保留子标题） |
| 明日计划 | 近期待办中**未完成**的 todo |
| AI 应用 | Notion 直接读取 |

- 近期待办的子标题结构需保留
- 日报中不显示 checkbox `[x]` 状态，只显示内容

## 空值处理

- 正式发送前：若"本周目标"、"近期待办"、"AI 应用"为空，提醒博士补充
- 测试/草稿模式：不检查，直接继续

## 邮件配置

本技能独立运行，使用原生 Python 邮件库（imaplib/smtplib）发送邮件。

配置文件：`~/.openclaw/conf/enterprise-mail/config.json`

```json
{
  "imap": { "host": "imap.exmail.qq.com", "port": 993 },
  "smtp": { "host": "smtp.exmail.qq.com", "port": 465, "ssl": true },
  "auth": { "user": "your-email@company.com", "password": "your-auth-code" },
  "from": "your-email@company.com",
  "profiles": {
    "测试团队": {
      "to": ["recipient1@company.com"],
      "cc": ["cc1@company.com"]
    }
  }
}
```

发送命令：
```bash
--profile "测试团队"   # 使用指定发送对象配置
```

博士确认草稿后说"发送"再实际发送。

### 实现特性
- ✅ 原生 SMTP 发送（无需 curl）
- ✅ 指数退避重试（1s, 2s, 4s）
- ✅ 从内存发送 RFC822 邮件（无临时文件）
- ✅ SMTP 成功后**保证**删除草稿
- ✅ 从邮件头提取收件人，兼容 profile 配置
- ✅ 发送成功后**自动清理同一天的所有日报草稿**（废稿）
  - 场景：同一天多次保存草稿时，发送后其他废稿会被一并删除
  - 原理：按 subject 匹配 `工作日报 - YYYY-MM-DD` 扫描草稿箱
