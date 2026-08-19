import tempfile
import threading
import unittest
from pathlib import Path

from dusk import ipc
from tests import util  # noqa: F401


class IpcTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sock = Path(self.tmp.name) / "control.sock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_status_and_reload_round_trip(self):
        server = ipc.ControlServer(self.sock)

        def handler(request):
            if request.get("cmd") == "status":
                return {"ok": True, "state": {"mode": "solar"}}
            if request.get("cmd") == "reload":
                return {"ok": True}
            return {"ok": False, "error": "unknown"}

        stop = threading.Event()

        def serve():
            while not stop.is_set():
                server.poll(0.2, handler)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        client = ipc.ControlClient(self.sock)

        status = client.request("status")
        self.assertTrue(status["ok"])
        self.assertEqual(status["state"]["mode"], "solar")

        reload = client.request("reload")
        self.assertTrue(reload["ok"])

        unknown = client.request("bogus")
        self.assertFalse(unknown["ok"])

        stop.set()
        thread.join(timeout=2)
        server.close()

    def test_client_fails_when_no_server(self):
        client = ipc.ControlClient(Path(self.tmp.name) / "missing.sock")
        with self.assertRaises(ipc.ControlError):
            client.request("status")


if __name__ == "__main__":
    unittest.main()