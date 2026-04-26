"""Quickstart: one chat completion through usai-harness.

Assumes you have run `usai-harness init` and configured at least one provider.
The default provider is `usai`; this script lets the harness pick the default
model from the live catalog. To target a specific provider or model, pass
them via the `provider` and `model` arguments.

Run from the project root:

    python docs/examples/01_quickstart.py
"""

import asyncio

from usai_harness import USAiClient


async def main() -> None:
    async with USAiClient(project="quickstart-example") as client:
        response = await client.complete(
            messages=[
                {"role": "user", "content": "In one sentence, what is the OpenAI chat-completions API?"},
            ],
            # Gemini 2.5 reserves part of the budget for thinking tokens; see
            # docs/ops-guide.md section 7.2. 512 is a comfortable floor that
            # also works for non-thinking models.
            max_tokens=512,
        )

    content = response["choices"][0]["message"]["content"]
    usage = response.get("usage") or {}

    print("Response:")
    print(content)
    print()
    print(f"  model_returned   : {response.get('model')}")
    print(f"  prompt_tokens    : {usage.get('prompt_tokens')}")
    print(f"  completion_tokens: {usage.get('completion_tokens')}")
    print(f"  total_tokens     : {usage.get('total_tokens')}")


if __name__ == "__main__":
    asyncio.run(main())
