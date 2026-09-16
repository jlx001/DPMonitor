"""Local HTTP gateway that routes Codex traffic across the SK pool."""
import http.client
import http.server
import json
import threading

SERVER_ERROR_STATUS = {401, 402, 429, 500, 502, 503, 504}
SSE_CONTENT_TYPE = "text/event-stream"


_INJECTED_TITLE_PREFIXES = (
    "# AGENTS.md",
    "The following is the Codex",
    "You are Codex, an agent based on",
    # Codex sends the per-turn environment snapshot as a role=user
    # message; it never contains the user's question.
    "<environment_context>",
)


def _is_injected_title_text(text):
    stripped = text.lstrip()
    return any(stripped.startswith(prefix)
               for prefix in _INJECTED_TITLE_PREFIXES)


def _first_input_text(content):
    """Return the first user text that is not an injected preamble."""
    if isinstance(content, str):
        text = content.strip()
        if text and not _is_injected_title_text(text):
            return text
        return None
    if not isinstance(content, list):
        return None
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") not in ("input_text", "text"):
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if not _is_injected_title_text(text):
            return text.strip()
    return None


def _extract_usage(payload):
    usage = payload.get("usage")
    if not usage:
        usage = (payload.get("response") or {}).get("usage")
    if not usage:
        return None
    input_tokens = (usage.get("input_tokens")
                    or usage.get("prompt_tokens") or 0)
    output_tokens = (usage.get("output_tokens")
                     or usage.get("completion_tokens") or 0)
    details = (usage.get("input_tokens_details")
               or usage.get("prompt_tokens_details") or {})
    cached_tokens = details.get("cached_tokens") or 0
    return int(input_tokens), int(output_tokens), int(cached_tokens)


class GatewayState:
    """Shared state injected into every gateway request handler."""

    def __init__(self, pool, conversations, usage, notifier,
                 upstream_host="api.deepseek.com", upstream_port=443,
                 upstream_scheme="https", conversation_cost_limit=5.0):
        self.pool = pool
        self.conversations = conversations
        self.usage = usage
        self.notifier = notifier
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.upstream_scheme = upstream_scheme
        self.conversation_cost_limit = conversation_cost_limit


class _StateRef:
    """Mutable box so the handler always reads the latest gateway state."""

    def __init__(self, state):
        self.state = state


class Gateway:
    """Threading HTTP server on 127.0.0.1 that proxies API requests."""

    def __init__(self, state, host="127.0.0.1", port=8787):
        self._state_ref = _StateRef(state)
        self._server = http.server.ThreadingHTTPServer(
            (host, port), self._make_handler())
        self._server.state_ref = self._state_ref
        self.port = self._server.server_address[1]
        self._thread = None

    def _make_handler(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/healthz":
                    self._send_bytes(200, "text/plain", b"ok")
                else:
                    self._send_bytes(
                        404, "application/json", b'{"error":"not found"}')

            def do_POST(self):
                _GatewayDispatch(self.server.state_ref.state, self).dispatch()

            def _send_bytes(self, status, content_type, payload):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler

    def set_state(self, state):
        self._state_ref.state = state

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()


class _GatewayDispatch:
    """One inbound request lifecycle: bind SK, forward, record, respond."""

    def __init__(self, state, handler):
        self.state = state
        self.handler = handler

    def dispatch(self):
        body_bytes = self._read_body()
        try:
            request_data = json.loads(body_bytes) if body_bytes else {}
        except ValueError:
            self.handler._send_bytes(
                400, "application/json", b'{"error":"invalid json"}')
            return
        conv = self.state.conversations.get_or_create(request_data)
        model = request_data.get("model") or "unknown"
        title = self._conversation_title(request_data)
        # Keep the row at the top of recent conversations as soon as a
        # request arrives, instead of waiting for the full response.
        self.state.usage.touch_conversation(conv.conv_id)
        status, content_type, payload, usage = self._forward_with_retry(
            self.handler.path, body_bytes, conv)
        self._finish(status, content_type, payload, usage, conv, model, title)

    @staticmethod
    def _conversation_title(request_data):
        for item in request_data.get("input") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message" or item.get("role") != "user":
                continue
            text = _first_input_text(item.get("content"))
            if text:
                return text[:40]
        return ""

    def _read_body(self):
        length = int(self.handler.headers.get("Content-Length") or 0)
        if length > 0:
            return self.handler.rfile.read(length)
        return b""

    def _forward_with_retry(self, path, body_bytes, conv):
        sk = self.state.pool.get(conv.sk_id)
        if sk is None:
            if conv.sk_id:
                return self._bound_sk_removed(conv)
            sk = self.state.pool.select_sk()
            if sk is None:
                return 503, "application/json", \
                    b'{"error":"no sk available"}', None
            conv.sk_id = sk.cfg.id
        status, content_type, payload, usage = self._forward(
            path, body_bytes, sk)
        if status == 401:
            self.state.pool.suspend(sk.cfg.id, 1800)
            alternate = self.state.pool.healthy_fallback(sk.cfg.id)
            if alternate is not None:
                conv.sk_id = alternate.cfg.id
                self.state.notifier.notify(
                    "key_switched",
                    "SK {} 鉴权失败，已切换到 {}".format(
                        sk.cfg.id, alternate.cfg.id),
                    sk_id=sk.cfg.id)
                self.state.usage.add_event(
                    "key_switched",
                    "401 -> {}".format(alternate.cfg.id),
                    sk_id=sk.cfg.id)
                status, content_type, payload, usage = self._forward(
                    path, body_bytes, alternate)
        return status, content_type, payload, usage

    def _bound_sk_removed(self, conv):
        self.state.notifier.notify(
            "sk_removed",
            "当前对话绑定的 SK {} 已被删除，无法继续请求".format(
                conv.sk_id),
            sk_id=conv.sk_id)
        self.state.usage.add_event(
            "sk_removed", "bound sk removed", sk_id=conv.sk_id)
        return 503, "application/json", b'{"error":"bound sk removed"}', None

    def _forward(self, path, body_bytes, sk):
        conn = self._connect()
        headers = {
            "Authorization": "Bearer {}".format(sk.api_key),
            "Content-Type": self.handler.headers.get(
                "Content-Type", "application/json"),
            "Accept": self.handler.headers.get(
                "Accept", "application/json"),
            "User-Agent": "DeepSeekMonitor-Gateway/1.0",
        }
        conn.request("POST", path, body=body_bytes, headers=headers)
        response = conn.getresponse()
        status = response.status
        content_type = response.getheader("Content-Type", "application/json")
        if content_type.startswith(SSE_CONTENT_TYPE):
            payload, usage = self._drain_sse(response)
        else:
            payload = response.read()
            usage = self._usage_from_payload(self._try_json(payload))
        conn.close()
        return status, content_type, payload, usage

    def _connect(self):
        if self.state.upstream_scheme == "http":
            return http.client.HTTPConnection(
                self.state.upstream_host, self.state.upstream_port, timeout=180)
        return http.client.HTTPSConnection(
            self.state.upstream_host, self.state.upstream_port, timeout=180)

    def _drain_sse(self, response):
        chunks = []
        buffer = b""
        usage = None
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            buffer += chunk
            if usage is None:
                usage = self._usage_from_sse(buffer)
        return b"".join(chunks), usage

    def _usage_from_sse(self, buffer):
        for line in buffer.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            payload = self._try_json(data)
            if payload:
                usage = _extract_usage(payload)
                if usage is not None:
                    return usage
        return None

    @staticmethod
    def _usage_from_payload(payload):
        if isinstance(payload, dict):
            return _extract_usage(payload)
        return None

    @staticmethod
    def _try_json(raw):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def _finish(self, status, content_type, payload, usage, conv, model,
                title):
        if status in SERVER_ERROR_STATUS:
            if conv.sk_id and self.state.pool.get(conv.sk_id) is None:
                self._respond(status, content_type, payload)
                return
            self.state.pool.suspend(conv.sk_id, 1800)
            self.state.notifier.notify(
                "server_error",
                "SK {} 上游错误 {}，已熔断并中断当前对话".format(
                    conv.sk_id, status),
                sk_id=conv.sk_id)
            self.state.usage.add_event(
                "server_error", "status={}".format(status), sk_id=conv.sk_id)
            self._respond(status, content_type, payload)
            return
        if usage is not None:
            input_tokens, output_tokens, cached_tokens = usage
            self.state.usage.record_request(
                conv.sk_id, conv.conv_id, model,
                input_tokens, output_tokens, cached_tokens, title=title)
            self._check_conversation_limit(conv)
        self._respond(status, content_type, payload)

    def _check_conversation_limit(self, conv):
        limit = self.state.conversation_cost_limit
        if limit <= 0 or conv.cost_limit_notified:
            return
        if self.state.usage.conversation_cost(conv.conv_id) >= limit:
            conv.cost_limit_notified = True
            self.state.notifier.notify(
                "cost_limit",
                "当前对话已消费超过阈值（¥{}），建议新建对话".format(limit),
                sk_id=conv.sk_id)
            self.state.usage.add_event(
                "cost_limit",
                "conversation cost limit reached",
                sk_id=conv.sk_id)

    def _respond(self, status, content_type, payload):
        if content_type.startswith(SSE_CONTENT_TYPE):
            handler = self.handler
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.end_headers()
            handler.wfile.write(payload)
            handler.wfile.flush()
            handler.close_connection = True
        else:
            self.handler._send_bytes(status, content_type, payload)
