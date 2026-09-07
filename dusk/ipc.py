"""Unix-socket control plane between the CLI/widget and the daemon.

Line-delimited JSON. The daemon binds the socket; the CLI and bar widget send
`{"cmd": "status"}` or `{"cmd": "reload"}` and read one response line.
"""

from __future__ import annotations

import json
import selectors
import socket
from pathlib import Path
from typing import Any


class ControlError(Exception):
    pass


class ControlServer:
    def __init__(self, sock_path: Path, wake_fd: int | None = None) -> None:
        self.sock_path = Path(sock_path)
        self.sock_path.parent.mkdir(parents=True, exist_ok=True)
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock_path.unlink()
        except OSError:
            pass
        self._listener.bind(str(self.sock_path))
        self._listener.listen(8)
        self._listener.settimeout(None)
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._listener, selectors.EVENT_READ, data="listen")
        if wake_fd is not None:
            self._selector.register(wake_fd, selectors.EVENT_READ, data="wake")

    def register_wake(self, fd: int) -> None:
        """Register a pipe fd that wakes the poll loop (used for signals)."""
        self._selector.register(fd, selectors.EVENT_READ, data="wake")

    def close(self) -> None:
        try:
            self._selector.close()
        except (OSError, ValueError):
            pass
        try:
            self._listener.close()
        except OSError:
            pass
        try:
            self.sock_path.unlink()
        except OSError:
            pass

    def poll(
        self,
        timeout: float | None,
        handler: Any = None,
    ) -> list[dict[str, Any]]:
        """Wait up to `timeout` seconds; handle any client requests.

        `handler` is an optional callable `request -> response dict` (or None
        for no reply). Returns the list of handled requests, including a
        synthetic `{"cmd": "__signal"}` entry when the wake pipe fired.

        Contract: poll returns after the FIRST ready round of events or at
        the timeout, whichever comes first — it never keeps waiting just
        because events arrived. The scheduler relies on this prompt return for
        timeout and signal wakes; request handlers may complete work before
        replying. Do not loop internally until the deadline.
        """
        handled: list[dict[str, Any]] = []
        deadline = None
        if timeout is not None and timeout > 0:
            deadline = _now_monotonic() + timeout
        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - _now_monotonic()
                if remaining <= 0:
                    break
            try:
                events = self._selector.select(remaining)
            except InterruptedError:
                # A signal interrupted the wait; report it so the caller
                # re-evaluates.
                handled.append({"cmd": "__signal"})
                break
            if not events:
                break
            for _key, _mask in events:
                if _key.data == "wake":
                    _drain_wake(_key.fileobj)
                    handled.append({"cmd": "__signal"})
                elif _key.data == "listen":
                    conn, _addr = self._listener.accept()
                    conn.settimeout(5.0)
                    request = self._read_request(conn)
                    if request is not None:
                        handled.append(request)
                        if handler is not None:
                            response = handler(request)
                            if response is not None:
                                self.respond(conn, response)
                    conn.close()
            # Return after the first ready round so the pump can establish a
            # fresh wait instead of waiting out the previous transition sleep.
            break
        return handled

    @staticmethod
    def _read_request(conn: socket.socket) -> dict[str, Any] | None:
        try:
            line = conn.makefile("r", encoding="utf-8").readline()
        except (OSError, ValueError):
            return None
        line = (line or "").strip()
        if not line:
            return None
        try:
            request = json.loads(line)
        except ValueError:
            request = {}
        return request if isinstance(request, dict) else {}

    def respond(self, conn: socket.socket, payload: dict[str, Any]) -> None:
        try:
            data = (json.dumps(payload) + "\n").encode("utf-8")
            conn.sendall(data)
        except OSError:
            pass


def _drain_wake(fd: int) -> None:
    import os

    try:
        while os.read(fd, 4096):
            pass
    except (OSError, BlockingIOError):
        pass


def _now_monotonic() -> float:
    import time

    return time.monotonic()


class ControlClient:
    def __init__(self, sock_path: Path, timeout: float = 3.0) -> None:
        self.sock_path = Path(sock_path)
        self.timeout = timeout

    def request(self, cmd: str, **kwargs: Any) -> dict[str, Any]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(self.sock_path))
            payload = {"cmd": cmd, **kwargs}
            sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            line = sock.makefile("r", encoding="utf-8").readline()
        except (TimeoutError, OSError, ValueError) as exc:
            raise ControlError(f"cannot reach dusk scheduler at {self.sock_path}: {exc}") from exc
        finally:
            sock.close()
        if not line or not line.strip():
            raise ControlError("dusk scheduler returned an empty response")
        try:
            response = json.loads(line)
        except ValueError as exc:
            raise ControlError(f"invalid response from dusk scheduler: {line!r}") from exc
        if not isinstance(response, dict):
            raise ControlError("invalid response from dusk scheduler")
        return response
