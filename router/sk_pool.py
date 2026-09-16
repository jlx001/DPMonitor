"""SK pool configuration and selection policy."""
import datetime as dt
from dataclasses import dataclass, field


@dataclass
class SKConfig:
    id: str
    name: str
    weight: int = 1
    daily_cost_cap: float = 0.0
    monthly_cost_cap: float = 0.0
    time_windows: list = field(default_factory=list)
    is_default: bool = False
    is_platform: bool = False
    enabled: bool = True


class SK:
    """Runtime state for one SK: balance, circuit breaker, api key."""

    def __init__(self, config):
        self.cfg = config
        self.api_key = ""
        self.balance = None
        self.is_available = True
        self.suspended_until = 0.0


class SKPool:
    """Picks the best SK for a new conversation by quota deficit."""

    def __init__(self, configs, usage_store, now_fn=None):
        self._usage = usage_store
        self._now_fn = now_fn or dt.datetime.now
        self._by_id = {config.id: SK(config) for config in configs}

    def all(self):
        return list(self._by_id.values())

    def get(self, sk_id):
        return self._by_id.get(sk_id)

    def upsert(self, config):
        existing = self._by_id.get(config.id)
        if existing is None:
            self._by_id[config.id] = SK(config)
        else:
            existing.cfg = config
        return self._by_id[config.id]

    def remove(self, sk_id):
        self._by_id.pop(sk_id, None)

    def set_balance(self, sk_id, balance, is_available=True):
        sk = self._by_id.get(sk_id)
        if sk is not None:
            sk.balance = balance
            sk.is_available = is_available

    def suspend(self, sk_id, seconds):
        sk = self._by_id.get(sk_id)
        if sk is not None:
            sk.suspended_until = self._now_fn().timestamp() + seconds

    def resume(self, sk_id):
        sk = self._by_id.get(sk_id)
        if sk is not None:
            sk.suspended_until = 0.0

    def select_sk(self):
        now = self._now_fn()
        candidates = [sk for sk in self._by_id.values()
                      if self._is_eligible(sk, now)]
        if not candidates:
            return self._default_sk()
        total_weight = sum(sk.cfg.weight for sk in candidates)
        best = None
        best_score = float("-inf")
        for sk in candidates:
            target_share = sk.cfg.weight / total_weight
            actual_share = self._actual_share(sk.cfg.id)
            score = target_share - actual_share + self._balance_tiebreak(sk)
            if score > best_score:
                best_score = score
                best = sk
        return best

    def healthy_fallback(self, exclude_sk_id):
        now = self._now_fn()
        candidates = [
            sk for sk in self._by_id.values()
            if sk.cfg.id != exclude_sk_id and self._is_eligible(sk, now)
        ]
        if not candidates:
            return None
        return candidates[0]

    def _is_eligible(self, sk, now):
        cfg = sk.cfg
        if not cfg.enabled:
            return False
        if now.timestamp() < sk.suspended_until:
            return False
        if not self._in_time_window(cfg, now):
            return False
        if cfg.daily_cost_cap > 0 and \
                self._usage.today_cost(cfg.id) >= cfg.daily_cost_cap:
            return False
        if cfg.monthly_cost_cap > 0 and \
                self._usage.month_cost(cfg.id) >= cfg.monthly_cost_cap:
            return False
        if sk.balance is not None and not sk.is_available:
            return False
        if sk.balance is not None and sk.balance <= 0:
            return False
        return True

    @staticmethod
    def _in_time_window(cfg, now):
        if not cfg.time_windows:
            return True
        current = now.strftime("%H:%M")
        for window in cfg.time_windows:
            start_text, _, end_text = window.partition("-")
            if start_text <= current <= end_text:
                return True
        return False

    def _actual_share(self, sk_id):
        costs = {sid: self._usage.today_cost(sid) for sid in self._by_id}
        total = sum(costs.values())
        if total <= 0:
            return 0.0
        return costs.get(sk_id, 0.0) / total

    @staticmethod
    def _balance_tiebreak(sk):
        if sk.balance is None:
            return 0.0
        return min(max(sk.balance, 0.0), 100.0) / 100.0 * 0.01

    def _default_sk(self):
        for sk in self._by_id.values():
            if sk.cfg.is_default:
                return sk
        return next(iter(self._by_id.values()), None)
