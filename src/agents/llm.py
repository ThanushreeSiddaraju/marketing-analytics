"""A small tool-use loop on the Anthropic SDK, shared by all the agents.

I wrote the loop by hand instead of using the SDK's tool runner because every
SQL call has to land in the ledger with an id the model can cite, and because
the tests swap in a fake client to run the agents without an API key.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")


def make_client():
    import anthropic  # imported here so the offline tests don't need a key
    return anthropic.Anthropic()


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[[dict], str]

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema, "strict": True}


class ToolError(Exception):
    """Raised by a tool function; the message goes back to the model as an error result."""


class AgentFailed(RuntimeError):
    pass


@dataclass
class AgentRun:
    output: dict
    messages: list = field(default_factory=list)
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def obj_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required if required is not None else list(properties), "additionalProperties": False}


def run_agent(client, *, system: str, messages: list, output_schema: dict, tools: list[Tool] = (),
              effort: str = "medium", max_turns: int = 12, max_tokens: int = 16000, model: str = MODEL) -> AgentRun:
    """Call the model until it stops asking for tools, then parse its JSON answer.

    `messages` is used as-is and extended in place, so a caller can append
    feedback and call again to continue the same conversation.
    """
    by_name = {t.name: t for t in tools}
    run = AgentRun(output={}, messages=messages)
    for _ in range(max_turns):
        kwargs: dict[str, Any] = dict(
            model=model, max_tokens=max_tokens, system=system, messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": output_schema}},
        )
        if tools:
            kwargs["tools"] = [t.spec() for t in tools]
        resp = client.messages.create(**kwargs)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            run.input_tokens += getattr(usage, "input_tokens", 0) or 0
            run.output_tokens += getattr(usage, "output_tokens", 0) or 0
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "refusal":
            raise AgentFailed("the model declined this request")
        if resp.stop_reason == "max_tokens":
            raise AgentFailed("ran out of output tokens before finishing")
        if resp.stop_reason == "pause_turn":
            continue
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            text = "".join(b.text for b in resp.content if b.type == "text")
            try:
                run.output = json.loads(text)
            except json.JSONDecodeError as e:
                raise AgentFailed(f"final answer wasn't valid JSON: {e}") from None
            return run

        results = []
        for call in calls:
            run.tool_calls += 1
            tool = by_name.get(call.name)
            try:
                if tool is None:
                    raise ToolError(f"no tool called {call.name}")
                content, is_error = tool.fn(call.input), False
            except ToolError as e:
                content, is_error = f"Error: {e}", True
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    raise AgentFailed(f"no final answer after {max_turns} turns")
