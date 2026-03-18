from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib import error, request

from fishmindos.config import get_config_value
from fishmindos.models import InteractionEvent


class LLMClientError(RuntimeError):
    """Raised when the remote LLM API cannot return a usable planning payload."""


DEFAULT_TOOL_SYSTEM_PROMPT = """You are the FishMindOS task planner.
You are the FishMindOS robot planner.
Your primary job is to convert user input into executable robot tool calls.

Rules:
1. Prefer executable plans over explanations for real robot tasks.
2. Only use tools that are actually provided.
3. Only use arguments that come from the user input, runtime context, or prior lookup results.
4. Never invent IDs, coordinates, or device state.
5. If required information is missing, ask one short clarification question or prefer lookup/query tools before control tools.
6. High-risk actions such as delete, overwrite, or motion control should only be planned when the user request is explicit.
7. If the user is only asking identity, capability, greeting, or a short clarification question, you may answer with one short Chinese sentence and no tools.
8. If the provider does not support native tool_calls, output strict JSON:
   {"steps":[{"name":"tool_name","arguments":{"action":"..."}}]}
"""

PROVIDER_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "gpt": "https://api.openai.com/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "bigmodel": "https://open.bigmodel.cn/api/paas/v4",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_intl": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "claude": "https://api.anthropic.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
IDENTITY_GUIDE_PATH = REPO_ROOT / "IDENTITY.md"
SOUL_GUIDE_PATH = REPO_ROOT / "SOUL.md"
USER_GUIDE_PATH = REPO_ROOT / "USER.md"
AGENT_GUIDE_PATH = REPO_ROOT / "AGENT.md"
TOOLS_GUIDE_PATH = REPO_ROOT / "TOOLS.md"
TASK_SPEC_PATH = REPO_ROOT / "TASK_SPEC.md"


@dataclass
class LLMPlanningResult:
    tool_calls: list[dict[str, Any]]
    assistant_text: str = ""


@dataclass
class OpenAICompatibleLLMClient:
    """Minimal HTTP client for OpenAI-compatible chat completion APIs."""

    provider: str
    api_url: str
    model: str
    api_key: str | None = None
    timeout_sec: int = 30
    prompt_mode: str = "full"

    @classmethod
    def from_env(cls) -> OpenAICompatibleLLMClient | None:
        provider = str(get_config_value("llm", "provider", "FISHMINDOS_LLM_PROVIDER", default="")).strip().lower()
        base_url = get_config_value("llm", "base_url", "FISHMINDOS_LLM_BASE_URL")
        api_url = get_config_value("llm", "api_url", "FISHMINDOS_LLM_API_URL")
        if not api_url:
            if not base_url and provider:
                base_url = PROVIDER_DEFAULT_BASE_URLS.get(provider)
            if base_url:
                api_url = cls._build_chat_completions_url(str(base_url))

        model = get_config_value("llm", "model", "FISHMINDOS_LLM_MODEL")
        if not api_url or not model:
            return None

        timeout_raw = get_config_value("llm", "timeout_sec", "FISHMINDOS_LLM_TIMEOUT_SEC", default="30")
        try:
            timeout_sec = max(1, int(timeout_raw))
        except ValueError:
            timeout_sec = 30

        prompt_mode = str(
            get_config_value("llm", "prompt_mode", "FISHMINDOS_LLM_PROMPT_MODE", default="full")
        ).strip().lower() or "full"

        return cls(
            provider=provider or "custom",
            api_url=str(api_url),
            model=str(model),
            api_key=get_config_value("llm", "api_key", "FISHMINDOS_LLM_API_KEY"),
            timeout_sec=timeout_sec,
            prompt_mode=prompt_mode,
        )

    @staticmethod
    def supported_providers() -> list[str]:
        return sorted(PROVIDER_DEFAULT_BASE_URLS.keys())

    @staticmethod
    def _build_chat_completions_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    @staticmethod
    @lru_cache(maxsize=16)
    def _load_prompt_file(path: str) -> str:
        file_path = Path(path)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8").strip()

    @classmethod
    def _default_prompt_documents(
        cls,
        identity_doc_path: str | Path | None = None,
        soul_doc_path: str | Path | None = None,
        user_doc_path: str | Path | None = None,
        agent_doc_path: str | Path | None = None,
        tools_doc_path: str | Path | None = None,
        task_spec_path: str | Path | None = None,
    ) -> dict[str, str]:
        return {
            "identity": cls._load_prompt_file(str(identity_doc_path or IDENTITY_GUIDE_PATH)),
            "soul": cls._load_prompt_file(str(soul_doc_path or SOUL_GUIDE_PATH)),
            "user": cls._load_prompt_file(str(user_doc_path or USER_GUIDE_PATH)),
            "agent": cls._load_prompt_file(str(agent_doc_path or AGENT_GUIDE_PATH)),
            "tools": cls._load_prompt_file(str(tools_doc_path or TOOLS_GUIDE_PATH)),
            "task_spec": cls._load_prompt_file(str(task_spec_path or TASK_SPEC_PATH)),
        }

    @classmethod
    def build_system_prompt(
        cls,
        identity_doc_path: str | Path | None = None,
        soul_doc_path: str | Path | None = None,
        user_doc_path: str | Path | None = None,
        agent_doc_path: str | Path | None = None,
        tools_doc_path: str | Path | None = None,
        task_spec_path: str | Path | None = None,
        prompt_mode: str = "full",
        prompt_documents: Mapping[str, str] | None = None,
    ) -> str:
        mode = (prompt_mode or "full").strip().lower()
        parts = [DEFAULT_TOOL_SYSTEM_PROMPT]
        if mode == "minimal":
            return "\n\n".join(parts)

        documents = dict(
            prompt_documents
            if prompt_documents is not None
            else cls._default_prompt_documents(
                identity_doc_path=identity_doc_path,
                soul_doc_path=soul_doc_path,
                user_doc_path=user_doc_path,
                agent_doc_path=agent_doc_path,
                tools_doc_path=tools_doc_path,
                task_spec_path=task_spec_path,
            )
        )

        identity_text = documents.get("identity", "").strip()
        if identity_text:
            parts.append("Identity:\n" + identity_text)

        soul_text = documents.get("soul", "").strip()
        if soul_text:
            parts.append("Style:\n" + soul_text)

        user_text = documents.get("user", "").strip()
        if user_text:
            parts.append("User preferences:\n" + user_text)

        agent_text = documents.get("agent", "").strip()
        if agent_text:
            parts.append("Agent policy:\n" + agent_text)

        if mode == "agent_only":
            return "\n\n".join(parts)

        task_spec_text = documents.get("task_spec", "").strip()
        if task_spec_text:
            parts.append("Task contract:\n" + task_spec_text)

        tools_text = documents.get("tools", "").strip()
        if tools_text:
            parts.append("Tool semantics:\n" + tools_text)

        return "\n\n".join(parts)

    def plan_response(
        self,
        event: InteractionEvent,
        tools: list[dict[str, Any]],
        prompt_documents: Mapping[str, str] | None = None,
        extra_messages: list[dict[str, Any]] | None = None,
    ) -> LLMPlanningResult:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    prompt_mode=self.prompt_mode,
                    prompt_documents=prompt_documents,
                ),
            },
            {"role": "user", "content": self._build_user_prompt(event)},
        ]
        if extra_messages:
            messages.extend(extra_messages)
        raw_response = self._create_completion(
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        return self._extract_planning_result(raw_response)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMPlanningResult:
        """Send an arbitrary message list and return a planning result."""
        raw_response = self._create_completion(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=0,
        )
        return self._extract_planning_result(raw_response)

    def plan_tool_calls(
        self,
        event: InteractionEvent,
        tools: list[dict[str, Any]],
        prompt_documents: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        return self.plan_response(event, tools, prompt_documents=prompt_documents).tool_calls

    @classmethod
    def _extract_tool_calls(cls, response_data: dict[str, Any]) -> list[dict[str, Any]]:
        return cls._extract_planning_result(response_data).tool_calls

    def _create_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: int | float = 0,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        return self._post_json(payload)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(self.api_url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as resp:
                content = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMClientError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LLMClientError(f"LLM API unavailable: {exc.reason}") from exc

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError("LLM API returned invalid JSON response.") from exc

        if not isinstance(data, dict):
            raise LLMClientError("LLM API response is not a JSON object.")
        return data

    @staticmethod
    def _build_user_prompt(event: InteractionEvent) -> str:
        payload = {
            "text": event.text,
            "source": event.source,
            "robot_id": event.robot_id,
            "context": event.context,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def _extract_planning_result(cls, response_data: dict[str, Any]) -> LLMPlanningResult:
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMClientError("LLM API response does not contain choices.")

        message = choices[0].get("message", {})
        parsed_calls = cls._extract_tool_calls_from_message(message)
        if parsed_calls:
            return LLMPlanningResult(tool_calls=parsed_calls, assistant_text=cls._extract_assistant_text(message.get("content")))

        parsed_from_content = cls._extract_tool_calls_from_content(message.get("content"))
        if parsed_from_content:
            return LLMPlanningResult(tool_calls=parsed_from_content, assistant_text="")

        return LLMPlanningResult(tool_calls=[], assistant_text=cls._extract_assistant_text(message.get("content")))

    @classmethod
    def _extract_tool_calls_from_message(cls, message: Any) -> list[dict[str, Any]]:
        if not isinstance(message, dict):
            return []
        tool_calls = message.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            return []

        parsed_calls: list[dict[str, Any]] = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            function = item.get("function", {})
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            parsed_calls.append(
                {
                    "id": item.get("id", ""),
                    "name": name,
                    "arguments": cls._load_tool_arguments(function.get("arguments", "{}")),
                }
            )
        return parsed_calls

    @classmethod
    def _extract_tool_calls_from_content(cls, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            raw_text = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            )
        elif isinstance(content, str):
            raw_text = content
        else:
            raw_text = ""

        if not raw_text.strip():
            return []

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return []

        if isinstance(payload, dict):
            steps = payload.get("steps")
        elif isinstance(payload, list):
            steps = payload
        else:
            steps = None

        if not isinstance(steps, list):
            return []

        parsed_calls: list[dict[str, Any]] = []
        for index, item in enumerate(steps, start=1):
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool")
            arguments = item.get("arguments") or item.get("args") or {}
            if not isinstance(name, str) or not name:
                continue
            parsed_calls.append(
                {
                    "id": f"content_call_{index}",
                    "name": name,
                    "arguments": cls._load_tool_arguments(arguments),
                }
            )
        return parsed_calls

    @staticmethod
    def _extract_assistant_text(content: Any) -> str:
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            ]
            return "".join(parts).strip()
        if isinstance(content, str):
            return content.strip()
        return ""

    @staticmethod
    def _load_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if raw_arguments in (None, ""):
            return {}
        if not isinstance(raw_arguments, str):
            raise LLMClientError("Tool arguments must be a JSON string or object.")

        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise LLMClientError("Tool arguments are not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise LLMClientError("Tool arguments must be a JSON object.")
        return parsed
