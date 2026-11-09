"""Gemini live check (D25): which usage fields does the endpoint return?

The owner runs this by hand with a real key. It sends one tiny request to
`<GOOGLE_GEMINI_BASE_URL>/responses` and prints only the NAMES and TYPES of the
usage fields. It never prints a key, a value, the request or the response text.

Usage:  uv run python scripts/check_gemini_usage.py --list
        uv run python scripts/check_gemini_usage.py <model id>
Reads:  GOOGLE_GEMINI_BASE_URL and GEMINI_API_KEY from the environment.
"""

import json
import os
import sys
import urllib.error
import urllib.request

REQUIRED = ("input_tokens", "output_tokens")
OPTIONAL = (
    "input_tokens_details.cached_tokens",
    "input_tokens_details.cache_write_tokens",
)


def describe(usage: dict) -> dict[str, str]:
    """Return {field name: type name} for the usage object, one level deep."""
    found: dict[str, str] = {}
    for key, value in usage.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                found[f"{key}.{sub_key}"] = type(sub_value).__name__
        else:
            found[key] = type(value).__name__
    return found


def error_fields(err: urllib.error.HTTPError) -> dict:
    """Return only the type, param and code of a JSON error. Never the message."""
    try:
        error = json.loads(err.read().decode("utf-8")).get("error")
    except (ValueError, AttributeError):
        return {"body": "not JSON (often an edge firewall)"}
    if not isinstance(error, dict):
        return {}
    return {k: error[k] for k in ("type", "param", "code") if isinstance(error.get(k), str)}


def send(base_url: str, api_key: str, path: str, body: dict | None) -> urllib.request.Request:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "llm-adapter-check/0.1",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    return urllib.request.Request(  # noqa: S310 - URL comes from the owner's config
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method="POST" if body is not None else "GET",
    )


def list_models(base_url: str, api_key: str) -> int:
    try:
        with urllib.request.urlopen(send(base_url, api_key, "/models", None), timeout=60) as reply:  # noqa: S310
            payload = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        print(f"HTTP {err.code}. error fields: {error_fields(err)}")
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        print(f"failed: {type(err).__name__}")
        return 1
    data = payload.get("data") if isinstance(payload, dict) else None
    ids = sorted(
        m["id"] for m in data or [] if isinstance(m, dict) and isinstance(m.get("id"), str)
    )
    gemini = [i for i in ids if "gemini" in i.lower()]
    print(f"{len(ids)} models. Gemini models:")
    for model_id in gemini:
        print(f"  {model_id}")
    if not gemini:
        print("  none")
    return 0 if gemini else 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_gemini_usage.py --list | <model id>")
        return 2
    model = sys.argv[1]
    base_url = os.environ.get("GOOGLE_GEMINI_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    missing = [
        name
        for name, value in (
            ("GOOGLE_GEMINI_BASE_URL", base_url),
            ("GEMINI_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        print("not set: " + ", ".join(missing))
        return 2
    if model == "--list":
        return list_models(base_url, api_key)

    body = {"model": model, "input": "Say hi.", "max_output_tokens": 64}
    request = send(base_url, api_key, "/responses", body)
    try:
        with urllib.request.urlopen(request, timeout=60) as reply:  # noqa: S310
            payload = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        print(f"HTTP {err.code}. The body is not shown.")
        print(f"error fields: {error_fields(err)}")
        print("Check the base URL, the key and the model id. List the models with --list.")
        return 1
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        print(f"failed: {type(err).__name__}")
        return 1

    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        print("RESULT: the response has no `usage` object.")
        print("top-level keys: " + ", ".join(sorted(payload)) if isinstance(payload, dict) else "")
        return 1

    found = describe(usage)
    print("usage fields returned (name: type):")
    for name in sorted(found):
        print(f"  {name}: {found[name]}")
    print("the adapter needs (D25):")
    for name in REQUIRED:
        print(f"  {name}: {'present' if name in found else 'MISSING'}")
    print("the adapter reads if present (D25):")
    for name in OPTIONAL:
        print(f"  {name}: {'present' if name in found else 'absent'}")
    return 0 if all(name in found for name in REQUIRED) else 1


if __name__ == "__main__":
    sys.exit(main())
