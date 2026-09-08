import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import notify
from scripts import notify_failure

# Tests never load local account or SMTP credentials.
with patch("dotenv.load_dotenv"):
    import checkin


class FailureNotificationTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "FAILED_STEP_RESULTS": '{"dependencies":"failure","checkin":"skipped"}',
        "GITHUB_REPOSITORY": "owner/repo", "GITHUB_RUN_ID": "123",
        "GITHUB_SERVER_URL": "https://github.com", "GITHUB_RUN_ATTEMPT": "2",
    }, clear=True)
    @patch.object(notify_failure, "send_failure_notification", return_value=True)
    def test_dependency_failure_sends_step_and_run_link(self, send):
        self.assertEqual(notify_failure.main(), 0)
        data = send.call_args.args[0]
        self.assertEqual(data["failed_steps"], "安装依赖")
        self.assertEqual(data["run_url"], "https://github.com/owner/repo/actions/runs/123")
        self.assertEqual(data["attempt"], "2")

    @patch.dict(os.environ, {"FAILED_STEP_RESULTS": "invalid"}, clear=True)
    @patch.object(notify_failure.time, "sleep")
    @patch.object(notify_failure, "send_failure_notification", side_effect=[False, True])
    def test_missing_step_outputs_still_notifies_and_retries(self, send, sleep):
        self.assertEqual(notify_failure.main(), 0)
        self.assertEqual(send.call_count, 2)
        self.assertIn("未取得具体步骤", send.call_args.args[0]["failed_steps"])
        sleep.assert_called_once_with(5)

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(notify_failure.time, "sleep")
    @patch.object(notify_failure, "send_failure_notification",
                  side_effect=RuntimeError("private-password"))
    def test_notification_failure_is_nonzero_and_does_not_leak_exception(self, send, sleep):
        with self.assertLogs(level="WARNING") as logs:
            self.assertEqual(notify_failure.main(), 1)
        self.assertEqual(send.call_count, 3)
        self.assertNotIn("private-password", " ".join(logs.output))

    @patch.dict(os.environ, {"FAILURE_ALREADY_NOTIFIED": "true"}, clear=True)
    @patch.object(notify_failure, "send_failure_notification", return_value=True)
    def test_dedup_only_for_reported_account_failures(self, send):
        os.environ["FAILED_STEP_RESULTS"] = json.dumps({"checkin": "failure"})
        self.assertEqual(notify_failure.main(), 0)
        send.assert_not_called()
        os.environ["FAILED_STEP_RESULTS"] = json.dumps({"dependencies": "failure"})
        self.assertEqual(notify_failure.main(), 0)
        send.assert_called_once()

    @patch.object(notify, "_send_email", return_value=True)
    def test_failure_email_contains_context_and_escapes_html(self, send):
        notify.send_failure_notification({
            "repository": "owner/repo", "workflow": "<example>",
            "failed_steps": "安装依赖", "run_url": "https://github.com/owner/repo/actions/runs/123",
        })
        subject, text, html = send.call_args.args
        self.assertIn("执行失败通知", subject)
        self.assertIn("安装依赖", text)
        self.assertIn("actions/runs/123", html)
        self.assertIn('<a href="https://github.com/owner/repo/actions/runs/123">', html)
        self.assertIn("&lt;example&gt;", html)
        self.assertNotIn("<example>", html)


class CheckinFailureTests(unittest.TestCase):
    def test_failed_balance_query_never_becomes_zero_balance(self):
        session = MagicMock()
        for response in ({"success": False}, {"success": True, "data": {}}):
            session.get.return_value.json.return_value = response
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                checkin.get_quota(session, "token", 1)
        session.get.side_effect = checkin.requests.ConnectionError("offline")
        with self.assertRaises(RuntimeError):
            checkin.get_quota(session, "token", 1)

    @patch.object(checkin, "get_quota", side_effect=RuntimeError("查询余额失败"))
    @patch.object(checkin, "do_login", return_value=({"id": 1, "checked_in": True}, ""))
    def test_account_balance_failure_preserves_successful_login(self, login, quota):
        result = checkin.do_checkin_for_account(MagicMock(), "user", "password")
        self.assertTrue(result["checked_in"])
        self.assertIn("登录已成功，但查询余额失败", result["error"])

    @patch.object(checkin, "ACCOUNTS", "one:pass,two:pass")
    @patch.object(checkin, "find_working_proxy", return_value="")
    @patch.object(checkin, "create_session")
    @patch.object(checkin, "do_checkin_for_account", side_effect=[
        RuntimeError("private detail"),
        {"display": "two", "checked_in": True, "balance_usd": 5, "error": ""},
    ])
    @patch.object(notify, "send_combined_email_notification", return_value=True)
    def test_multi_continues_after_error_then_marks_failure_as_notified(self, send, account, session, proxy):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                with self.assertRaises(SystemExit) as raised:
                    checkin.run_multi_mode()
            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(output.read_text().strip(), "failure_notified=true")
        results = send.call_args.args[0]
        self.assertEqual(len(results), 2)
        self.assertIn("RuntimeError", results[0]["error"])
        self.assertNotIn("private detail", results[0]["error"])
        self.assertTrue(results[1]["checked_in"])

    @patch.object(checkin, "ACCOUNTS", "one:pass")
    @patch.object(checkin, "find_working_proxy", return_value="")
    @patch.object(checkin, "create_session")
    @patch.object(checkin, "do_checkin_for_account", return_value={
        "display": "one", "checked_in": False, "balance_usd": 0, "error": "登录失败",
    })
    @patch.object(notify, "send_combined_email_notification", return_value=False)
    def test_failed_summary_delivery_does_not_suppress_fallback(self, send, account, session, proxy):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
                with self.assertRaises(RuntimeError):
                    checkin.run_multi_mode()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
