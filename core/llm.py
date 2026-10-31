"""LLM client: the single entry point for every model call.

Responsibilities (all of them exist to protect your credits):
  * disk cache keyed by (provider, full request payload): reruns are free
  * hard spend cap PER PROVIDER (Meta and Modal credits never mix)
  * exact cost accounting with cached-input, input and output token rates
  * retries with backoff on 429/5xx/network errors, none on other 4xx
  * a ledger (JSONL) of every paid call, for the cost-per-program report

Two wire formats are supported:
  "responses": the format of your working Meta call (input_text items)
  "chat":      OpenAI-style /chat/completions (likely for Modal/Baseten;
               check the provider's quickstart and adjust PROVIDERS)

Standard library only (urllib), so it works inside the Docker image as is.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


class LLMTruncated(LLMError):
    """Reply was cut off (token limit). The provider still bills these tokens,
    so the exception carries usage and, once the client has recorded it, cost."""

    def __init__(self, msg: str, usage: dict):
        super().__init__(msg)
        self.usage = usage
        self.cost_usd = 0.0


@dataclass(frozen=True)
class Provider:
    name: str
    wire: str                      # "responses" | "chat"
    url_env: str                   # env var holding the full endpoint URL
    key_env: str
    default_model: str             # "" -> must come from <NAME>_MODEL env or argument
    price_in: float                # $ per 1M fresh input tokens
    price_cached: float            # $ per 1M cached input tokens
    price_out: float               # $ per 1M output tokens (reasoning tokens count as output)
    default_effort: str | None     # reasoning effort sent by default (None = do not send)
    default_cap_usd: float
    url_default: str = ""          # used when the url env var is not set
    default_max_output_tokens: int | None = None   # sent when the caller sets none


PROVIDERS = {
    # Prices from the Meta Model API pricing page (Standard mode).
    "meta": Provider("meta", "responses", "META_API_URL", "META_API_KEY",
                     "muse-spark-1.3", 1.25, 0.15, 4.25, "low", 40.0),
    # Modal Shared Endpoint. Per Modal's docs: OpenAI Chat Completions (and
    # Responses) at inference.us-west.modal.direct, authenticated with a proxy
    # token "wk-...<id>.ws-...<secret>" as a Bearer key. The model id is the
    # endpoint's hostname: list it with GET <host>/v1/models. Prices are from
    # third-party listings: CONFIRM in your Modal dashboard.
    "modal": Provider("modal", "chat", "MODAL_API_URL", "MODAL_API_KEY",
                      "", 1.25, 0.15, 4.25, None, 40.0,
                      "https://inference.us-west.modal.direct/v1/chat/completions"),
    # Baseten Model APIs: OpenAI Chat Completions at inference.baseten.co/v1,
    # Bearer API key. The hackathon guide says to use the "-1026" model slug
    # (the public docs show meta-models/muse-spark-open).
    "baseten": Provider("baseten", "chat", "BASETEN_API_URL", "BASETEN_API_KEY",
                        "meta-models/muse-spark-open-1026", 1.25, 0.15, 4.25, None, 40.0,
                        "https://inference.baseten.co/v1/chat/completions", 32000),
}


@dataclass
class LLMResult:
    text: str
    usage: dict            # input_tokens, cached_tokens, output_tokens, reasoning_tokens
    cost_usd: float        # what THIS call cost (0.0 on a cache hit)
    cached: bool
    model: str
    provider: str
    latency_s: float = 0.0
    list_cost_usd: float = 0.0   # what the call costs at list price (also for cache hits)


# ------------------------------------------------------------------ utils --
def load_env(path: str | Path = ".env") -> None:
    """Minimal .env loader (KEY=VALUE lines); existing environment wins."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def compute_cost(p: Provider, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    fresh = max(input_tokens - cached_tokens, 0)
    return (fresh * p.price_in + cached_tokens * p.price_cached + output_tokens * p.price_out) / 1e6


def _urllib_post(url: str, headers: dict, payload: dict, timeout: float):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, body


# ---------------------------------------------------------------- parsing --
def _usage_responses(data: dict) -> dict:
    u = data.get("usage") or {}
    return {
        "input_tokens": u.get("input_tokens", 0),
        "cached_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
    }


def _usage_chat(data: dict) -> dict:
    u = data.get("usage") or {}
    return {
        "input_tokens": u.get("prompt_tokens", 0),
        "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        "output_tokens": u.get("completion_tokens", 0),
        "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
    }


def parse_responses(data: dict) -> tuple[str, dict]:
    usage = _usage_responses(data)
    if data.get("error"):
        raise LLMError(f"API error: {data['error']}")
    status = data.get("status")
    if status not in (None, "completed"):
        msg = f"response not completed: {status} {data.get('incomplete_details')}"
        raise (LLMTruncated(msg, usage) if status == "incomplete" else LLMError(msg))
    texts = [c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    return "".join(texts), usage


def parse_chat(data: dict) -> tuple[str, dict]:
    usage = _usage_chat(data)
    if data.get("error"):
        raise LLMError(f"API error: {data['error']}")
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise LLMTruncated("output truncated (finish_reason=length): the model hit its token "
                           "limit, probably while reasoning; raise max_output_tokens or lower effort", usage)
    return (choice.get("message") or {}).get("content") or "", usage


# ----------------------------------------------------------------- client --
class LLMClient:
    def __init__(self, provider: str = "meta", *, model: str | None = None,
                 state_dir: str | Path = ".cache", max_spend: float | None = None,
                 post: Callable | None = None, sleep: Callable = time.sleep,
                 env: dict | None = None, timeout: float = 180.0):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider '{provider}' (known: {sorted(PROVIDERS)})")
        self.p = PROVIDERS[provider]
        self.provider = provider
        self.env = os.environ if env is None else env
        # <PROVIDER>_WIRE=responses|chat overrides the wire format (e.g. to use
        # Modal's Responses API so `reasoning.effort` works as it does on Meta).
        self.wire = self.env.get(f"{provider.upper()}_WIRE") or self.p.wire
        self.model = model or self.env.get(f"{provider.upper()}_MODEL") or self.p.default_model
        if not self.model:
            raise LLMError(f"no model set for '{provider}': pass model= or set {provider.upper()}_MODEL")
        self.state = Path(state_dir)
        self.cache_dir = self.state / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.spend_file = self.state / f"spend_{provider}.json"
        self.ledger_file = self.state / "ledger.jsonl"
        cap_env = self.env.get(f"MAX_SPEND_{provider.upper()}_USD")
        self.max_spend = max_spend if max_spend is not None else (
            float(cap_env) if cap_env else self.p.default_cap_usd)
        mot = self.env.get(f"{provider.upper()}_MAX_OUTPUT_TOKENS")
        self.default_max_out = int(mot) if mot else self.p.default_max_output_tokens
        self._post = post or _urllib_post
        self._sleep = sleep
        self._timeout = timeout
        self._lock = threading.Lock()

    # --- spend bookkeeping
    def spent(self) -> float:
        try:
            return json.loads(self.spend_file.read_text())["usd"]
        except (OSError, ValueError, KeyError):
            return 0.0

    def _record(self, usd: float, entry: dict) -> None:
        with self._lock:
            tmp = self.spend_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"usd": self.spent() + usd}))
            tmp.replace(self.spend_file)
            with self.ledger_file.open("a") as f:
                f.write(json.dumps(entry) + "\n")

    # --- request building
    def _payload(self, prompt, system, effort, temperature, max_output_tokens) -> dict:
        eff = self.p.default_effort if effort == "default" else effort
        if self.wire == "responses":
            pl = {"model": self.model, "stream": False,
                  "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}]}
            if system:
                pl["instructions"] = system
            if eff:
                pl["reasoning"] = {"effort": eff}
            if max_output_tokens:
                pl["max_output_tokens"] = max_output_tokens
        else:
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
            pl = {"model": self.model, "messages": msgs, "stream": False}
            if eff:
                pl["reasoning_effort"] = eff
            if max_output_tokens:
                pl["max_tokens"] = max_output_tokens
        if temperature is not None:
            pl["temperature"] = temperature
        return pl

    def effective_effort(self, effort="default") -> str:
        """The reasoning effort actually sent ("none" if nothing is sent)."""
        eff = self.p.default_effort if effort == "default" else effort
        return eff or "none"

    # --- the one public method
    def call(self, prompt: str, *, system: str | None = None, effort: str | None = "default",
             temperature: float | None = None, max_output_tokens: int | None = None,
             tag: str = "", salt: str = "") -> LLMResult:
        """`salt` is part of the cache key but is NOT sent to the API: use it to
        draw a fresh sample of an otherwise identical request (variance runs)."""
        payload = self._payload(prompt, system, effort, temperature,
                                max_output_tokens or self.default_max_out)
        keyed = {"p": self.provider, "pl": payload}
        if salt:
            keyed["salt"] = salt
        key = hashlib.sha256(json.dumps(keyed, sort_keys=True).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            c = json.loads(cache_file.read_text())
            u = c["usage"]
            lc = compute_cost(self.p, u["input_tokens"], u["cached_tokens"], u["output_tokens"])
            return LLMResult(c["text"], u, 0.0, True, self.model, self.provider, 0.0, lc)

        if self.spent() >= self.max_spend:
            raise BudgetExceeded(f"{self.provider}: spend cap ${self.max_spend:.2f} reached "
                                 f"(spent ${self.spent():.4f})")
        url = self.env.get(self.p.url_env) or self.p.url_default
        api_key = self.env.get(self.p.key_env)
        if not url or not api_key:
            raise LLMError(f"set {self.p.url_env} (if it has no default) and {self.p.key_env}; see .env.example")

        headers = {"Authorization": f"Bearer {api_key}"}
        start = time.monotonic()
        data = None
        for attempt in range(4):
            try:
                status, body = self._post(url, headers, payload, self._timeout)
            except OSError as e:                      # URLError, timeouts, resets
                if attempt == 3:
                    raise LLMError(f"network error: {e}") from e
                self._sleep(2 ** attempt)
                continue
            if status in (429, 500, 502, 503, 504):
                if attempt == 3:
                    raise LLMError(f"HTTP {status} after retries: {str(body)[:300]}")
                self._sleep(2 ** attempt)
                continue
            if not 200 <= status < 300:
                raise LLMError(f"HTTP {status}: {str(body)[:500]}")   # e.g. unsupported parameter
            data = body
            break
        if not isinstance(data, dict):
            raise LLMError(f"unexpected response body: {str(data)[:300]}")

        parser = parse_responses if self.wire == "responses" else parse_chat
        try:
            text, usage = parser(data)
        except LLMTruncated as e:           # billed even though unusable: record it
            u = e.usage
            e.cost_usd = compute_cost(self.p, u["input_tokens"], u["cached_tokens"], u["output_tokens"])
            self._record(e.cost_usd, {"ts": time.time(), "provider": self.provider, "model": self.model,
                                      "tag": tag, "cost_usd": e.cost_usd, "truncated": True, **u})
            raise
        cost = compute_cost(self.p, usage["input_tokens"], usage["cached_tokens"], usage["output_tokens"])
        latency = time.monotonic() - start
        self._record(cost, {"ts": time.time(), "provider": self.provider, "model": self.model,
                            "tag": tag, "cost_usd": cost, "latency_s": round(latency, 2), **usage})
        cache_file.write_text(json.dumps({"text": text, "usage": usage}))
        return LLMResult(text, usage, cost, False, self.model, self.provider, latency, cost)


# -------------------------------------------------------------------- CLI --
def main(argv: list[str]) -> int:
    """Smoke test:  python -m core.llm [--provider meta|modal] ["prompt"]"""
    load_env()
    provider = "meta"
    args = argv[1:]
    if "--provider" in args:
        i = args.index("--provider")
        provider = args[i + 1]
        del args[i:i + 2]
    prompt = " ".join(args) or "Reply with the single word: ready"
    client = LLMClient(provider)
    r = client.call(prompt, tag="smoke")
    print(r.text)
    print(f"\nmodel={r.model} cached={r.cached} usage={r.usage} cost=${r.cost_usd:.6f} "
          f"spent_total=${client.spent():.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))