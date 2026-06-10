"""
DeepSeek Platform API — balance + usage from platform.deepseek.com.
"""
import json, requests, os, datetime as dt
from datetime import datetime, timedelta

PLATFORM_BASE = "https://platform.deepseek.com/api/v0"


def _log(msg: str):
    now = dt.datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "app.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass


class DeepSeekPlatform:
    """Client for platform.deepseek.com internal API (requires token + cookie)."""

    def __init__(self, platform_token: str, cookie: str = ""):
        self.token = platform_token
        self.sess = requests.Session()
        self.sess.headers.update({
            "Authorization": f"Bearer {platform_token}",
            "Accept": "application/json",
            "x-app-version": "1.0.0",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        })
        if cookie:
            self.sess.headers["Cookie"] = cookie

    def _get(self, path: str, params: dict = None) -> dict:
        resp = self.sess.get(f"{PLATFORM_BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise Exception(f"API error: {data.get('msg', 'unknown')}")
        return data.get("data", {}).get("biz_data", {})

    def test_connection(self) -> bool:
        try:
            self._get("/users/get_user_summary")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """Overall account summary — balance, monthly usage, monthly cost."""
        d = self._get("/users/get_user_summary")
        _log(f"Summary: OK ({len(d.get('normal_wallets',[]))} wallets, {len(d.get('monthly_costs',[]))} costs)")

        def _cny(items: list) -> str:
            for it in items:
                if it.get("currency") == "CNY":
                    return it.get("balance") or it.get("amount") or "0"
            return items[0].get("balance") or items[0].get("amount") or "0" if items else "0"

        balance = float(_cny(d.get("normal_wallets", [])))
        monthly_cost = float(_cny(d.get("monthly_costs", [])))
        monthly_tokens = int(float(d.get("monthly_token_usage", "0")))
        current_token = int(float(d.get("current_token", "0")))

        return {
            "balance": balance,
            "monthly_cost": monthly_cost,
            "monthly_tokens": monthly_tokens,
            "current_tokens": current_token,
        }

    # ------------------------------------------------------------------
    # Cost & Amount (per-model, per-day breakdown)
    # ------------------------------------------------------------------

    def _parse_usage(self, items: list) -> dict:
        """Convert platform usage entries → our standard model."""
        m = {"prompt_tokens": 0, "cache_hit_tokens": 0,
             "cache_miss_tokens": 0, "completion_tokens": 0,
             "requests": 0, "cost": 0.0}
        for e in items:
            t = e.get("type", "")
            v = float(e.get("amount", "0"))
            m["cost"] += v  # sum all amounts (cost ¥ for cost endpoint, tokens for amount endpoint)
            if t == "PROMPT_TOKEN":
                m["prompt_tokens"] = int(v)
            elif t == "PROMPT_CACHE_HIT_TOKEN":
                m["cache_hit_tokens"] = int(v)
            elif t == "PROMPT_CACHE_MISS_TOKEN":
                m["cache_miss_tokens"] = int(v)
            elif t == "RESPONSE_TOKEN":
                m["completion_tokens"] = int(v)
            elif t == "REQUEST":
                m["requests"] = int(v)
        return m

    def _hit_rate(self, m: dict) -> float:
        total = m["cache_hit_tokens"] + m["cache_miss_tokens"]
        return round(m["cache_hit_tokens"] / total * 100, 1) if total > 0 else 0.0

    def get_daily_costs(self, year: int, month: int) -> dict:
        """Per-day costs for the month — also gives per-model totals."""
        d = self._get("/usage/cost", {"month": month, "year": year})
        result = {"total": {}, "days": {}}
        for currency_block in (d if isinstance(d, list) else [d]):
            if not isinstance(currency_block, dict):
                continue
            # Only use CNY data (USD block comes second with all zeros)
            if currency_block.get("currency") not in (None, "CNY"):
                continue
            if "total" not in currency_block:
                continue
            # Parse total per model
            for item in currency_block.get("total", []):
                model = item.get("model", "unknown")
                parsed = self._parse_usage(item.get("usage", []))
                if model not in result["total"]:
                    result["total"][model] = {"cost": 0.0, "tokens": {}}
                result["total"][model]["cost"] += parsed["cost"]
            # Parse daily breakdown
            for day in currency_block.get("days", []):
                date = day.get("date", "")
                if date not in result["days"]:
                    result["days"][date] = {"cost": 0.0, "models": {}}
                for item in day.get("data", []):
                    model = item.get("model", "unknown")
                    parsed = self._parse_usage(item.get("usage", []))
                    result["days"][date]["cost"] += parsed["cost"]
                    result["days"][date]["models"][model] = dict(parsed)
        return result

    def get_daily_tokens(self, year: int, month: int) -> dict:
        """Per-day token counts for the month."""
        d = self._get("/usage/amount", {"month": month, "year": year})
        result = {"total": {}, "days": {}}
        if isinstance(d, dict):
            # Total per model
            for item in d.get("total", []):
                model = item.get("model", "unknown")
                result["total"][model] = self._parse_usage(item.get("usage", []))
            # Daily breakdown
            for day in d.get("days", []):
                date = day.get("date", "")
                result["days"][date] = {}
                for item in day.get("data", []):
                    model = item.get("model", "unknown")
                    result["days"][date][model] = self._parse_usage(item.get("usage", []))
        return result

    # ------------------------------------------------------------------
    # Combined — matches UI data format
    # ------------------------------------------------------------------

    def get_all_usage(self) -> dict:
        """Return combined data for UI rendering."""
        now = datetime.now()
        year, month = now.year, now.month

        summary = self.get_summary()

        try:
            costs = self.get_daily_costs(year, month)
            _log(f"Costs: OK")
        except Exception as e:
            _log(f"Costs error: {e}")
            import traceback; _log(traceback.format_exc())
            costs = {"total": {}, "days": {}}

        try:
            tokens = self.get_daily_tokens(year, month)
            _log(f"Tokens: OK")
        except Exception as e:
            _log(f"Tokens error: {e}")
            import traceback; _log(traceback.format_exc())
            tokens = {"total": {}, "days": {}}

        # Daily cost for today
        today_str = now.strftime("%Y-%m-%d")
        daily_cost = costs.get("days", {}).get(today_str, {}).get("cost", 0.0)

        # Build per-model stats
        models = {}
        cost_total = costs.get("total", {})
        token_total = tokens.get("total", {})

        # Only keep actual model names (v4-flash, v4-pro)
        KEEP_MODELS = {'deepseek-v4-flash', 'deepseek-v4-pro'}
        all_models = set()
        for m in list(cost_total.keys()) + list(token_total.keys()):
            if m in KEEP_MODELS:
                all_models.add(m)
        for model in all_models:
            t = token_total.get(model, {})
            c = cost_total.get(model, {})
            models[model] = {
                "input_tokens_cache_hit": t.get("cache_hit_tokens", 0),
                "input_tokens_cache_miss": t.get("cache_miss_tokens", 0),
                "output_tokens": t.get("completion_tokens", 0),
                "requests": t.get("requests", 0),
                "hit_rate": self._hit_rate(t) if t else 0.0,
                "cost": c.get("cost", 0.0) if isinstance(c, dict) else 0.0,
            }

        # Daily breakdown — all days in month, sorted
        all_days = []
        raw_days = costs.get("days", {})
        _log(f"Daily breakdown: {len(raw_days)} days")
        for ds, day in sorted(raw_days.items()):
            day_cost = day.get("cost", 0.0)
            per_model = {}
            for m, v in day.get("models", {}).items():
                if m not in KEEP_MODELS: continue
                mc = v.get("cost", 0.0) if isinstance(v, dict) else 0.0
                per_model[m] = round(mc, 4)
            all_days.append({
                "date": ds[5:],
                "cost": round(day_cost, 4),
                "models": per_model,
            })
        # If no data from API, generate empty days
        if not all_days:
            for i in range(6, -1, -1):
                d = now - timedelta(days=i)
                all_days.append({"date": d.strftime("%m-%d"), "cost": 0, "models": {}})

        # Today's per-model data for day/month toggle
        today_models = {}
        today_tokens = tokens.get("days", {}).get(today_str, {})
        today_costs = costs.get("days", {}).get(today_str, {}).get("models", {})
        for model in all_models:
            t = today_tokens.get(model, {})
            c = today_costs.get(model, {})
            today_models[model] = {
                "input_tokens_cache_hit": t.get("cache_hit_tokens", 0) if isinstance(t, dict) else 0,
                "input_tokens_cache_miss": t.get("cache_miss_tokens", 0) if isinstance(t, dict) else 0,
                "output_tokens": t.get("completion_tokens", 0) if isinstance(t, dict) else 0,
                "cost": c.get("cost", 0.0) if isinstance(c, dict) else 0.0,
            }

        return {
            "balance": {
                "currency": "CNY",
                "total_balance": summary["balance"],
            },
            "usage": {
                "daily_cost": round(daily_cost, 4),
                "monthly_cost": round(summary["monthly_cost"], 4),
                "models": models,
                "today_models": today_models,
                "daily_breakdown": all_days,
            },
        }
