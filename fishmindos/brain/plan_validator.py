"""Lightweight plan validator for the current FishMindOS architecture."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


class PlanValidator:
    """
    Validate only high-level planning requirements.

    The current system exposes just two LLM-visible tools:
    - submit_mission
    - system_status

    Older validator logic tried to infer missing micro-skills such as audio/light
    from keywords. That no longer matches the current architecture and causes
    false positives such as treating "告诉我" as a broadcast request.
    """

    STATUS_KEYWORDS = (
        "状态",
        "电量",
        "电池",
        "充电",
        "在充电吗",
        "位置",
        "在哪",
        "在哪儿",
        "现在怎么样",
        "情况",
    )

    WORLD_QUERY_KEYWORDS = (
        "有哪些点",
        "有哪些地点",
        "有哪些路点",
        "这里有哪些点",
        "这里有哪些地点",
        "这里有什么点",
        "这里有什么地点",
        "可用地点",
        "地点列表",
        "路点列表",
        "列出地点",
        "列出路点",
        "哪些地点可以去",
        "哪些地方可以去",
        "有哪些地方可以去",
        "能去哪些地方",
        "能去哪些位置",
        "可以去哪些地方",
        "可以去哪些位置",
    )

    ACTION_KEYWORDS = (
        "去",
        "到",
        "前往",
        "返回",
        "回来",
        "回去",
        "回充",
        "关灯",
        "开灯",
        "亮灯",
        "播报",
        "播放",
        "说",
        "拿",
        "取",
        "送",
        "停止导航",
        "关闭导航",
        "取消导航",
    )

    def validate_plan(self, user_input: str, steps: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        issues: List[str] = []
        if not steps:
            return False, ["LLM 未生成任何步骤"]

        skill_names = [str(step.get("skill", "")) for step in steps]
        has_submit_mission = "submit_mission" in skill_names
        has_system_status = "system_status" in skill_names
        has_world_list_locations = "world_list_locations" in skill_names

        if has_submit_mission:
            for step in steps:
                if step.get("skill") != "submit_mission":
                    continue
                params = step.get("params") or {}
                tasks = params.get("tasks") if isinstance(params, dict) else None
                if isinstance(tasks, list) and tasks:
                    return True, []
            return False, ["submit_mission 已生成，但 tasks 为空"]

        if self._looks_like_world_locations_query(user_input):
            if has_world_list_locations:
                return True, []
            return False, ["这是地点查询，但规划中没有 world_list_locations"]

        if self._looks_like_status_query(user_input):
            if has_system_status:
                return True, []
            return False, ["这是状态查询，但规划中没有 system_status"]

        if self._looks_like_action_request(user_input):
            return False, ["这是动作请求，但规划中没有 submit_mission"]

        if has_system_status:
            return True, []

        return True, issues

    def get_improvement_hint(self, issues: List[str]) -> str:
        if not issues:
            return ""

        lines = ["### 规划审查反馈", "检测到以下问题，请修正规划："]
        for idx, issue in enumerate(issues, 1):
            lines.append(f"{idx}. {issue}")

        lines.append("")
        if any("submit_mission" in issue for issue in issues):
            lines.append("请改为一次 submit_mission 调用，并确保 tasks 数组完整。")
        if any("system_status" in issue for issue in issues):
            lines.append("请改为调用 system_status，并直接给出文字答复。")
        if any("world_list_locations" in issue for issue in issues):
            lines.append("请改为调用 world_list_locations，并直接返回地点列表。")
        if any("tasks 为空" in issue for issue in issues):
            lines.append("请在 submit_mission 中填入至少一个有效 action。")
        return "\n".join(lines)

    def _looks_like_status_query(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        if self._looks_like_action_request(text):
            return False
        return any(keyword in text for keyword in self.STATUS_KEYWORDS)

    def _looks_like_world_locations_query(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        return any(keyword in text for keyword in self.WORLD_QUERY_KEYWORDS)

    def _looks_like_action_request(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        return any(keyword in text for keyword in self.ACTION_KEYWORDS)
