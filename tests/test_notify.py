import os
import sys
import unittest
from pathlib import Path
from email.message import EmailMessage
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import notify


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.events = []
        self.message = None
        self.from_addr = None
        self.to_addrs = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def ehlo(self):
        self.events.append("ehlo")

    def starttls(self, context=None):
        self.events.append("starttls")
        self.context = context

    def login(self, username, password):
        self.events.append(("login", username, password))

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.events.append("send_message")
        self.message = message
        self.from_addr = from_addr
        self.to_addrs = to_addrs


class NotifyTests(unittest.TestCase):
    def setUp(self):
        FakeSMTP.instances.clear()

    def test_parse_recipients_supports_multiple_separators(self):
        recipients = notify._parse_recipients(
            "Alice <alice@example.com>; bob@example.com\nCarol <carol@example.com>"
        )
        self.assertEqual(
            recipients,
            [
                ("Alice", "alice@example.com"),
                ("", "bob@example.com"),
                ("Carol", "carol@example.com"),
            ],
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_required_config_skips_notification(self):
        self.assertFalse(
            notify.send_email_notification(
                {
                    "username": "user*****",
                    "date": "2026年08月27日",
                    "checked_in": True,
                    "balance_usd": 1.5,
                }
            )
        )

    @patch("notify.smtplib.SMTP_SSL", FakeSMTP)
    @patch.dict(
        os.environ,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "465",
            "SMTP_SECURITY": "ssl",
            "SMTP_USERNAME": "sender@example.com",
            "SMTP_PASSWORD": "secret",
            "EMAIL_FROM": "sender@example.com",
            "EMAIL_FROM_NAME": "AgentRouter Bot",
            "EMAIL_TO": "Alice <alice@example.com>;bob@example.com",
        },
        clear=True,
    )
    def test_single_notification_sends_multipart_email(self):
        sent = notify.send_email_notification(
            {
                "username": "user*****",
                "date": "2026年08月27日",
                "checked_in": False,
                "balance_usd": 12.34,
            }
        )

        self.assertTrue(sent)
        smtp = FakeSMTP.instances[-1]
        self.assertEqual((smtp.host, smtp.port), ("smtp.example.com", 465))
        self.assertIn(("login", "sender@example.com", "secret"), smtp.events)
        self.assertEqual(smtp.to_addrs, ["alice@example.com", "bob@example.com"])
        self.assertIsInstance(smtp.message, EmailMessage)
        self.assertEqual(smtp.message["From"], "AgentRouter Bot <sender@example.com>")
        self.assertIn("2026年08月27日", smtp.message["Subject"])
        self.assertTrue(smtp.message.is_multipart())

    @patch("notify.smtplib.SMTP", FakeSMTP)
    @patch.dict(
        os.environ,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_SECURITY": "starttls",
            "EMAIL_FROM": "sender@example.com",
            "EMAIL_TO": "receiver@example.com",
        },
        clear=True,
    )
    def test_starttls_uses_default_port_without_authentication(self):
        sent = notify.send_combined_email_notification(
            [
                {
                    "display": "user*****",
                    "checked_in": True,
                    "balance_usd": 8.0,
                    "error": "",
                },
                {
                    "display": "bad*****",
                    "checked_in": False,
                    "balance_usd": 0.0,
                    "error": "用户名或密码错误",
                },
            ]
        )

        self.assertTrue(sent)
        smtp = FakeSMTP.instances[-1]
        self.assertEqual(smtp.port, 587)
        self.assertEqual(smtp.events[:3], ["ehlo", "starttls", "ehlo"])
        self.assertNotIn("login", [event[0] if isinstance(event, tuple) else event for event in smtp.events])
        self.assertIn("2 个账号", smtp.message["Subject"])


if __name__ == "__main__":
    unittest.main()
