"""LLM client tests. A fake `post` replaces HTTP, so these cost nothing."""
import json
import pytest
from core.llm import (LLMClient, LLMError, LLMTruncated, BudgetExceeded, PROVIDERS, compute_cost,
                      parse_responses, parse_chat)

ENV = {"META_API_URL": "http://x/v1/responses", "META_API_KEY": "k",
       "MODAL_API_URL": "http://m/v1/chat/completions", "MODAL_API_KEY": "k2", "BASETEN_API_KEY": "bk",
       "MODAL_MODEL": "some-open-model"}


def responses_body(text="hello", inp=32, out=1500, cached=0, reasoning=953):
    """Shape of the real Meta response you pasted: reasoning item first, then message."""
    return {"status": "completed", "error": None,
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": inp, "input_tokens_details": {"cached_tokens": cached},
                      "output_tokens": out, "output_tokens_details": {"reasoning_tokens": reasoning}}}


def chat_body(text="hi", pt=100, ct=50, cached=40):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": pt, "completion_tokens": ct,
                      "prompt_tokens_details": {"cached_tokens": cached}}}


class FakePost:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, payload))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(tmp_path, post, provider="meta", **kw):
    return LLMClient(provider, state_dir=tmp_path, post=post, sleep=lambda s: None,
                     env=dict(ENV), **kw)


def test_cost_matches_the_real_call_you_measured():
    # 32 input + 1500 output tokens at Spark 1.3 prices = about $0.0064
    c = compute_cost(PROVIDERS["meta"], 32, 0, 1500)
    assert abs(c - 0.006415) < 1e-9


def test_cost_uses_cached_rate():
    p = PROVIDERS["meta"]
    assert compute_cost(p, 1_000_000, 1_000_000, 0) == pytest.approx(0.15)
    assert compute_cost(p, 1_000_000, 0, 0) == pytest.approx(1.25)


def test_parse_responses_skips_reasoning_item():
    text, usage = parse_responses(responses_body("the answer"))
    assert text == "the answer" and usage["reasoning_tokens"] == 953


def test_incomplete_response_is_an_error():
    body = responses_body()
    body["status"] = "incomplete"
    with pytest.raises(LLMError):
        parse_responses(body)


def test_chat_parsing_and_truncation():
    text, usage = parse_chat(chat_body())
    assert text == "hi" and usage["cached_tokens"] == 40
    bad = chat_body()
    bad["choices"][0]["finish_reason"] = "length"
    with pytest.raises(LLMError):
        parse_chat(bad)


def test_cache_hit_is_free_and_skips_http(tmp_path):
    post = FakePost((200, responses_body("one")))
    c = client(tmp_path, post)
    r1 = c.call("prompt", system="rules")
    r2 = c.call("prompt", system="rules")
    assert not r1.cached and r2.cached and r2.cost_usd == 0.0 and r2.text == "one"
    assert len(post.calls) == 1
    assert c.spent() == pytest.approx(r1.cost_usd)


def test_different_prompt_or_effort_is_a_cache_miss(tmp_path):
    post = FakePost((200, responses_body("a")), (200, responses_body("b")), (200, responses_body("c")))
    c = client(tmp_path, post)
    c.call("p1"); c.call("p2"); c.call("p1", effort="high")
    assert len(post.calls) == 3


def test_spend_cap_blocks_next_call(tmp_path):
    post = FakePost((200, responses_body(out=1_000_000)), (200, responses_body()))
    c = client(tmp_path, post, max_spend=1.0)       # first call costs ~$4.25
    c.call("a")
    with pytest.raises(BudgetExceeded):
        c.call("b")
    assert len(post.calls) == 1


def test_providers_have_separate_budgets(tmp_path):
    meta = client(tmp_path, FakePost((200, responses_body(out=1_000_000))), max_spend=1.0)
    meta.call("a")
    modal = client(tmp_path, FakePost((200, chat_body())), provider="modal", max_spend=1.0)
    assert modal.spent() == 0.0
    assert modal.call("a").text == "hi"


def test_retries_on_429_then_succeeds(tmp_path):
    post = FakePost((429, "slow down"), (503, "busy"), (200, responses_body("ok")))
    r = client(tmp_path, post).call("x")
    assert r.text == "ok" and len(post.calls) == 3


def test_gives_up_after_four_attempts(tmp_path):
    post = FakePost(*[(500, "boom")] * 4)
    with pytest.raises(LLMError):
        client(tmp_path, post).call("x")
    assert len(post.calls) == 4


def test_400_is_not_retried_and_shows_the_message(tmp_path):
    post = FakePost((400, {"error": "unsupported parameter: temperature"}))
    with pytest.raises(LLMError) as e:
        client(tmp_path, post).call("x", temperature=0.0)
    assert "unsupported parameter" in str(e.value) and len(post.calls) == 1


def test_network_error_is_retried(tmp_path):
    post = FakePost(OSError("connection reset"), (200, responses_body("ok")))
    assert client(tmp_path, post).call("x").text == "ok"


def test_failed_calls_cost_nothing(tmp_path):
    c = client(tmp_path, FakePost(*[(500, "x")] * 4))
    with pytest.raises(LLMError):
        c.call("x")
    assert c.spent() == 0.0


def test_ledger_records_paid_calls_only(tmp_path):
    c = client(tmp_path, FakePost((200, responses_body())))
    c.call("x", tag="prog:translate")
    c.call("x", tag="prog:translate")           # cache hit: no ledger line
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["tag"] == "prog:translate"


def test_payload_shapes(tmp_path):
    post = FakePost((200, responses_body()), (200, chat_body()))
    client(tmp_path, post).call("hello", system="rules")
    _, headers, pl = post.calls[0]
    assert pl["input"][0]["content"][0] == {"type": "input_text", "text": "hello"}
    assert pl["instructions"] == "rules" and pl["reasoning"] == {"effort": "low"}
    assert "temperature" not in pl and headers["Authorization"] == "Bearer k"
    client(tmp_path, post, provider="modal").call("hello", system="rules")
    _, _, pl2 = post.calls[1]
    assert pl2["messages"][0] == {"role": "system", "content": "rules"} and "reasoning_effort" not in pl2


def test_missing_credentials_message(tmp_path):
    c = LLMClient("meta", state_dir=tmp_path, env={}, post=FakePost())
    with pytest.raises(LLMError) as e:
        c.call("x")
    assert "META_API_URL" in str(e.value)


def test_modal_requires_a_model_name(tmp_path):
    with pytest.raises(LLMError):
        LLMClient("modal", state_dir=tmp_path, env={}, post=FakePost())


def test_salt_forces_a_fresh_sample_but_is_not_sent(tmp_path):
    post = FakePost((200, responses_body("a")), (200, responses_body("b")))
    c = client(tmp_path, post)
    r1 = c.call("p"); r2 = c.call("p", salt="sample1"); r3 = c.call("p", salt="sample1")
    assert (r1.text, r2.text, r3.text) == ("a", "b", "b") and r3.cached
    assert "salt" not in json.dumps(post.calls[1][2])


def test_modal_uses_documented_default_url_and_bearer_proxy_token(tmp_path):
    env = {"MODAL_API_KEY": "wk-abc.ws-def", "MODAL_MODEL": "spark.us-west.modal.direct"}
    post = FakePost((200, chat_body()))
    LLMClient("modal", state_dir=tmp_path, post=post, env=env).call("hi")
    url, headers, payload = post.calls[0]
    assert url == "https://inference.us-west.modal.direct/v1/chat/completions"
    assert headers["Authorization"] == "Bearer wk-abc.ws-def"
    assert payload["model"] == "spark.us-west.modal.direct"


def test_wire_override_switches_modal_to_responses_format(tmp_path):
    env = {"MODAL_API_KEY": "k", "MODAL_MODEL": "m", "MODAL_WIRE": "responses"}
    post = FakePost((200, responses_body("ok")))
    c = LLMClient("modal", state_dir=tmp_path, post=post, env=env)
    assert c.call("hi", effort="low").text == "ok"
    assert post.calls[0][2]["reasoning"] == {"effort": "low"} and "input" in post.calls[0][2]


def test_baseten_defaults_follow_the_hackathon_guide(tmp_path):
    post = FakePost((200, chat_body()))
    LLMClient("baseten", state_dir=tmp_path, post=post, env={"BASETEN_API_KEY": "bk"}).call("hi")
    url, headers, payload = post.calls[0]
    assert url == "https://inference.baseten.co/v1/chat/completions"
    assert payload["model"] == "meta-models/muse-spark-open-1026"
    assert headers["Authorization"] == "Bearer bk"


def test_truncated_reply_is_billed_and_recorded_but_not_cached(tmp_path):
    body = chat_body()
    body["choices"][0]["finish_reason"] = "length"
    body["usage"] = {"prompt_tokens": 1000, "completion_tokens": 4000}
    post = FakePost((200, body), (200, chat_body("fixed")))
    c = client(tmp_path, post, provider="baseten")
    with pytest.raises(LLMTruncated) as e:
        c.call("x")
    expected = (1000 * 1.25 + 4000 * 4.25) / 1e6
    assert e.value.cost_usd == pytest.approx(expected) and c.spent() == pytest.approx(expected)
    assert c.call("x").text == "fixed"          # the failure was not cached


def test_baseten_sends_a_large_output_cap_and_env_can_override(tmp_path):
    post = FakePost((200, chat_body()), (200, chat_body()))
    client(tmp_path, post, provider="baseten").call("a")
    assert post.calls[0][2]["max_tokens"] == 32000
    env = dict(ENV, BASETEN_API_KEY="k", BASETEN_MAX_OUTPUT_TOKENS="1234")
    LLMClient("baseten", state_dir=tmp_path, post=post, env=env, sleep=lambda s: None).call("b")
    assert post.calls[1][2]["max_tokens"] == 1234