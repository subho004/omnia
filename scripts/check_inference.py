"""Verify OpenRouter; --smoke spends at most five bounded, synthetic free-model requests."""

import argparse
import asyncio
import json
import time

import httpx

from claw_orchestrator.config import Settings
from claw_orchestrator.inference import InferenceCheckError, openrouter_preflight


async def check(smoke: bool):
    settings = Settings()
    if settings.inference_provider != "openrouter":
        raise InferenceCheckError("Select INFERENCE_PROVIDER=openrouter first")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
        preflight = await openrouter_preflight(settings, client)
        print(json.dumps({"preflight": "passed", **preflight}), flush=True)
        if not smoke:
            return
        request_count = 5 if preflight["supports_structured_output"] else 4
        if preflight["free_model_daily_requests"].get("remaining", request_count) < request_count:
            raise InferenceCheckError("Insufficient free requests remain; smoke was not started")
        headers = {"Authorization": "Bearer " + settings.openrouter_api_key.get_secret_value()}
        base = {
            "model": settings.openrouter_model,
            "max_tokens": 256,
            "reasoning": {"enabled": False},
            "provider": {
                "require_parameters": True,
                "max_price": {"prompt": 0, "completion": 0},
            },
        }

        async def request(label, **body):
            start = time.monotonic()
            response = await client.post(
                settings.openrouter_base_url + "/chat/completions",
                headers=headers,
                json={**base, **body},
            )
            if response.status_code != 200:
                raise InferenceCheckError(
                    f"{label}: HTTP {response.status_code}; no automatic retry"
                )
            data = response.json()
            if "error" in data or not data.get("choices"):
                raise InferenceCheckError(f"{label}: provider did not complete the request")
            usage = data.get("usage", {})
            print(
                json.dumps(
                    {
                        "check": label,
                        "seconds": round(time.monotonic() - start, 2),
                        "usage": {
                            k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "cost")
                        },
                    }
                ),
                flush=True,
            )
            return data["choices"][0]["message"]

        text = await request(
            "short_reply", messages=[{"role": "user", "content": "Reply exactly READY."}]
        )
        if text.get("content", "").strip().rstrip(".") != "READY":
            raise InferenceCheckError("short_reply: unexpected answer")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_demo_numbers",
                    "description": "Add two synthetic demo integers.",
                    "parameters": {
                        "type": "object",
                        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                        "required": ["a", "b"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        messages = [{"role": "user", "content": "Use add_demo_numbers to add 17 and 25."}]
        call = await request(
            "tool_arguments",
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        calls = call.get("tool_calls", [])
        if len(calls) != 1 or calls[0].get("function", {}).get("name") != "add_demo_numbers":
            raise InferenceCheckError("tool_arguments: wrong tool or call count")
        if json.loads(calls[0]["function"]["arguments"]) != {"a": 17, "b": 25}:
            raise InferenceCheckError("tool_arguments: wrong arguments")
        # The only executed tool is this validated local arithmetic; no arbitrary model code.
        messages += [call, {"role": "tool", "tool_call_id": calls[0]["id"], "content": "42"}]
        result = ""
        finished = False
        async with client.stream(
            "POST",
            settings.openrouter_base_url + "/chat/completions",
            headers=headers,
            json={
                **base,
                "messages": messages,
                "tools": tools,
                "tool_choice": "none",
                "stream": True,
            },
        ) as response:
            if response.status_code != 200:
                raise InferenceCheckError(f"stream: HTTP {response.status_code}; no retry")
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                if line == "data: [DONE]":
                    finished = True
                    break
                data = json.loads(line[6:])
                if "error" in data:
                    raise InferenceCheckError("stream: provider returned an error")
                for choice in data.get("choices", []):
                    if choice.get("finish_reason") == "error":
                        raise InferenceCheckError("stream: failed after headers")
                    result += choice.get("delta", {}).get("content") or ""
        if not finished or "42" not in result:
            raise InferenceCheckError("stream: missing terminal event or tool-result answer")
        print(json.dumps({"check": "streamed_tool_result", "passed": True}), flush=True)
        if preflight["supports_structured_output"]:
            structured = await request(
                "structured_output",
                messages=[{"role": "user", "content": "Return status ready."}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "status",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {"status": {"type": "string", "enum": ["ready"]}},
                            "required": ["status"],
                            "additionalProperties": False,
                        },
                    },
                },
            )
            if json.loads(structured.get("content", "")) != {"status": "ready"}:
                raise InferenceCheckError("structured_output: schema mismatch")
        else:
            print(
                json.dumps({"check": "structured_output", "status": "unsupported; skipped"}),
                flush=True,
            )
        context = "Synthetic marker: MORROW_TEST_742.\n" + "\n".join(
            f"Demo row {i}: this synthetic note contains no customer data." for i in range(220)
        )
        recall = await request(
            "context_recall",
            messages=[
                {"role": "user", "content": context},
                {"role": "assistant", "content": "Noted."},
                {"role": "user", "content": "Return only the synthetic marker from the beginning."},
            ],
        )
        if "MORROW_TEST_742" not in recall.get("content", ""):
            raise InferenceCheckError("context_recall: marker missing")
        print(
            json.dumps(
                {
                    "smoke": "passed",
                    "inference_requests": request_count,
                    "scope": "Direct provider only; native runtime not exercised",
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    try:

        async def bounded_check():
            async with asyncio.timeout(180):
                await check(args.smoke)

        asyncio.run(bounded_check())
    except InferenceCheckError as error:
        raise SystemExit(str(error)) from None
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError):
        # No traceback, upstream body, request headers or response text in operator output.
        raise SystemExit(
            "Inference check failed; credentials and upstream bodies omitted."
        ) from None
