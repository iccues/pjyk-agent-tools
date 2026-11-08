import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pjyk_admin.client import AdminApiClient


class ProxyRoutingTests(unittest.TestCase):
    @patch("urllib.request.proxy_bypass", return_value=False)
    @patch("urllib.request.getproxies", return_value={"http": "http://proxy.example:8081"})
    def test_only_loopback_skips_configured_proxy(self, _proxies, _bypass):
        # Stop at the HTTP transport to inspect routing without opening a socket.
        with patch("urllib.request.HTTPHandler.http_open", autospec=True) as transport:
            transport.return_value.code = 200
            for host, expected in (
                ("localhost", "localhost:8080"),
                ("LOCALHOST.", "LOCALHOST.:8080"),
                ("127.0.0.2", "127.0.0.2:8080"),
                ("[::1]", "[::1]:8080"),
                ("localhost.example", "proxy.example:8081"),
                ("192.0.2.1", "proxy.example:8081"),
            ):
                with self.subTest(host=host):
                    client = AdminApiClient(base_url=f"http://{host}:8080", token="")
                    transport.return_value.__enter__.return_value.read.return_value = b"[]"
                    client.list_animes()
                    request = transport.call_args.args[1]
                    self.assertIsInstance(request, Request)
                    self.assertEqual(request.host, expected)
