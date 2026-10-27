import os, json, hashlib, time, pathlib, requests

URL = os.environ["META_API_URL"]          # full endpoint from working call
KEY = os.environ["MODEL_API_KEY"]
CACHE = pathlib.Path(".cache/llm"); CACHE.mkdir(parents=True, exist_ok=True)
SPEND_FILE = pathlib.Path(".cache/spend.json")
MAX_SPEND = float(os.environ.get("MAX_SPEND_USD", "40"))
PRICE_IN = float(os.environ["PRICE_IN_PER_M"])    # $ per 1M input tokens, from Model list
PRICE_OUT = float(os.environ["PRICE_OUT_PER_M"])  # $ per 1M output tokens

def _spent():
    return json.loads(SPEND_FILE.read_text())["usd"] if SPEND_FILE.exists() else 0.0

def call(model, prompt, effort="low", temperature=0.0, tag=""):
    payload = {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "reasoning": {"effort": effort},
        "temperature": temperature,
        "stream": False,
    }
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    f = CACHE / f"{key}.json"
    if f.exists():
        return json.loads(f.read_text())          # cache hit: free

    if _spent() >= MAX_SPEND:
        raise RuntimeError(f"Spend cap ${MAX_SPEND} reached")

    for attempt in range(4):
        r = requests.post(URL, json=payload, timeout=120,
                          headers={"Authorization": f"Bearer {KEY}"})
        if r.status_code in (429, 500, 502, 503):
            time.sleep(2 ** attempt); continue
        r.raise_for_status(); break
    data = r.json()

    text = "".join(
        c["text"] for item in data["output"] if item["type"] == "message"
        for c in item["content"] if c["type"] == "output_text")
    u = data["usage"]
    cost = (u["input_tokens"] * PRICE_IN + u["output_tokens"] * PRICE_OUT) / 1e6
    SPEND_FILE.write_text(json.dumps({"usd": _spent() + cost}))

    result = {"text": text, "usage": u, "cost_usd": cost, "model": model, "tag": tag}
    f.write_text(json.dumps(result))
    return result