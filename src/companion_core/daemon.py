"""Authenticated loopback IPC. Only this process writes the shared event log."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

from .chat import ChatSession
from .model_adapter import ModelError
from .models import Event, SourceType
from .ownership import LogLease
from .runtime import OSRuntimeObserver, runtime_changed


def endpoint_path(event_path):
    return Path(str(Path(event_path).resolve()) + ".daemon.json")


class CompanionDaemon:
    def __init__(self, adapter, event_path, observer=None, interval=30):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("観測間隔は正の有限秒数にしてください")
        self.lease = LogLease(event_path).acquire()
        self.server = None
        self.endpoint = endpoint_path(event_path)
        self.published = False
        try:
            self.session = ChatSession(adapter, event_path)
            self.observer = observer or OSRuntimeObserver()
            self.previous = self.session.core.last_runtime
            self.interval = interval
            self.lock = threading.RLock()
            self.turn_lock = threading.Lock()
            self.token = secrets.token_hex(32)
            self.stop = threading.Event()
        except BaseException:
            self.lease.close()
            raise

    def poll(self):
        sample = self.observer.observe()
        event = Event(kind="runtime_observation", payload=sample, source=SourceType.RUNTIME)
        with self.lock:
            changed = runtime_changed(self.previous, sample)
            # Append before changing live state, so disk failure never invents durability.
            if changed:
                self.session.core.events.append(event)
            if not self.session.core.accept_runtime(event):
                raise ValueError("invalid runtime observation")
            self.previous = dict(sample)
            return changed

    def turn(self, text, correction_key=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            raise ValueError("入力は1〜16000文字にしてください")
        if correction_key is not None and not isinstance(correction_key, str):
            raise ValueError("invalid correction key")
        # Serialize conversations, but allow OS observations/status while LLM is busy.
        with self.turn_lock:
            with self.lock:
                ctx = self.session.core.handle(text, correction_key=correction_key)
                ctx["runtime"]["pc_observation"] = self.session.core.last_runtime
                messages = self.session.prompts.build(ctx, self.session.core.events.events)
            reply = self.session.generate_reply(ctx, messages)
            with self.lock:
                self.session.core.record_assistant_output(reply)
            return reply

    def start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass  # Never print conversation bodies or credentials.

            def do_POST(self):
                if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + owner.token):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 65536:
                        raise ValueError("invalid request length")
                    body = json.loads(self.rfile.read(length))
                    if self.path == "/status":
                        with owner.lock:
                            result = owner.session.status()
                    elif self.path == "/turn":
                        result = owner.turn(body["text"], body.get("correction_key"))
                    else:
                        self.send_error(404)
                        return
                    self.respond(200, {"result": result})
                except ModelError as exc:
                    self.respond(502, {"error": str(exc)})
                except (ValueError, KeyError, TypeError, OSError) as exc:
                    self.respond(400, {"error": str(exc)})

            def respond(self, code, body):
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.poll()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # Atomic discovery publication; the lease excludes another publisher.
        temporary = self.endpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps({"port": self.server.server_port, "token": self.token}), encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.endpoint)
        self.published = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def run(self):
        self.start()
        while not self.stop.wait(self.interval):
            self.poll()

    def close(self):
        if self.server is not None:
            if hasattr(self, "thread"):
                self.server.shutdown()
                self.thread.join()
            self.server.server_close()  # Wait for in-flight model requests before releasing lease.
            self.server = None
        if self.published:
            self.endpoint.unlink(missing_ok=True)
            self.published = False
        self.lease.close()


class DaemonClient:
    def __init__(self, event_path, timeout=240):
        info = json.loads(endpoint_path(event_path).read_text(encoding="utf-8"))
        port = info["port"]
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(info["token"], str):
            raise ValueError("invalid daemon endpoint")
        self.url = f"http://127.0.0.1:{port}"
        self.token = info["token"]
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}))

    def request(self, route, body):
        req = Request(self.url + route, json.dumps(body).encode("utf-8"),
                      {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                return json.load(response)["result"]
        except HTTPError as exc:
            if exc.code == 502:
                raise ModelError(json.load(exc)["error"]) from exc
            raise OSError(f"daemon IPC error: {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            # Never silently retry a possibly committed turn via a second writer.
            raise OSError("daemon接続が切れました。/statusで状態を確認してから再接続してください") from exc

    def turn(self, text, *, correction_key=None):
        return self.request("/turn", {"text": text, "correction_key": correction_key})

    def status(self):
        return self.request("/status", {})

    def close(self):
        pass


class LocalSession(ChatSession):
    def __init__(self, adapter, event_path):
        self.lease = LogLease(event_path).acquire()
        try:
            super().__init__(adapter, event_path)
        except BaseException:
            self.lease.close()
            raise

    def close(self):
        self.lease.close()


def connect_session(adapter, event_path, timeout=240):
    try:
        client = DaemonClient(event_path, timeout)
        client.status()
        return client
    except (OSError, ValueError, KeyError):
        # An alive but unavailable daemon still owns the lease: fail closed.
        return LocalSession(adapter, event_path)
