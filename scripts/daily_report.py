#!/usr/bin/env python3
"""
Daily Report Generator
编排层：fetch → compile → 草稿/发送
所有数据获取逻辑均在 fetch_report_data.py 中，日报生成逻辑在 compile_report.py 中。

独立运行，不依赖其他技能。
"""

import json
import sys
import subprocess
import os
import time
import imaplib
import smtplib
import ssl
import re
from email.mime.text import MIMEText
from email.header import Header
from email.generator import Generator
from io import StringIO

FETCH_SCRIPT = os.path.join(os.path.dirname(__file__), "fetch_report_data.py")
COMPILE_SCRIPT = os.path.join(os.path.dirname(__file__), "compile_report.py")
DRAFT_LOG = os.path.expanduser("~/.openclaw/workspace/record/日报草稿/draft_uid.txt")
MAIL_CONFIG_PATH = os.path.expanduser("~/.openclaw/conf/enterprise-mail/config.json")


# ── Draft log ─────────────────────────────────────────────────────────────────

def save_draft_uid(date_str, uid, profile=None):
    os.makedirs(os.path.dirname(DRAFT_LOG), exist_ok=True)
    with open(DRAFT_LOG, "w") as f:
        f.write(date_str + "\n" + str(uid) + "\n" + (profile or ""))


def load_draft_uid():
    if not os.path.exists(DRAFT_LOG):
        return None, None, None
    with open(DRAFT_LOG) as f:
        lines = f.read().strip().split("\n")
    if len(lines) < 2:
        return None, None, None
    return lines[0], lines[1], lines[2] if len(lines) > 2 else None


def clear_draft_uid():
    if os.path.exists(DRAFT_LOG):
        os.remove(DRAFT_LOG)


# ── Profile lookup ─────────────────────────────────────────────────────────────

def get_profile_to_cc(profile_name):
    conf_path = os.path.expanduser("~/.openclaw/conf/enterprise-mail/config.json")
    if not os.path.exists(conf_path):
        return [], []
    with open(conf_path) as f:
        config = json.load(f)
    profiles = config.get("profiles", {})
    for pname, pdata in profiles.items():
        if profile_name.lower() in pname.lower():
            return pdata.get("to", []), pdata.get("cc", [])
    return [], []


def create_profile_to_cc(profile_name, to_list, cc_list=None):
    """
    在配置文件中创建或更新发送 profile。

    Args:
        profile_name: Profile 名称（如 "工作汇报"）
        to_list: 收件人邮箱列表
        cc_list: 抄送人邮箱列表（可选）
    """
    conf_path = os.path.expanduser("~/.openclaw/conf/enterprise-mail/config.json")
    with open(conf_path) as f:
        config = json.load(f)

    if "profiles" not in config:
        config["profiles"] = {}

    config["profiles"][profile_name] = {
        "to": to_list,
        "cc": cc_list or []
    }

    with open(conf_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"[OK] Profile '{profile_name}' saved to {conf_path}")
    print(f"  To: {', '.join(to_list)}")
    if cc_list:
        print(f"  Cc: {', '.join(cc_list)}")


# ── Mail Configuration ───────────────────────────────────────────────────────

def load_mail_config():
    """加载邮件配置"""
    if not os.path.exists(MAIL_CONFIG_PATH):
        print(f"[ERROR] Mail config not found: {MAIL_CONFIG_PATH}")
        return None
    with open(MAIL_CONFIG_PATH) as f:
        config = json.load(f)
    required = ["smtp", "auth", "from"]
    for key in required:
        if key not in config:
            print(f"[ERROR] Missing required config: {key}")
            return None
    return config


# ── Save Draft to IMAP ───────────────────────────────────────────────────────

def save_draft_to_imap(subject, content, recipients, cc_list=None, is_html=False):
    """
    保存邮件到 IMAP 草稿箱
    
    Returns:
        (success: bool, uid: str or None)
    """
    config = load_mail_config()
    if not config:
        return False, None
    
    if not recipients:
        recipients = config.get("to", [])
    if cc_list is None:
        cc_list = config.get("cc", [])
    
    imap_host = config.get("imap", {}).get("host", "imap.exmail.qq.com")
    imap_port = config.get("imap", {}).get("port", 993)
    user = config["auth"]["user"]
    password = config["auth"]["password"]
    from_addr = config["from"]
    
    try:
        print(f"[IMAP] Connecting to {imap_host}:{imap_port}...")
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, ssl_context=ctx, timeout=20)
        mail.login(user, password)
        print("[IMAP] Login OK!")
        
        status, _ = mail.select('"Drafts"')
        if status != 'OK':
            print(f"[ERROR] Failed to select Drafts: {status}")
            mail.logout()
            return False, None
        print("[IMAP] Drafts OK!")
        
        # Build email
        subtype = 'html' if is_html else 'plain'
        msg = MIMEText(content, subtype, 'utf-8')
        msg['From'] = from_addr
        msg['To'] = ", ".join(recipients)
        if cc_list:
            msg['Cc'] = ", ".join(cc_list)
        msg['Subject'] = Header(subject, 'utf-8')
        
        # Save draft
        result = mail.append(
            '"Drafts"',
            '\\Draft',
            time.time(),
            msg.as_string().encode('utf-8')
        )
        
        # Get UID of saved draft
        uid = None
        mail.select("Drafts")
        status, msg_ids = mail.search(None, "ALL")
        if status == "OK" and msg_ids[0]:
            uids = msg_ids[0].split()
            uid = uids[-1].decode() if uids else None
        
        mail.logout()
        
        print(f"\n[IMAP] Draft saved!")
        print(f"  Subject: {subject}")
        print(f"  To: {', '.join(recipients)}")
        if uid:
            print(f"  UID: {uid}")
        return True, uid
        
    except Exception as e:
        print(f"[ERROR] Draft save failed: {e}")
        return False, None


# ── Send Email via SMTP ─────────────────────────────────────────────────────--

def send_email_native(subject, content, recipients, cc_list=None, is_html=False, max_retries=3):
    """
    使用原生 SMTP 发送邮件
    
    Returns:
        (success: bool, error_msg: str or None)
    """
    config = load_mail_config()
    if not config:
        return False, "Failed to load config"
    
    if not recipients:
        recipients = config.get("to", [])
    if cc_list is None:
        cc_list = config.get("cc", [])
    
    smtp_host = config["smtp"].get("host", "smtp.exmail.qq.com")
    smtp_port = config["smtp"].get("port", 465)
    smtp_ssl = config["smtp"].get("ssl", True)
    user = config["auth"]["user"]
    password = config["auth"]["password"]
    from_addr = config["from"]
    
    all_recipients = recipients + cc_list
    
    for attempt in range(max_retries):
        try:
            print(f"[SMTP] Connecting to {smtp_host}:{smtp_port}... (attempt {attempt + 1}/{max_retries})")
            
            if smtp_ssl:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
            
            server.login(user, password)
            print("[SMTP] Login successful")
            
            # Build and send email
            subtype = 'html' if is_html else 'plain'
            msg = MIMEText(content, subtype, 'utf-8')
            msg['From'] = from_addr
            msg['To'] = ", ".join(recipients)
            if cc_list:
                msg['Cc'] = ", ".join(cc_list)
            msg['Subject'] = Header(subject, 'utf-8')
            
            server.sendmail(from_addr, all_recipients, msg.as_string())
            server.quit()
            
            print("[SMTP] Email sent successfully!")
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            print(f"[SMTP] Attempt {attempt + 1} failed: {error_msg}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"[SMTP] Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                return False, error_msg
    
    return False, "Max retries exceeded"


# ── Send Draft via SMTP with Retry ─────────────────────────────────────────--

def send_draft_with_retry(raw_email_bytes, from_addr, to_list, cc_list, smtp_config, max_retries=3):
    """
    使用原生 SMTP 客户端从内存发送 RFC822 邮件
    带指数退避重试机制
    
    Args:
        raw_email_bytes: RFC822 格式的邮件内容 (bytes)
        from_addr: 发件人地址
        to_list: 收件人列表
        cc_list: 抄送人列表
        smtp_config: SMTP 配置字典 {host, port, ssl, user, password}
        max_retries: 最大重试次数
    
    Returns:
        (success: bool, error_msg: str)
    """
    import smtplib
    import time
    
    smtp_host = smtp_config.get("host", "smtp.exmail.qq.com")
    smtp_port = smtp_config.get("port", 465)
    smtp_ssl = smtp_config.get("ssl", True)
    user = smtp_config["user"]
    password = smtp_config["password"]
    
    recipients = to_list + (cc_list if cc_list else [])
    
    for attempt in range(max_retries):
        try:
            print(f"[SMTP] Connecting to {smtp_host}:{smtp_port}... (attempt {attempt + 1}/{max_retries})")
            
            if smtp_ssl:
                server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                server.starttls()
            
            server.login(user, password)
            print("[SMTP] Login successful")
            
            # 从内存直接发送 RFC822 内容
            # 使用 email.message_from_string 解析 RFC822 字符串
            # send_message 会覆盖邮件头中的收件人，所以我们需要手动处理
            from email import message_from_string
            
            # 解析 RFC822 内容
            if isinstance(raw_email_bytes, bytes):
                raw_str = raw_email_bytes.decode('utf-8', errors='ignore')
            else:
                raw_str = raw_email_bytes
            
            msg = message_from_string(raw_str)
            
            # 使用邮件头中的收件人，如果为空则使用传入的 recipients
            header_to = msg.get('To', '')
            if header_to:
                # 解析邮件头中的收件人列表
                import email.utils
                # getaddresses 需要列表参数
                parsed = email.utils.getaddresses([header_to])
                effective_recipients = [addr for name, addr in parsed if addr]
            else:
                effective_recipients = recipients if recipients else [from_addr]
            
            # 发送邮件
            server.send_message(msg, from_addr=from_addr, to_addrs=effective_recipients)
            server.quit()
            
            print(f"[SMTP] Email sent successfully!")
            return True, None, effective_recipients
            
        except Exception as e:
            error_msg = str(e)
            print(f"[SMTP] Attempt {attempt + 1} failed: {error_msg}")
            
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                print(f"[SMTP] Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                return False, error_msg
    
    return False, "Max retries exceeded"


def delete_imap_draft(uid, imap_config, auth_config):
    """
    删除 IMAP 草稿箱中的指定邮件
    
    Returns:
        bool: 是否成功删除
    """
    import imaplib
    import ssl
    
    try:
        host = imap_config.get("host", "imap.exmail.qq.com")
        port = imap_config.get("port", 993)
        user = auth_config["user"]
        password = auth_config["password"]
        
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
        mail.login(user, password)
        mail.select("Drafts")
        
        # 使用 UID 删除
        mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
        mail.expunge()
        mail.logout()
        
        print(f"[IMAP] Draft {uid} deleted")
        return True
        
    except Exception as e:
        print(f"[WARNING] Failed to delete draft {uid}: {e}")
        return False


def delete_drafts_by_subject(imap_config, auth_config, date_str):
    """
    删除草稿箱中所有当天创建的日报草稿（按 subject 匹配）
    用于发送成功后清理同一天的所有废稿
    
    Returns:
        int: 删除的草稿数量
    """
    import imaplib
    import ssl
    import re
    from email.header import decode_header
    
    try:
        host = imap_config.get("host", "imap.exmail.qq.com")
        port = imap_config.get("port", 993)
        user = auth_config["user"]
        password = auth_config["password"]
        
        ctx = ssl.create_default_context()
        mail = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
        mail.login(user, password)
        mail.select("Drafts")
        
        # 搜索所有草稿
        status, msg_ids = mail.search(None, "ALL")
        if status != "OK" or not msg_ids[0]:
            mail.logout()
            return 0
        
        # 目标 subject 模式：工作日报 - YYYY-MM-DD
        target_subject = f"工作日报 - {date_str}"
        
        deleted_count = 0
        all_ids = msg_ids[0].split()
        
        for mid in all_ids:
            # 获取邮件头
            status, head_data = mail.fetch(mid, "(ENVELOPE)")
            if status != "OK" or not head_data:
                continue
            
            # 解析 ENVELOPE 获取 subject
            try:
                import email
                # 用 RFC822 方式获取完整邮件再解析 subject
                status, msg_data = mail.fetch(mid, "(RFC822.HEADER)")
                if status != "OK" or not msg_data:
                    continue
                
                raw_header = msg_data[0][1]
                if isinstance(raw_header, bytes):
                    raw_header = raw_header.decode('utf-8', errors='ignore')
                
                msg = email.message_from_string(raw_header)
                subject = msg.get('Subject', '')
                
                # 解码 subject（处理 =?UTF-8?...?= 格式）
                decoded_parts = decode_header(subject)
                decoded_subject = ''
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        charset = charset or 'utf-8'
                        try:
                            decoded_subject += part.decode(charset, errors='ignore')
                        except:
                            decoded_subject += part.decode('utf-8', errors='ignore')
                    else:
                        decoded_subject += part
                
                # 匹配目标 subject
                if target_subject in decoded_subject:
                    # 获取 UID 并删除
                    status, uid_data = mail.fetch(mid, "(UID)")
                    if status == "OK" and uid_data and uid_data[0]:
                        uid_match = re.search(r'UID\s+(\d+)', uid_data[0].decode() if isinstance(uid_data[0], bytes) else str(uid_data[0]))
                        if uid_match:
                            uid = uid_match.group(1)
                            mail.uid("STORE", uid, "+FLAGS", "\\Deleted")
                            deleted_count += 1
                            print(f"[IMAP] Deleted draft UID {uid}: {decoded_subject}")
                            
            except Exception as e:
                print(f"[WARNING] Failed to process message {mid}: {e}")
                continue
        
        # 真正执行删除
        if deleted_count > 0:
            mail.expunge()
        
        mail.logout()
        return deleted_count
        
    except Exception as e:
        print(f"[WARNING] Failed to delete drafts by subject: {e}")
        return 0


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", help="YYYY-MM-DD")
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--profile", "-p", help="Email profile name")
    parser.add_argument("--save-draft", action="store_true", help="Save to IMAP draft")
    parser.add_argument("--send-draft", metavar="UID", help="Send draft by UID")
    parser.add_argument("--format", "-f", choices=["markdown", "html"], default="html", help="Output format: markdown or html (default: html)")
    parser.add_argument("--create-profile", metavar="JSON", help='创建发送 profile，格式：\'{"name":"profile_name","to":["a@a.com"],"cc":["b@b.com"]}\'')
    args = parser.parse_args()
    profile = args.profile
    output_format = args.format

    # Create profile
    if args.create_profile:
        import json as jsonmod
        try:
            data = jsonmod.loads(args.create_profile)
            name = data["name"]
            to_list = data.get("to", [])
            cc_list = data.get("cc", [])
            create_profile_to_cc(name, to_list, cc_list)
        except (jsonmod.JSONDecodeError, KeyError) as e:
            print(f"[ERROR] Invalid profile JSON: {e}")
            sys.exit(1)
        sys.exit(0)

    # Send existing draft
    if args.send_draft:
        import imaplib
        import ssl
        import json as jsonmod

        conf_path = os.path.expanduser("~/.openclaw/conf/enterprise-mail/config.json")
        with open(conf_path) as f:
            config = jsonmod.load(f)

        to_list, cc_list = get_profile_to_cc(profile) if profile else ([], [])
        
        # 获取配置
        imap_cfg = config.get("imap", {})
        smtp_cfg = config.get("smtp", {})
        auth_cfg = config.get("auth", {})
        from_addr = config.get("from", auth_cfg.get("user", ""))
        
        # 合并 SMTP 配置
        smtp_config = {
            "host": smtp_cfg.get("host", "smtp.exmail.qq.com"),
            "port": smtp_cfg.get("port", 465),
            "ssl": smtp_cfg.get("ssl", True),
            "user": auth_cfg["user"],
            "password": auth_cfg["password"]
        }
        
        # IMAP 获取草稿原始内容
        host = imap_cfg.get("host", "imap.exmail.qq.com")
        port = imap_cfg.get("port", 993)
        user = auth_cfg["user"]
        password = auth_cfg["password"]
        
        ctx = ssl.create_default_context()
        m = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=20)
        
        try:
            m.login(user, password)
            m.select("Drafts")
            
            # 获取最新草稿
            status, msg_ids = m.search(None, "ALL")
            if status != "OK" or not msg_ids[0]:
                print("[ERROR] Drafts folder is empty")
                sys.exit(1)
            
            ids = msg_ids[0].split()
            if not ids:
                print("[ERROR] No drafts found")
                sys.exit(1)
            
            # 获取草稿 UID
            latest_id = ids[-1]
            status, uid_data = m.fetch(latest_id, "(UID)")
            if status != "OK" or not uid_data or not uid_data[0]:
                print("[ERROR] Could not get draft UID")
                sys.exit(1)
            
            # 解析 UID
            uid_match = uid_data[0].decode() if isinstance(uid_data[0], bytes) else str(uid_data[0])
            import re
            uid_pattern = r'UID\s+(\d+)'
            uid_match_result = re.search(uid_pattern, uid_match)
            draft_uid = uid_match_result.group(1) if uid_match_result else latest_id.decode() if isinstance(latest_id, bytes) else latest_id
            
            # 获取 RFC822 内容
            result, msg_data = m.fetch(latest_id, "(RFC822)")
            if result != "OK" or not msg_data or not msg_data[0]:
                print("[ERROR] Draft not found")
                sys.exit(1)
            
            # 从内存获取原始 RFC822 数据（不写入文件）
            raw_email = msg_data[0][1]
            if isinstance(raw_email, str):
                raw_email = raw_email.encode('utf-8')
            
            print(f"[INFO] Draft retrieved (UID: {draft_uid}, size: {len(raw_email)} bytes)")
            
        finally:
            m.logout()

        # 使用原生 SMTP 发送（带重试）
        success, error_msg, sent_recipients = send_draft_with_retry(
            raw_email_bytes=raw_email,
            from_addr=from_addr,
            to_list=to_list,
            cc_list=cc_list,
            smtp_config=smtp_config,
            max_retries=3
        )
        
        if not success:
            print(f"[ERROR] Failed to send email after retries: {error_msg}")
            sys.exit(1)
        
        # SMTP 成功后才删除草稿
        print(f"[INFO] Email sent successfully!")
        print(f"  To: {', '.join(sent_recipients)}")
        if cc_list:
            print(f"  Cc: {', '.join(cc_list)}")
        
        # 删除 IMAP 草稿（发送成功后才执行）
        # 1. 从 draft_uid.txt 读取日期
        draft_date, _, _ = load_draft_uid()
        
        # 2. 先删除当前发送的草稿
        delete_success = delete_imap_draft(draft_uid, imap_cfg, auth_cfg)
        
        # 3. 清理同一天的所有日报草稿（废稿）
        if delete_success and draft_date:
            deleted_count = delete_drafts_by_subject(imap_cfg, auth_cfg, draft_date)
            if deleted_count > 0:
                print(f"[IMAP] Cleaned up {deleted_count - 1} leftover draft(s) for {draft_date}")
            clear_draft_uid()
        else:
            print("[WARNING] Draft sent but could not delete from IMAP")
        
        sys.exit(0)

    if not args.date:
        print("[ERROR] date required")
        sys.exit(1)

    date_str = args.date.strip()
    test_mode = args.test

    # 1. Fetch: 调用 fetch_report_data.py 获取标准化 JSON
    r = subprocess.run(
        ["python3", FETCH_SCRIPT, date_str],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("[ERROR] fetch failed:", r.stderr)
        sys.exit(1)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("[ERROR] failed to parse fetched data")
        sys.exit(1)

    sections = data.get("sections", {})

    # 2. Check empty (正式模式)
    empty = [k for k in ["本周目标", "近期待办", "AI 应用"] if not sections.get(k)]
    if empty and not test_mode and not args.save_draft:
        print("[EMPTY] Empty sections: " + ", ".join(empty) + ". Exiting.")
        sys.exit(0)

    # 3. Compile: 调用 compile_report.py 生成日报文本
    data_json = json.dumps({"date": date_str, "sections": sections})
    r = subprocess.run(
        ["python3", COMPILE_SCRIPT, "--data", data_json, "--format", output_format],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("[ERROR] compile failed:", r.stderr)
        sys.exit(1)
    body = r.stdout

    subject = "工作日报 - " + date_str

    # 4a. Save to draft
    if args.save_draft:
        to_list, cc_list = get_profile_to_cc(profile) if profile else ([], [])
        is_html = output_format == "html"
        
        success, uid = save_draft_to_imap(
            subject=subject,
            content=body,
            recipients=to_list,
            cc_list=cc_list,
            is_html=is_html
        )
        
        if success and uid:
            save_draft_uid(date_str, uid, profile)
            print()
            print("[CONFIRM] Subject: " + subject)
            if to_list:
                print("  To: " + ", ".join(to_list))
            if cc_list:
                print("  Cc: " + ", ".join(cc_list))
            print("  UID: " + uid)
            sys.exit(0)
        else:
            sys.exit(1)

    # 4b. Send directly using native SMTP
    to_list, cc_list = get_profile_to_cc(profile) if profile else ([], [])
    is_html = output_format == "html"
    
    success, error_msg = send_email_native(
        subject=subject,
        content=body,
        recipients=to_list,
        cc_list=cc_list,
        is_html=is_html,
        max_retries=3
    )
    
    if not success:
        print(f"[ERROR] Failed to send email: {error_msg}")
        sys.exit(1)
    
    print("[OK] Email sent: " + date_str)

    # 5. 不再自动创建明日页面（2026-04-14 博士决定禁用）
    print("[OK] Done. Next-day page creation is disabled.")


if __name__ == "__main__":
    main()
