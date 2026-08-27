#!/usr/bin/env python3
"""
邮件通知组件。

通过 SMTP 发送 AgentRouter 签到结果，作为独立模块被 checkin.py 调用。
发件人、收件人和 SMTP 服务器信息全部从环境变量读取。
"""

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, parseaddr
from html import escape
from typing import Dict, List, Tuple

log = logging.getLogger("notify")

SUPPORTED_SECURITY = {"ssl", "starttls", "none"}


def _clean_header(value: str) -> str:
    """移除可能导致邮件头注入的换行符。"""
    return re.sub(r"[\r\n]+", " ", value or "").strip()


def _parse_recipients(raw: str) -> List[Tuple[str, str]]:
    """解析逗号、分号或换行分隔的收件人列表。"""
    normalized = re.sub(r"[;\r\n]+", ",", raw or "")
    recipients = []
    for name, address in getaddresses([normalized]):
        address = address.strip()
        if not address:
            continue
        recipients.append((_clean_header(name), address))
    return recipients


def _load_email_config() -> Dict[str, object]:
    """从环境变量加载并校验 SMTP 邮件配置。"""
    host = (os.getenv("SMTP_HOST") or "").strip()
    username = (os.getenv("SMTP_USERNAME") or "").strip()
    password = os.getenv("SMTP_PASSWORD") or ""
    security = (os.getenv("SMTP_SECURITY") or "ssl").strip().lower()

    if security not in SUPPORTED_SECURITY:
        raise ValueError("SMTP_SECURITY 仅支持 ssl、starttls 或 none")

    default_port = 465 if security == "ssl" else (587 if security == "starttls" else 25)
    raw_port = (os.getenv("SMTP_PORT") or str(default_port)).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("SMTP_PORT 必须是有效的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SMTP_PORT 必须在 1 到 65535 之间")

    raw_from = (os.getenv("EMAIL_FROM") or "").strip()
    parsed_from_name, from_address = parseaddr(raw_from)
    from_name = _clean_header(os.getenv("EMAIL_FROM_NAME") or parsed_from_name)
    recipients = _parse_recipients(os.getenv("EMAIL_TO") or "")

    missing = []
    if not host:
        missing.append("SMTP_HOST")
    if not from_address:
        missing.append("EMAIL_FROM")
    if not recipients:
        missing.append("EMAIL_TO")
    if missing:
        raise ValueError("缺少邮件配置：" + "、".join(missing))

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "security": security,
        "from_name": from_name,
        "from_address": from_address,
        "recipients": recipients,
    }


def _send_email(subject: str, text_body: str, html_body: str) -> bool:
    """使用环境变量中的 SMTP 配置发送一封纯文本 + HTML 邮件。"""
    try:
        config = _load_email_config()
    except ValueError as exc:
        log.info("邮件通知已跳过: %s", exc)
        return False

    from_address = str(config["from_address"])
    from_name = str(config["from_name"])
    recipients = config["recipients"]
    recipient_headers = [formataddr((name, address)) for name, address in recipients]
    recipient_addresses = [address for _, address in recipients]

    message = EmailMessage()
    message["Subject"] = _clean_header(subject)
    message["From"] = formataddr((from_name, from_address)) if from_name else from_address
    message["To"] = ", ".join(recipient_headers)
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    host = str(config["host"])
    port = int(config["port"])
    username = str(config["username"])
    password = str(config["password"])
    security = str(config["security"])
    tls_context = ssl.create_default_context()

    try:
        if security == "ssl":
            smtp_client = smtplib.SMTP_SSL(host, port, timeout=15, context=tls_context)
        else:
            smtp_client = smtplib.SMTP(host, port, timeout=15)

        with smtp_client as smtp:
            if security == "starttls":
                smtp.ehlo()
                smtp.starttls(context=tls_context)
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(
                message,
                from_addr=from_address,
                to_addrs=recipient_addresses,
            )
        log.info("邮件通知发送成功，共 %d 位收件人", len(recipient_addresses))
        return True
    except (OSError, smtplib.SMTPException) as exc:
        log.error("邮件通知发送失败: %s", exc)
        return False


def send_email_notification(data: dict) -> bool:
    """
    发送单用户签到邮件。

    data:
    {
        "username":    str,   # 脱敏后的用户名
        "date":        str,   # 北京时间日期
        "checked_in":  bool,  # True=今日已签到，False=本次新签到
        "balance_usd": float, # 当前余额
    }
    """
    username = str(data.get("username", ""))
    date = str(data.get("date", ""))
    balance = data.get("balance_usd", 0.0)
    status = "今日已签到" if data.get("checked_in") else "签到成功，额度已到账"
    status_icon = "✅" if data.get("checked_in") else "🎉"

    subject = f"AgentRouter 签到通知 - {date}"
    text_body = (
        "AgentRouter 签到通知\n"
        "----------------\n"
        f"日期：{date}\n"
        f"用户：{username}\n"
        f"签到：{status}\n"
        f"余额：${balance:,.2f}\n"
    )
    html_body = (
        "<html><body>"
        "<h2>AgentRouter 签到通知</h2>"
        f"<p>📅 <strong>日期</strong>：{escape(date)}</p>"
        f"<p>👤 <strong>用户</strong>：{escape(username)}</p>"
        f"<p>{status_icon} <strong>签到</strong>：{escape(status)}</p>"
        f"<p>💰 <strong>余额</strong>：${balance:,.2f}</p>"
        "</body></html>"
    )
    return _send_email(subject, text_body, html_body)


def _bjt_date_str() -> str:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone(timedelta(hours=8)))
    return f"{now.year}年{now.month:02d}月{now.day:02d}日"


def send_combined_email_notification(results: list) -> bool:
    """发送多用户汇总签到邮件。"""
    success = [result for result in results if not result.get("error")]
    total_balance = sum(result.get("balance_usd", 0.0) for result in success)
    date = _bjt_date_str()

    text_lines = [
        "AgentRouter 签到通知",
        "----------------",
        f"日期：{date}",
        f"数量：{len(results)} 个账号",
        "----------------",
    ]
    html_rows = []

    for result in results:
        display = str(result.get("display", ""))
        if result.get("error"):
            status = f"❌ 登录失败：{result['error']}"
        elif result.get("checked_in"):
            status = f"🎉 签到成功，余额 ${result.get('balance_usd', 0.0):,.2f}"
        else:
            status = f"✅ 今日已签到，余额 ${result.get('balance_usd', 0.0):,.2f}"

        text_lines.extend([f"账号：{display}", f"  {status}"])
        html_rows.append(
            "<tr>"
            f"<td style=\"padding:6px 12px;border:1px solid #ddd\">{escape(display)}</td>"
            f"<td style=\"padding:6px 12px;border:1px solid #ddd\">{escape(status)}</td>"
            "</tr>"
        )

    text_lines.extend(["----------------", f"总余额：${total_balance:,.2f}"])
    text_body = "\n".join(text_lines) + "\n"
    html_body = (
        "<html><body>"
        "<h2>AgentRouter 签到通知</h2>"
        f"<p>📅 <strong>日期</strong>：{escape(date)}</p>"
        f"<p>✅ <strong>数量</strong>：{len(results)} 个账号</p>"
        "<table style=\"border-collapse:collapse\">"
        "<thead><tr>"
        "<th style=\"padding:6px 12px;border:1px solid #ddd;text-align:left\">账号</th>"
        "<th style=\"padding:6px 12px;border:1px solid #ddd;text-align:left\">结果</th>"
        "</tr></thead>"
        f"<tbody>{''.join(html_rows)}</tbody>"
        "</table>"
        f"<p>💰 <strong>总余额</strong>：${total_balance:,.2f}</p>"
        "</body></html>"
    )
    subject = f"AgentRouter 签到汇总 - {date}（{len(results)} 个账号）"
    return _send_email(subject, text_body, html_body)
