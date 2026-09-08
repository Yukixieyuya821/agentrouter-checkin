"""Run check-in with optional embedded nodes from a gzip + base64 Mihomo config."""

import base64
import gzip
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
FIRST_PORT = 17890


def build_config(encoded):
    import yaml

    try:
        raw = gzip.decompress(base64.b64decode(encoded.strip(), validate=True))
        source = yaml.safe_load(raw)
    except Exception:
        # Parser errors can contain the original node passwords.
        raise ValueError("MIHOMO_CONFIG_B64 must contain gzip + base64 encoded YAML") from None
    nodes = source.get("proxies") if isinstance(source, dict) else None
    if not isinstance(nodes, list) or not nodes or len(nodes) > 500:
        raise ValueError("Config must contain 1 to 500 embedded proxies")
    names = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            raise ValueError("Each proxy must have a name")
        if not node["name"] or node["name"] in names:
            raise ValueError("Proxy names must be nonempty and unique")
        if node.get("dialer-proxy"):
            raise ValueError("Chained proxies are not supported by this runner")
        names.append(node["name"])
    # Each local port goes directly to one node. Desktop rules, DNS listeners,
    # dashboards and subscription refresh URLs are unnecessary on the runner.
    listeners = [
        {"name": f"checkin-{i}", "type": "mixed", "listen": "127.0.0.1",
         "port": FIRST_PORT + i, "proxy": name, "udp": False}
        for i, name in enumerate(names)
    ]
    config = {
        "log-level": "silent", "ipv6": False, "allow-lan": False,
        "mode": "rule", "proxies": nodes, "listeners": listeners,
        "rules": ["MATCH,REJECT"],
    }
    # Preserve host aliases used by some node configurations.
    if "hosts" in source:
        config["hosts"] = source["hosts"]
    urls = [f"http://127.0.0.1:{item['port']}" for item in listeners]
    return config, urls


def wait_ready(process, ports, timeout=30):
    deadline = time.monotonic() + timeout
    pending = set(ports)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Mihomo exited before becoming ready; check node compatibility")
        for port in list(pending):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    pending.remove(port)
            except OSError:
                pass
        if not pending:
            return
        time.sleep(0.2)
    raise RuntimeError("Mihomo listeners did not become ready within 30 seconds")


def main():
    encoded = os.environ.get("MIHOMO_CONFIG_B64", "").strip()
    command = [sys.executable, str(ROOT / "checkin.py")]
    if not encoded:
        return subprocess.call(command)
    config, urls = build_config(encoded)
    child_env = os.environ.copy()
    child_env.pop("MIHOMO_CONFIG_B64", None)
    # Configured nodes take precedence over the standalone proxy setting.
    child_env["SOCKS5_PROXY"] = ",".join(urls)
    binary = os.environ.get("MIHOMO_BINARY", "mihomo")
    with tempfile.TemporaryDirectory(prefix="checkin-mihomo-") as temp:
        path = Path(temp) / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
        # Keep core output private: it may expose server addresses or passwords.
        process = subprocess.Popen(
            [binary, "-d", temp, "-f", str(path)], env=child_env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            wait_ready(process, [item["port"] for item in config["listeners"]])
            print(f"Mihomo ready: {len(urls)} nodes; checking connectivity in file order", flush=True)
            return subprocess.call(command, env=child_env)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as error:
        print(f"Proxy setup failed: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("Proxy setup failed; verify Mihomo installation and config", file=sys.stderr)
        sys.exit(1)
