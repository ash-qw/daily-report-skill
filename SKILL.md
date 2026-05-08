---
name: daily-report
description: 生成并发送工作日报。触发场景：博士说"发送日报"、"生成日报"、"发送工作日报"、"创建日报模板"。流程：读取 Notion → 编译日报 → 保存草稿箱（待确认）→ 发送。日报结构：本周目标/今日完成/明日计划/AI 应用。近期待办中已完成todo归今日完成，未完成归明日计划，子标题结构保留。

**注意**：邮件发送成功后**不再**自动创建明日日报模板。
---

# daily-report

## 定时任务配置（可选项）

本 skill 包含以下定时任务，用户可根据需要选择性启用。

**当用户首次安装本 skill 或询问"有哪些定时任务"时，AI 应主动介绍以下选项，询问用户需要启用哪些。**

### 可用定时任务

| 任务名称 | 触发时间 | 说明 |
|---------|---------|------|
| 日报模板-自动创建 | 每周一至周五 09:20（Asia/Shanghai） | 通过 `is_workday.py` 判断是否为工作日，非节假日自动在 Notion 创建当天日报模板 |
| 日报发送确认-询问加班 | 每周一至周五 17:55（Asia/Shanghai） | 询问博士"今天需要加班吗"，影响后续发送时间 |
| 日报发送-工作汇报 | 每周一至周五 21:35（Asia/Shanghai） | 生成日报草稿并保存到邮件草稿箱，等待博士确认后发送 |

### 创建定时任务

当用户选择启用某个定时任务时，AI 应使用 `openclaw task create` 命令（如果可用），或在 `~/.openclaw/cron/jobs.json` 中添加对应的 job 配置。

#### 定时任务 1：日报模板-自动创建

```json
{
  "id": "<生成唯一UUID>",
  "agentId": "main",
  "sessionKey": "agent:main:main",
  "name": "日报模板-自动创建",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "20 9 * * 1-5",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "执行以下步骤：\n\n1. 运行 python3 ~/.openclaw/scripts/is_workday.py 获取当日状态\n\n2. 如果输出包含 SKIP：退出，无需操作\n\n3. 如果输出包含 WORKDAY：从输出中提取 source 日期（格式 YYYY-MM-DD），然后运行：\n   NOTION_KEY=$(cat ~/.openclaw/workspace/api-keys/notion_api_key) python3 /home/node/.openclaw/workspace/skills/daily-report/scripts/create_from_template.py <source日期>\n\n4. 完成后简单汇报：成功 / 失败（附原因）",
    "timeoutSeconds": 300
  },
  "delivery": {
    "mode": "none",
    "channel": "last"
  }
}
```

#### 定时任务 2：日报发送确认-询问加班

```json
{
  "id": "<生成唯一UUID>",
  "agentId": "main",
  "sessionKey": "agent:main:main",
  "name": "日报发送确认-询问加班",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "55 17 * * 1-5",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "执行以下步骤：\n\nDATE=$(date +%Y-%m-%d)\nASKED_MARKER=\"$HOME/.openclaw/workspace/.daily_report_asked_$DATE\"\nSENT_MARKER=\"$HOME/.openclaw/workspace/.daily_report_sent_$DATE\"\n\n# 1. 运行 is_workday.py 判定\nWORKDAY_STATUS=$(python3 ~/.openclaw/scripts/is_workday.py 2>/dev/null)\n\n# 2. 非工作日则退出\nif echo \"$WORKDAY_STATUS\" | grep -q \"SKIP\"; then\n    echo \"非工作日，跳过询问\"\n    exit 0\nfi\n\n# 3. 已发送过则跳过\nif [ -f \"$SENT_MARKER\" ]; then\n    echo \"今日已发送日报，跳过询问\"\n    exit 0\nfi\n\n# 4. 发送询问消息并创建标记\n博士，今天需要加班吗？\ntouch \"$ASKED_MARKER\"\necho \"已询问博士是否加班\"",
    "timeoutSeconds": 300
  },
  "delivery": {
    "channel": "mattermost",
    "mode": "announce",
    "to": "user:<用户ID>"
  }
}
```

#### 定时任务 3：日报发送-工作汇报

```json
{
  "id": "<生成唯一UUID>",
  "agentId": "main",
  "sessionKey": "agent:main:main",
  "name": "日报发送-工作汇报",
  "enabled": true,
  "schedule": {
    "kind": "cron",
    "expr": "35 21 * * 1-5",
    "tz": "Asia/Shanghai"
  },
  "sessionTarget": "isolated",
  "wakeMode": "now",
  "payload": {
    "kind": "agentTurn",
    "message": "请执行以下步骤：\n\nDATE=$(date +%Y-%m-%d)\nMARKER_FILE=\"$HOME/.openclaw/workspace/.daily_report_sent_$DATE\"\n\n# 检查是否已手动发送过\nif [ -f \"$MARKER_FILE\" ]; then\n    echo \"今日已手动发送日报，跳过自动生成\"\n    exit 0\nfi\n\n1. 获取当前日期（北京时间），格式 YYYY-MM-DD\n2. 运行命令生成日报草稿：\n   python3 /home/node/.openclaw/workspace/skills/daily-report/scripts/daily_report.py <当天日期> --save-draft --profile \"工作汇报\"\n3. 草稿已保存，请在草稿箱确认。\n\n# 创建标记（方便次日自动清理）\ntouch \"$MARKER_FILE\"",
    "timeoutSeconds": 600
  },
  "delivery": {
    "channel": "mattermost",
    "mode": "announce",
    "to": "user:<用户ID>"
  }
}
```

### 注意事项

- 创建任务前需将 `<用户ID>` 替换为实际的 OpenClaw 用户 ID
- 每个任务 ID 使用 `uuidgen` 生成唯一值
- 建议将配置写入 `~/.openclaw/cron/jobs.json`，或通过 `openclaw task create` 命令创建
- 邮件发送需要先配置 profile：参考下方「邮件配置」章节

根据 Notion「工作进度」页面生成并发送工作日报。

**✅ 独立运行**：本技能不依赖其他技能，所有邮件功能已内联实现。

## 触发场景

- 博士说"发送日报"、"发送工作日报" → 读取 Notion → 编译日报 → 保存草稿箱 → 博士确认后发送
- 博士说"生成日报"、"创建日报模板" → 在 Notion 中重新创建/更新当天（T+0）的日报模板页，不发送
- **定时任务（自动）**：每周一至周五 09:20，通过 `is_workday.py` 判断是否为工作日，非节假日则自动创建当天模板

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
