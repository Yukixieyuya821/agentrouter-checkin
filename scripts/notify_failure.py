"""Failure notification entry point: Python standard library only."""

import json
import logging
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from notify import send_failure_notification


STEP_NAMES = {
    "checkout": "检出代码",
    "setup_python": "设置 Python",
    "dependencies": "安装依赖",
    "mihomo": "安装 Mihomo 代理内核",
    "checkin": "启动代理、签到或发送结果邮件",
}


def load_step_results():
    try:
        results = json.loads(os.getenv("FAILED_STEP_RESULTS") or "{}")
        return results if isinstance(results, dict) else {}
    except ValueError:
        return {}


def main():
    results = load_step_results()
    failed = [key for key in STEP_NAMES if results.get(key) == "failure"]
    if os.getenv("FAILURE_ALREADY_NOTIFIED") == "true" and failed == ["checkin"]:
        logging.info("账号失败已通过汇总邮件通知，跳过重复通知")
        return 0
    repository = os.getenv("GITHUB_REPOSITORY", "")
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    data = {
        "repository": repository,
        "workflow": os.getenv("GITHUB_WORKFLOW", "AgentRouter 每日签到"),
        "failed_steps": "、".join(STEP_NAMES[key] for key in failed)
                        or "作业失败或超时，未取得具体步骤，请查看运行日志",
        "attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
        "run_url": f"{server}/{repository}/actions/runs/{run_id}",
    }
    for attempt in range(1, 4):
        try:
            if send_failure_notification(data):
                return 0
        except Exception as error:
            # Do not put credentials or raw exception contents in workflow logs.
            logging.error("失败通知发送异常：%s", type(error).__name__)
        logging.warning("失败通知第 %d 次发送未成功", attempt)
        if attempt < 3:
            time.sleep(5)
    logging.error("失败通知未能送达，请检查 SMTP 配置和服务可用性")
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
