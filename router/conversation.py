"""Conversation-to-SK binding using Responses API input history."""
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict


def _item_fingerprint(item):
    raw = json.dumps(item, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _fingerprint_sequence(request_data):
    user_input = request_data.get("input")
    if not isinstance(user_input, list):
        return []
    return [_item_fingerprint(item) for item in user_input]


class Conversation:
    """Stable binding between one Codex conversation and one SK."""

    def __init__(self, conv_id, sk_id, seen_fingerprints):
        self.conv_id = conv_id
        self.sk_id = sk_id
        self.seen_fingerprints = seen_fingerprints
        self.created_at = time.time()
        self.last_seen = self.created_at
        self.last_response_id = None
        self.cost_limit_notified = False


class ConversationStore:
    """Keeps one SK per conversation by matching growing message history."""

    def __init__(self, pool, usage_store, max_entries=500, now_fn=None):
        self._pool = pool
        self._usage = usage_store
        self._max_entries = max_entries
        self._now_fn = now_fn or time.time
        self._lock = threading.RLock()
        self._prev_map = OrderedDict()
        self._conversations = OrderedDict()
        self._load_persisted()

    def set_pool(self, pool):
        with self._lock:
            self._pool = pool

    def get_or_create(self, request_data):
        with self._lock:
            conv = self._match_previous_id(request_data)
            if conv is None:
                conv = self._match_history(request_data)
            if conv is None:
                conv = self._new_conversation(request_data)
            else:
                self._update_history(conv, request_data)
            conv.last_seen = self._now_fn()
            self._conversations.move_to_end(conv.conv_id)
            self._persist(conv)
            self._evict()
            return conv

    def register_response(self, conv, response_id):
        if not response_id:
            return
        with self._lock:
            conv.last_response_id = response_id
            self._prev_map[("prev", response_id)] = conv
            self._prev_map.move_to_end(("prev", response_id))

    def _match_previous_id(self, request_data):
        previous_id = request_data.get("previous_response_id")
        if not previous_id:
            return None
        return self._prev_map.get(("prev", previous_id))

    def _match_history(self, request_data):
        fingerprints = _fingerprint_sequence(request_data)
        if not fingerprints:
            return None
        tail_candidate = None
        for conv in self._conversations.values():
            if self._is_continuation(conv.seen_fingerprints, fingerprints):
                return conv
            if self._tail_overlap(conv.seen_fingerprints, fingerprints):
                if tail_candidate is None or \
                        conv.last_seen > tail_candidate.last_seen:
                    tail_candidate = conv
        return tail_candidate

    @staticmethod
    def _is_continuation(seen, fingerprints):
        if len(fingerprints) < len(seen):
            return False
        return fingerprints[:len(seen)] == seen

    @staticmethod
    def _tail_overlap(seen, fingerprints, tail_len=6):
        """Compaction keeps recent messages verbatim; find them as a block."""
        if len(fingerprints) <= len(seen) or len(seen) < tail_len:
            return False
        tail = seen[-tail_len:]
        for index in range(len(fingerprints) - tail_len + 1):
            if fingerprints[index:index + tail_len] == tail:
                return True
        return False

    def _update_history(self, conv, request_data):
        fingerprints = _fingerprint_sequence(request_data)
        if fingerprints:
            conv.seen_fingerprints = fingerprints

    def _new_conversation(self, request_data):
        chosen = self._pool.select_sk()
        conv_id = "conv-{}".format(uuid.uuid4().hex[:12])
        fingerprints = _fingerprint_sequence(request_data)
        conv = Conversation(
            conv_id, chosen.cfg.id if chosen else "", fingerprints)
        self._conversations[conv_id] = conv
        return conv

    def _evict(self):
        while len(self._conversations) > self._max_entries:
            _, conv = self._conversations.popitem(last=False)
            self._delete_persisted(conv.conv_id)
        while len(self._prev_map) > self._max_entries:
            self._prev_map.popitem(last=False)

    def _persist(self, conv):
        if self._usage is None:
            return
        self._usage.save_conversation_binding(
            conv.conv_id, conv.sk_id, conv.seen_fingerprints,
            conv.created_at, conv.last_seen, conv.last_response_id,
            conv.cost_limit_notified)

    def _delete_persisted(self, conv_id):
        if self._usage is None:
            return
        self._usage.delete_conversation_binding(conv_id)

    def _load_persisted(self):
        if self._usage is None:
            return
        for row in self._usage.load_conversation_bindings(
                limit=self._max_entries):
            conv = Conversation(row["conv_id"], row["sk_id"],
                                row["fingerprints"])
            conv.created_at = row["created_at"]
            conv.last_seen = row["last_seen"]
            conv.last_response_id = row["last_response_id"]
            conv.cost_limit_notified = bool(row["cost_limit_notified"])
            self._conversations[conv.conv_id] = conv
            if conv.last_response_id:
                self._prev_map[("prev", conv.last_response_id)] = conv
