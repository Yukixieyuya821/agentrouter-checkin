import json
import unittest
from unittest.mock import patch

with patch("dotenv.load_dotenv"):
    import checkin


def response(data=None, waf=False):
    result = checkin.requests.Response()
    result.status_code = 403 if waf else 200
    result._content = (b"<html>aliyun_waf</html>" if waf
                       else json.dumps(data).encode())
    return result


class QuotaRetryTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [f"http://127.0.0.1:{17890 + i}" for i in range(8)]
        self.env = patch.object(checkin, "PROXY_ENV", ",".join(self.nodes))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.session = checkin.create_session(self.nodes[0])
        self.addCleanup(self.session.close)
        self.session.cookies.set("session", "private-cookie")

    def test_balance_waf_switches_proxy_without_repeating_login(self):
        routes = []

        def get(url, **kwargs):
            routes.append(dict(self.session.proxies))
            self.assertEqual(self.session.cookies.get("session"), "private-cookie")
            self.assertEqual(kwargs["headers"]["Authorization"], "private-token")
            return (response(waf=True) if len(routes) == 1 else
                    response({"success": True, "data": {"quota": 1500000}}))

        with patch.object(self.session, "get", side_effect=get), patch.object(
            checkin, "do_login", return_value=({
                "id": 1, "access_token": "private-token", "checked_in": True,
            }, "")
        ) as login, self.assertLogs("checkin", level="INFO") as logs:
            result = checkin.do_checkin_for_account(self.session, "user", "password")
        login.assert_called_once()
        self.assertTrue(result["checked_in"])
        self.assertEqual(result["balance_usd"], 3)
        self.assertEqual(result["error"], "")
        self.assertEqual([route["https"] for route in routes], self.nodes[:2])
        self.assertFalse(self.session.trust_env)
        self.assertNotIn("private-token", " ".join(logs.output))

    def test_network_failure_can_recover(self):
        with patch.object(self.session, "get", side_effect=[
            checkin.requests.ConnectionError("private-node-password"),
            response({"success": True, "data": {"quota": 0}}),
        ]) as get, self.assertLogs("checkin", level="INFO") as logs:
            self.assertEqual(checkin.get_quota(self.session, "token", 1), 0)
        self.assertEqual(get.call_count, 2)
        self.assertNotIn("private-node-password", " ".join(logs.output))

    def test_exhaustion_is_bounded_and_preserves_checkin(self):
        with patch.object(self.session, "get", return_value=response(waf=True)) as get, patch.object(
            checkin, "do_login", return_value=({"id": 1, "checked_in": True}, "")
        ) as login:
            result = checkin.do_checkin_for_account(self.session, "user", "password")
        self.assertEqual(get.call_count, 5)
        login.assert_called_once()
        self.assertTrue(result["checked_in"])
        self.assertIn("登录已成功", result["error"])
        self.assertIn("已尝试 5 个连接", result["error"])

    def test_business_error_or_missing_quota_does_not_rotate(self):
        for data in ({"success": False, "message": "unauthorized"},
                     {"success": True, "data": {}}):
            with self.subTest(data=data), patch.object(
                self.session, "get", return_value=response(data)
            ) as get, self.assertRaises(RuntimeError):
                checkin.get_quota(self.session, "token", 1)
            get.assert_called_once()

    def test_direct_fallback_clears_proxy_and_ignores_environment(self):
        routes = []

        def get(*args, **kwargs):
            routes.append(dict(self.session.proxies))
            return (response(waf=True) if len(routes) == 1 else
                    response({"success": True, "data": {"quota": 1}}))

        with patch.object(checkin, "PROXY_ENV", self.nodes[0]), patch.object(
            self.session, "get", side_effect=get
        ):
            self.assertEqual(checkin.get_quota(self.session, "token", 1), 1)
        self.assertEqual(len(routes), 2)
        self.assertEqual(routes[-1], {})
        self.assertFalse(self.session.trust_env)

    def test_status_check_does_not_claim_all_endpoints_are_accessible(self):
        with patch.object(checkin, "create_session", return_value=self.session), patch.object(
            self.session, "get", return_value=response({"success": True})
        ), patch.object(self.session, "close") as close, self.assertLogs("checkin") as logs:
            self.assertEqual(checkin.find_working_proxy(), self.nodes[0])
        close.assert_called_once()
        self.assertIn("登录和余额接口仍需验证", " ".join(logs.output))
        self.assertNotIn("已绕过 WAF", " ".join(logs.output))

    def test_single_mode_sends_success_after_balance_retry(self):
        with patch.object(checkin, "build_working_session", return_value=self.session), patch.object(
            checkin, "do_login", return_value=({"id": 1, "checked_in": True}, "")
        ) as login, patch.object(self.session, "get", side_effect=[
            response(waf=True), response({"success": True, "data": {"quota": 1000000}}),
        ]), patch("notify.send_email_notification", return_value=True) as send:
            checkin.run_single_mode()
        login.assert_called_once()
        self.assertEqual(send.call_args.args[0]["balance_usd"], 2)
        self.assertFalse(send.call_args.args[0]["checked_in"])

    def test_multi_mode_reuses_working_proxy_with_independent_cookies(self):
        second = checkin.create_session(self.nodes[1])
        self.addCleanup(second.close)
        with patch.object(checkin, "ACCOUNTS", "first:pass,second:pass"), patch.object(
            checkin, "find_working_proxy", return_value=self.nodes[0]
        ), patch.object(checkin, "create_session", side_effect=[self.session, second]) as create, patch.object(
            checkin, "do_login", return_value=({"id": 1, "checked_in": True}, "")
        ) as login, patch.object(self.session, "get", side_effect=[
            response(waf=True), response({"success": True, "data": {"quota": 1000000}}),
        ]), patch.object(second, "get", return_value=response({
            "success": True, "data": {"quota": 2000000},
        })), patch("notify.send_combined_email_notification", return_value=True) as send:
            checkin.run_multi_mode()
        self.assertEqual([call.args[0] for call in create.call_args_list], self.nodes[:2])
        self.assertEqual(login.call_count, 2)
        self.assertIsNone(second.cookies.get("session"))
        self.assertEqual([r["balance_usd"] for r in send.call_args.args[0]], [2, 4])


if __name__ == "__main__":
    unittest.main()
