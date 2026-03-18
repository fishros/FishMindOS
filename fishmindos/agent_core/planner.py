from __future__ import annotations

from dataclasses import dataclass

from fishmindos.mcp import LocalMCPClient
from fishmindos.models import InteractionEvent, PlannedSkillCall, TaskSequence

from .fastpath import FastPathPlanner
from .llm import OpenAICompatibleLLMClient


# Tools that only read state — safe to call during planning for LLM context
_QUERY_ACTIONS = {
    "list_maps", "list_tasks", "list_chains", "list_presets",
    "current_position", "navigation_status", "battery_soc",
    "charging_status", "describe_task", "show_chain",
}

MAX_AGENT_TURNS = 5


class LLMTaskPlanner:
    """Use the configured LLM plus MCP-discovered tools to build a task sequence.

    Runs an agentic loop: the LLM can call query/lookup tools first to gather
    information, then issue control tool calls. The loop runs until the LLM
    stops requesting tool calls or MAX_AGENT_TURNS is reached.
    """

    def __init__(
        self,
        mcp_client: LocalMCPClient,
        client: OpenAICompatibleLLMClient,
    ) -> None:
        self.mcp_client = mcp_client
        self.client = client

    @classmethod
    def from_env(cls, mcp_client: LocalMCPClient) -> LLMTaskPlanner | None:
        client = OpenAICompatibleLLMClient.from_env()
        if client is None:
            return None
        return cls(mcp_client=mcp_client, client=client)

    def plan_event(
        self,
        event: InteractionEvent,
        on_tool_call: object = None,
    ) -> TaskSequence:
        """Plan a task sequence using an agentic loop.

        Args:
            event: The interaction event to plan for.
            on_tool_call: Optional callable(name, args) invoked before each tool call.
        """
        import json as _json

        all_tools = self.mcp_client.list_tools()
        if not all_tools:
            return TaskSequence(goal=event.text, steps=[], planner_source="llm")

        prompt_documents = self.mcp_client.read_planning_bundle()
        system_prompt = self.client.build_system_prompt(
            prompt_mode=self.client.prompt_mode,
            prompt_documents=prompt_documents,
        )

        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": self.client._build_user_prompt(event)},
        ]

        final_steps: list[PlannedSkillCall] = []

        for _turn in range(MAX_AGENT_TURNS):
            result = self.client.chat(messages=messages, tools=all_tools, tool_choice="auto")

            if not result.tool_calls:
                # LLM decided to reply in text — no more tool calls
                reply = result.assistant_text.strip()
                if reply:
                    return TaskSequence(goal=event.text, steps=[], planner_source="llm", reply_text=reply)
                break

            # Append assistant turn with tool_calls to history
            assistant_msg: dict = {
                "role": "assistant",
                "content": result.assistant_text or None,
                "tool_calls": [
                    {
                        "id": c.get("id", f"call_{i}"),
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": _json.dumps(c.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for i, c in enumerate(result.tool_calls)
                ],
            }
            messages.append(assistant_msg)

            # Execute each tool call; separate query tools from action tools
            has_action = False
            for call in result.tool_calls:
                name = str(call.get("name", "")).strip()
                call_id = call.get("id", "")
                args = dict(call.get("arguments", {}))

                if not name or not self.mcp_client.has_tool(name):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": _json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False),
                    })
                    continue

                if callable(on_tool_call):
                    on_tool_call(name, args)

                action = str(args.get("action", "")).strip()
                is_query = action in _QUERY_ACTIONS

                # Only execute query tools during planning so LLM can use the result.
                # Control tools are collected and handed to the executor later.
                if is_query:
                    try:
                        tool_result = self.mcp_client.call_tool(name, arguments=args, context=event.context)
                        result_content = _json.dumps(tool_result, ensure_ascii=False)
                    except Exception as exc:
                        result_content = _json.dumps({"error": str(exc)}, ensure_ascii=False)
                else:
                    result_content = _json.dumps({"ok": True, "queued": True}, ensure_ascii=False)

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_content,
                })

                # Collect as a planned step regardless — executor will run them
                final_steps.append(PlannedSkillCall(skill=name, args=args, on_fail="abort"))
                has_action = True

            if not has_action:
                # All calls were unknown — let LLM respond
                continue

        if final_steps:
            return TaskSequence(goal=event.text, steps=final_steps, planner_source="llm")
        return TaskSequence(goal=event.text, steps=[], planner_source="llm")


@dataclass
class HybridTaskPlanner:
    mcp_client: LocalMCPClient
    quick_planner: FastPathPlanner
    llm_planner: LLMTaskPlanner | None = None

    @classmethod
    def from_env(cls, mcp_client: LocalMCPClient) -> HybridTaskPlanner:
        return cls(
            mcp_client=mcp_client,
            quick_planner=FastPathPlanner.from_env(),
            llm_planner=LLMTaskPlanner.from_env(mcp_client),
        )

    def plan_event(self, event: InteractionEvent, on_tool_call: object = None) -> TaskSequence:
        quick_sequence = self.quick_planner.plan_event(event)
        if quick_sequence is not None:
            return quick_sequence

        if self.llm_planner is None:
            raise RuntimeError("No available planner for this request.")

        llm_sequence = self.llm_planner.plan_event(event, on_tool_call=on_tool_call)
        if llm_sequence.steps or llm_sequence.reply_text:
            return llm_sequence

        return TaskSequence(
            goal=event.text,
            steps=[],
            planner_source="fallback",
            reply_text="汪，这句我还没完全听懂。你可以直接说去哪里、执行哪个任务、创建任务链，或者问我地图和状态。",
        )


QuickCommandPlanner = FastPathPlanner
