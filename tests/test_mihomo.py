import base64
import gzip
import json
import unittest
from unittest.mock import MagicMock, patch

from scripts.run_with_mihomo import build_config, main, wait_ready


def encode(value):
    return base64.b64encode(gzip.compress(json.dumps(value).encode())).decode()


class MihomoTests(unittest.TestCase):
    def test_nodes_route_to_distinct_local_ports_without_desktop_rules(self):
        nodes = [{"name": "node-a", "type": "ss", "password": "private"},
                 {"name": "node-b", "type": "ss", "password": "private"}]
        config, urls = build_config(encode({
            "proxies": nodes, "external-controller": "0.0.0.0:9090",
            "rules": ["MATCH,DIRECT"], "dns": {"listen": "0.0.0.0:53"},
        }))
        self.assertEqual(config["proxies"], nodes)
        self.assertEqual([x["proxy"] for x in config["listeners"]], ["node-a", "node-b"])
        self.assertEqual(urls, ["http://127.0.0.1:17890", "http://127.0.0.1:17891"])
        self.assertTrue(all(x["listen"] == "127.0.0.1" for x in config["listeners"]))
        self.assertNotIn("external-controller", config)
        self.assertNotIn("dns", config)
        self.assertEqual(config["rules"], ["MATCH,REJECT"])

    def test_invalid_secret_does_not_leak_parser_input(self):
        encoded = base64.b64encode(gzip.compress(b"password: [private-secret")).decode()
        with self.assertRaises(ValueError) as raised:
            build_config(encoded)
        self.assertNotIn("private-secret", str(raised.exception))

    def test_rejects_empty_duplicate_or_chained_nodes(self):
        for nodes in ([], [{"name": "a"}, {"name": "a"}],
                      [{"name": "a", "dialer-proxy": "missing"}]):
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                build_config(encode({"proxies": nodes}))

    @patch.dict("os.environ", {}, clear=True)
    @patch("scripts.run_with_mihomo.subprocess.call", return_value=7)
    def test_no_secret_preserves_checkin_exit_code(self, call):
        self.assertEqual(main(), 7)
        self.assertTrue(call.call_args.args[0][-1].endswith("checkin.py"))

    def test_early_core_exit_fails_readiness(self):
        process = MagicMock()
        process.poll.return_value = 1
        with self.assertRaises(RuntimeError):
            wait_ready(process, [17890])

    @patch.dict("os.environ", {"MIHOMO_CONFIG_B64": encode({"proxies": [{"name": "a"}]})})
    @patch("scripts.run_with_mihomo.wait_ready")
    @patch("scripts.run_with_mihomo.subprocess.Popen")
    @patch("scripts.run_with_mihomo.subprocess.call", return_value=4)
    def test_child_gets_ports_and_core_is_stopped(self, call, popen, ready):
        process = popen.return_value
        process.poll.return_value = None
        self.assertEqual(main(), 4)
        child_env = call.call_args.kwargs["env"]
        self.assertEqual(child_env["SOCKS5_PROXY"], "http://127.0.0.1:17890")
        self.assertNotIn("MIHOMO_CONFIG_B64", child_env)
        process.terminate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
