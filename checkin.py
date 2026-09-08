#!/usr/bin/env python3
"""
AgentRouter 每日签到脚本（支持本地运行与 GitHub Actions）

需要的配置（环境变量）：
  AGENTROUTER_USERNAME   登录用户名或邮箱（单用户模式）
  AGENTROUTER_PASSWORD   登录密码（单用户模式）
  AGENTROUTER_ACCOUNTS   多账号批量登录，格式 user1:pass1,user2:pass2
                         支持换行或逗号分隔（多用户模式），user id 登录后自动获取
  SOCKS5_PROXY           代理，可多个（换行或逗号分隔），如
                         socks5://user:pass@host:port

邮件通知配置见 README.md；本地可使用同目录 .env，GitHub Actions 使用环境变量。

模式判定：
  - 单用户：AGENTROUTER_USERNAME 和 AGENTROUTER_PASSWORD 同时存在
  - 多用户：缺少 USERNAME/PASSWORD 任一或两者，且有 AGENTROUTER_ACCOUNTS
"""

import os
import re
import sys
import time
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 某些精简版 Python 运行时不会自动把脚本目录加入 sys.path。
# 显式加入后，无论从哪个工作目录启动，都能导入同目录的 notify.py。
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import requests
from dotenv import load_dotenv

# 本地运行时自动读取 checkin.py 同目录的 .env；系统/GitHub Actions 环境变量优先。
load_dotenv(dotenv_path=SCRIPT_DIR / ".env", override=False)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("AGENTROUTER_BASE_URL") or "https://agentrouter.org"
USERNAME = os.getenv("AGENTROUTER_USERNAME") or ""
PASSWORD = os.getenv("AGENTROUTER_PASSWORD") or ""
ACCOUNTS = os.getenv("AGENTROUTER_ACCOUNTS") or ""
PROXY_ENV = os.getenv("SOCKS5_PROXY") or ""

# New-API 配额 → 美元换算：1 USD = 500000 quota
QUOTA_PER_UNIT = 500000
BJT = timezone(timedelta(hours=8))

class BJTFormatter(logging.Formatter):
    """日志时间固定为北京时间（UTC+8）"""
    @staticmethod
    def converter(secs):
        return time.gmtime(secs + 8 * 3600)

_bjt_handler = logging.StreamHandler()
_bjt_handler.setFormatter(
    BJTFormatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
logging.basicConfig(level=logging.INFO, handlers=[_bjt_handler])
log = logging.getLogger("checkin")

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def mask(name: str) -> str:
    """用户名/邮箱脱敏：显示前 4 位 + *****"""
    if not name:
        return "*****"
    return (name[:4] + "*****") if len(name) > 4 else (name + "*****")

def parse_accounts(raw: str) -> list:
    """解析 AGENTROUTER_ACCOUNTS（换行或逗号分隔 user:pass），返回 [(username, password), ...]"""
    accounts = []
    for item in re.split(r"[\n,]+", raw or ""):
        entry = item.strip()
        if not entry:
            continue
        if ":" not in entry:
            log.warning("非法账号条目（缺少冒号分隔符）: %s", mask(entry))
            continue
        username, password = entry.split(":", 1)
        username = username.strip()
        password = password.strip()
        if not username:
            log.warning("非法账号条目（用户名为空）")
            continue
        accounts.append((username, password))
    return accounts

def detect_mode(username: str, password: str, account: str) -> str:
    """判定运行模式: single=单用户 / multi=多用户 / none=未配置账号"""
    if username and password:
        return "single"
    if account:
        return "multi"
    return "none"

def quota_to_usd(quota: int) -> float:
    return (quota or 0) / QUOTA_PER_UNIT

def bjt_date_str() -> str:
    now = datetime.now(BJT)
    return f"{now.year}年{now.month:02d}月{now.day:02d}日"

def parse_proxies(raw: str) -> list:
    """解析代理配置（换行或逗号分隔），socks/socks5 统一转 socks5h（DNS 也走代理）"""
    proxies = []
    for item in re.split(r"[\n,]+", raw):
        url = item.strip()
        if not url:
            continue
        if url.startswith("socks5://"):
            url = "socks5h://" + url[len("socks5://"):]
        elif url.startswith("socks://"):
            url = "socks5h://" + url[len("socks://"):]
        proxies.append(url)
    return proxies

def get_json(resp: requests.Response):
    """解析 JSON；被 WAF 拦截或非 JSON 时返回 None"""
    try:
        return resp.json()
    except ValueError:
        if "aliyun_waf" in resp.text:
            log.warning("响应被阿里云 WAF 拦截（当前 IP/代理不可用）")
        return None

# ---------------------------------------------------------------------------
# 会话与 API
# ---------------------------------------------------------------------------

def create_session(proxy_url: str = "") -> requests.Session:
    """创建仿浏览器 Session（可选代理）"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/125.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Referer": f"{BASE_URL}/login",
        "Origin": BASE_URL,
    })
    if proxy_url:
        s.proxies.update({"http": proxy_url, "https": proxy_url})
    return s

def find_working_proxy() -> str:
    """逐个尝试代理 + 直连，返回第一个能绕过 WAF 的代理 URL；全部失败返回 None"""
    proxies = parse_proxies(PROXY_ENV)
    attempts = [(p, p.split("@")[-1]) for p in proxies] + [("", "直连（无代理）")]
    for proxy_url, label in attempts:
        log.info("尝试连接方式: %s", label)
        s = create_session(proxy_url)
        try:
            data = get_json(s.get(f"{BASE_URL}/api/status", timeout=25))
            if data and data.get("success"):
                log.info("✅ 连接可用：%s（已绕过 WAF）", label)
                return proxy_url
        except Exception as e:
            log.warning("连接 [%s] 异常: %s", label, e)
        log.warning("❌ 连接 [%s] 不可用，尝试下一个", label)
    return None

def build_working_session():
    """返回第一个能绕过 WAF 的 session；全部失败返回 None（单用户模式使用）"""
    proxy_url = find_working_proxy()
    if proxy_url is None:
        return None
    return create_session(proxy_url)

def do_login(session: requests.Session, username: str, password: str) -> tuple:
    """登录（= 触发签到）。成功返回 (user_data, "")；失败返回 ({}, 错误信息)"""
    payload = {"username": username, "password": password}
    try:
        data = get_json(session.post(f"{BASE_URL}/api/user/login", json=payload, timeout=25))
        if not data:
            return {}, "响应解析失败（可能被 WAF 拦截）"
        if data.get("success"):
            log.info("登录成功: %s", mask(username))
            return data.get("data", {}), ""
        msg = data.get("message", "未知错误")
        log.error("登录失败: %s", msg)
        return {}, msg
    except requests.RequestException as e:
        log.error("登录请求异常: %s", e)
        return {}, str(e)

def get_quota(session: requests.Session, access_token: str, user_id) -> int:
    """用登录得到的 access_token 查询最新余额 quota"""
    try:
        headers = {"Authorization": access_token, "New-API-User": str(user_id)}
        data = get_json(session.get(f"{BASE_URL}/api/user/self", headers=headers, timeout=25))
        if data and data.get("success"):
            quota = data.get("data", {}).get("quota")
            if isinstance(quota, (int, float)):
                return quota
    except requests.RequestException as e:
        log.error("查询余额异常: %s", e)
        raise RuntimeError("查询余额请求失败") from None
    raise RuntimeError("查询余额失败或响应缺少 quota")

def do_checkin_for_account(session: requests.Session, username: str, password: str) -> dict:
    """单个账号登录（触发签到）+ 查余额，返回结果 dict 供汇总通知使用"""
    user, err = do_login(session, username, password)
    result = {
        "display": mask(username),
        "checked_in": False,
        "balance_usd": 0.0,
        "error": err,
    }
    if not user:
        result["error"] = err or "登录响应缺少用户信息"
        return result
    result["checked_in"] = bool(user.get("checked_in"))
    try:
        quota = get_quota(session, user.get("access_token", ""), user.get("id", ""))
        result["balance_usd"] = round(quota_to_usd(quota), 2)
    except RuntimeError as error:
        result["error"] = f"登录已成功，但{error}"
    return result

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_single_mode():
    """单用户签到（原逻辑不变）"""
    log.info("签到用户: %s", mask(USERNAME))

    # 1. 选出能绕过 WAF 的连接
    session = build_working_session()
    if session is None:
        log.error("所有连接方式均无法绕过 WAF，请检查 SOCKS5_PROXY，脚本退出")
        sys.exit(1)

    # 2. 登录触发签到
    log.info("登录中（登录即触发每日签到）...")
    user, _ = do_login(session, USERNAME, PASSWORD)
    if not user:
        log.error("登录失败，无法签到，脚本退出")
        sys.exit(1)

    new_checkin = bool(user.get("checked_in"))  # True=本次触发了新签到
    if new_checkin:
        log.info("🎉 签到成功，新增额度已到账")
    else:
        log.info("✅ 今日已签到")

    # 3. 查询最新余额（登录响应中的 quota 可能尚未刷新）
    quota = get_quota(session, user.get("access_token", ""), user.get("id", ""))
    balance_usd = round(quota_to_usd(quota), 2)
    log.info("当前余额: $%.2f", balance_usd)

    # 4. 发送邮件通知
    notify_data = {
        "username": mask(user.get("username") or USERNAME),
        "date": bjt_date_str(),
        "checked_in": not new_checkin,  # notify: True=今日已签到, False=新签到
        "balance_usd": balance_usd,
    }
    from notify import send_email_notification
    if not send_email_notification(notify_data):
        raise RuntimeError("签到已完成，但结果邮件未能发送")

def run_multi_mode():
    """多用户签到：共享一个可用代理，每账号独立 session，聚合后发一条汇总通知"""
    accounts = parse_accounts(ACCOUNTS)
    if not accounts:
        log.error("AGENTROUTER_ACCOUNTS 解析后无有效账号，脚本退出")
        sys.exit(1)
    log.info("多用户模式，共 %d 个账号", len(accounts))

    # 1. 选出一个能绕过 WAF 的代理（所有账号共用）
    proxy_url = find_working_proxy()
    if proxy_url is None:
        log.error("所有连接方式均无法绕过 WAF，请检查 SOCKS5_PROXY，脚本退出")
        sys.exit(1)

    # 2. 逐账号签到（任一失败不中断，继续下一个）
    results = []
    for username, password in accounts:
        log.info("签到中: %s", mask(username))
        try:
            with create_session(proxy_url) as session:  # 独立 session，避免 cookie 串扰
                result = do_checkin_for_account(session, username, password)
        except Exception as error:
            result = {"display": mask(username), "checked_in": False,
                      "balance_usd": 0.0, "error": f"账号执行异常（{type(error).__name__}）"}
        results.append(result)
        if result["error"]:
            log.warning("❌ %s 执行失败: %s", mask(username), result["error"])
        elif result["checked_in"]:
            log.info("🎉 %s 签到成功，余额 $%.2f", mask(username), result["balance_usd"])
        else:
            log.info("✅ %s 今日已签到，余额 $%.2f", mask(username), result["balance_usd"])

    # 3. 发送汇总邮件通知
    from notify import send_combined_email_notification
    if not send_combined_email_notification(results):
        raise RuntimeError("账号执行完毕，但汇总邮件未能发送")
    if any(result.get("error") for result in results):
        # Only suppress fallback mail once the failure summary has been delivered.
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as output:
                output.write("failure_notified=true\n")
        sys.exit(1)

def main():
    log.info("=" * 48)
    log.info("AgentRouter 每日签到脚本启动")

    mode = detect_mode(USERNAME, PASSWORD, ACCOUNTS)
    if mode == "none":
        log.error("未配置账号信息：需 AGENTROUTER_USERNAME+AGENTROUTER_PASSWORD（单用户）"
                  "或 AGENTROUTER_ACCOUNTS（多用户），脚本退出")
        sys.exit(1)

    if mode == "single":
        run_single_mode()
    else:
        run_multi_mode()

    log.info("签到流程完成")
    log.info("=" * 48)

if __name__ == "__main__":
    main()

