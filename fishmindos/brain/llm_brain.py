"""
FishMindOS - 基于LLM的智能大脑
使用LLM进行意图识别、任务规划和技能调用
"""

import json
import re
import threading
import uuid
from typing import Any, Dict, List, Optional, Generator
from dataclasses import dataclass, field

from fishmindos.skills.base import SkillRegistry
from fishmindos.adapters.fishbot import FishBotAdapter
from fishmindos.brain.llm_providers import LLMProvider, LLMMessage, create_llm_provider
from fishmindos.brain.planner import TaskPlanner
from fishmindos.brain.smart_brain import SmartBrain
from fishmindos.brain.plan_validator import PlanValidator
from fishmindos.config import get_config
from fishmindos.brain.prompt_manager import AgentPromptManager


@dataclass
class BrainResponse:
    """大脑响应"""
    type: str  # thought, plan, action, result, text, error
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)


class TaskPlan:
    """任务计划"""
    def __init__(self, steps: List[Dict[str, Any]]):
        self.steps = steps
        self.current_step = 0
    
    def next_step(self) -> Optional[Dict[str, Any]]:
        """获取下一步"""
        if self.current_step < len(self.steps):
            step = self.steps[self.current_step]
            self.current_step += 1
            return step
        return None
    
    def is_complete(self) -> bool:
        """是否完成"""
        return self.current_step >= len(self.steps)


class LLMBrain:
    """
    基于LLM的智能大脑
    使用大语言模型进行真正的意图理解和任务规划
    """
    
    def __init__(self, registry: SkillRegistry, adapter: FishBotAdapter, 
                 llm_provider: Optional[LLMProvider] = None):
        self.registry = registry
        self.adapter = adapter
        self.planner = TaskPlanner(registry)
        self._cancel_event = threading.Event()
        self._current_plan: Optional[TaskPlan] = None
        
        # 初始化提示词管理器（读取 docs/ 文件夹）
        self.prompt_manager = AgentPromptManager()
        
        # 初始化规划验证器（自适应改进）
        self.plan_validator = PlanValidator()
        
        # 初始化LLM提供商
        if llm_provider is None:
            config = get_config()
            try:
                self.llm = create_llm_provider(config.llm)
                print(f"OK LLM提供商已初始化: {config.llm.provider} ({config.llm.model})")
            except Exception as e:
                print(f"WARN LLM初始化失败: {e}，将使用规则引擎")
                self.llm = None
        else:
            self.llm = llm_provider
        
        # 会话上下文 - 包含对话历史
        self.session_context: Dict[str, Any] = {
            "conversation_history": [],
            "executed_tasks": [],
            "current_location": None,
            "carrying_item": None,
            "last_input": None,
            "last_plan": None,
            "current_intent_type": None,
            "pending_clarification": None,
        }
    
    def _get_system_prompt(self) -> str:
        """构建系统提示词：LLM 只做高层任务编排。"""
        config = get_config()
        identity = config.app.identity
        available_skills = self._get_available_tools("")
        skills_description = "\n".join(
            f"- {tool['function']['name']}: {tool['function']['description']}"
            for tool in available_skills[:30]
        )

        prompt_parts = [
            (
                "你是运行在 FishMindOS 系统上的对话与任务编排角色。"
                "你的对外名字由当前配置中的 identity 或项目 profile 文档定义。"
                "FishMindOS 是系统名，不是你的对话名字。"
                "当用户问你叫什么或你是谁时，使用当前身份字段回答，不要回答自己是 FishMindOS。"
                "你的唯一职责是理解用户意图，"
                "并将动作转化为 JSON 任务流提交给 submit_mission 工具。"
                "不要自己去调用细碎的底层工具，把复杂动作合并到 tasks 数组中一次性提交。"
            ),
            (
                "# 编排规则\n"
                "1. 只要用户要求移动、亮灯、播报或回充，必须且只需调用 submit_mission 一次。\n"
                "2. submit_mission 的 tasks 必须是按执行顺序排列的 JSON 数组。\n"
                "3. 你的可用 action 现在包含：goto, dock, light, speak, wait_confirm, query。\n"
                "4. 参数规则：goto 传 target，light 传 color，speak 传 text，wait_confirm 不需要参数，query 无参数。\n"
                "5. wait_confirm 用于等待人类完成物理交互（如放快递、取外卖、送纸）。\n"
                "6. 只有当用户明确表达“等待/确认后继续”时才使用 wait_confirm；短指令（如“拿纸”）不要默认加 wait_confirm。\n"
                "7. 上面的示例是参考，不是固定模板；你应根据用户真实意图生成 tasks。\n"
                "8. 若取送类任务缺少关键信息（取货地点或送达地点），先用一句自然语言追问，不要立刻调用 submit_mission。\n"
                "9. 不要调用其他底层工具来拆分微操步骤。\n"
                "10. 若用户只是查询状态/电量/是否在充电，只调用 system_status，然后直接文字回复，不要提交 mission。"
            ),
            (
                "# wait_confirm 示例（不是固定模板）\n"
                "遇到“去大厅拿快递送回公司然后充电”这类需求时，必须严格输出：\n"
                "[\n"
                "  {\"action\": \"goto\", \"target\": \"大厅\"},\n"
                "  {\"action\": \"speak\", \"text\": \"请帮我把快递放到篮子上\"},\n"
                "  {\"action\": \"wait_confirm\"},\n"
                "  {\"action\": \"goto\", \"target\": \"公司\"},\n"
                "  {\"action\": \"speak\", \"text\": \"已经取到快递，请拿走\"},\n"
                "  {\"action\": \"wait_confirm\"},\n"
                "  {\"action\": \"dock\"}\n"
                "]"
            ),
            f"# 可用工具\n{skills_description}",
        ]

        world_prompt = self._get_world_prompt_info()
        if world_prompt:
            prompt_parts.append(f"# World 上下文\n{world_prompt}")

        soul_prompt = self._get_soul_prompt_info()
        if soul_prompt:
            prompt_parts.append(f"# Soul 上下文\n{soul_prompt}")

        current_map = self.session_context.get("current_map", {})
        map_info = f"{current_map.get('name', '未加载')}(ID:{current_map.get('id', '无')})" if current_map else "未加载"
        prompt_parts.append(
            "# 当前状态\n"
            f"- 地图: {map_info}\n"
            f"- 位置: {self.session_context.get('current_location', '未知')}\n"
            f"- 身份: {identity}\n"
        )
        return "\n\n---\n\n".join(prompt_parts)

    def _extract_delivery_slots(self, user_input: str) -> Dict[str, Any]:
        text = str(user_input or "").strip()
        normalized = re.sub(r"\s+", "", text.lower())

        fetch_verbs = ["拿", "取", "买", "带", "领"]
        has_fetch_verb = any(v in normalized for v in fetch_verbs)
        has_deliver_verb = any(v in normalized for v in ["送", "交给", "给"])

        # 通用“取送类对象”检测：优先动词后宾语，其次常见对象词。
        has_object_by_pattern = bool(
            re.search(r"(拿|取|买|带|领)([^，。,.!?？！]{1,12})", normalized)
        )
        generic_object_keywords = [
            "咖啡", "奶茶", "饮料", "水",
            "纸", "纸巾", "文件", "包", "包裹", "快递", "外卖",
            "钥匙", "充电器", "药", "物品", "餐",
        ]
        has_object_keyword = any(k in normalized for k in generic_object_keywords)

        is_delivery_intent = bool((has_fetch_verb or has_deliver_verb) and (has_object_by_pattern or has_object_keyword))

        has_source = bool(
            re.search(r"(去|到|从|在)[^，。,.!?？！]{1,14}(拿|取|买|带|领)", normalized)
            or re.search(r"(从)[^，。,.!?？！]{1,14}(拿|取|买|带|领)", normalized)
        )

        has_target = bool(
            re.search(r"(送到|送去|送往|带到|拿到|交给|给)[^，。,.!?？！]{1,16}", normalized)
            or any(
                k in normalized
                for k in ["给我", "送我", "拿给我", "带给我", "送回来", "拿回来", "带回来", "送过来", "拿过来", "带过来"]
            )
        )

        return {
            "is_delivery_intent": is_delivery_intent,
            "has_source": has_source,
            "has_target": has_target,
        }

    def _get_world_resolver(self):
        resolver = self.session_context.get("world") or self.session_context.get("world_model")
        if resolver and hasattr(resolver, "resolve_location"):
            return resolver
        return None

    def _world_knows_location(self, location_name: str) -> bool:
        resolver = self._get_world_resolver()
        if not resolver:
            return False
        name = str(location_name or "").strip()
        if not name:
            return False

        current_map = self.session_context.get("current_map") or {}
        current_map_id = current_map.get("id") if isinstance(current_map, dict) else None
        current_map_name = current_map.get("name") if isinstance(current_map, dict) else None
        try:
            return bool(
                resolver.resolve_location(
                    name,
                    current_map_id=current_map_id,
                    current_map_name=current_map_name,
                )
            )
        except Exception:
            return False

    def _extract_delivery_entities(self, user_input: str) -> Dict[str, Any]:
        text = str(user_input or "").strip()
        normalized = re.sub(r"\s+", "", text)
        if not normalized:
            return {}

        has_delivery = any(k in normalized for k in ["送", "拿", "取", "带", "买", "领"])
        if not has_delivery:
            return {}

        item = None
        item_match = re.search(r"(送|拿|取|带|买|领)([^到去回给从在，。,.!?？！]{1,12})", normalized)
        if item_match:
            item = item_match.group(2)

        source = None
        source_match = re.search(r"(?:去|到|从|在)([^，。,.!?？！]{1,14})(?:拿|取|带|买|领)", normalized)
        if source_match:
            source = source_match.group(1)

        target = None
        target_match = re.search(r"(?:送到|送去|送往|交给|给|到|去)([^，。,.!?？！再然后并且]{1,14})", normalized)
        if target_match:
            target = target_match.group(1)

        return_charge = any(k in normalized for k in ["回充", "充电", "回桩", "回去充电", "回来充电"])
        return {
            "item": item,
            "source": source,
            "target": target,
            "return_charge": return_charge,
            "normalized": normalized,
        }

    def _refine_clarification_question(self, user_input: str, llm_question: str) -> str:
        """Use world knowledge to avoid over-asking known locations."""
        entities = self._extract_delivery_entities(user_input)
        if not entities:
            return llm_question

        item = str(entities.get("item") or "物品")
        source = str(entities.get("source") or "").strip()
        target = str(entities.get("target") or "").strip()
        return_charge = bool(entities.get("return_charge"))

        target_known = self._world_knows_location(target) if target else False
        dock_known = self._world_knows_location("回充点") or self._world_knows_location("充电点")

        # 典型场景：目标地点和回充都已知，只缺取货地点时，不要问“厕所/充电站在哪”。
        if not source and target and target_known and (not return_charge or dock_known or return_charge):
            return f"{item}要先去哪里取？"

        if source and not target:
            return "取到后要送到哪里？"

        if not source and not target:
            return f"{item}要先去哪里取？取到后送到哪里？"

        return llm_question

    def _looks_like_new_command_input(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        normalized = re.sub(r"\s+", "", text.lower())

        strong_markers = [
            "然后", "再", "并", "并且", "顺便", "最后",
            "回来", "回去", "回充", "充电", "开灯", "关灯", "亮灯",
            "播报", "播放", "说", "停止", "取消", "导航",
        ]
        if any(marker in normalized for marker in strong_markers):
            return True

        return bool(
            re.search(
                r"(拿|取|买|带|领)[^，。,.!?？！]{0,12}(咖啡|奶茶|饮料|水|纸|纸巾|文件|包裹|快递|外卖|钥匙|充电器|药|物品)",
                normalized,
            )
        )

    def _looks_like_location_answer(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        normalized = re.sub(r"\s+", "", text)

        # 问句/寒暄/身份类输入，不应被当作地点补充。
        reject_markers = [
            "？", "?", "什么", "怎么", "为何", "为啥", "吗", "呢",
            "你叫", "你是", "名字", "介绍", "你好", "谢谢",
        ]
        if any(marker in normalized for marker in reject_markers):
            return False

        # 动作类词汇，通常意味着新命令而非地点补充。
        action_markers = [
            "拿", "取", "送", "买", "带", "领", "交给",
            "回充", "充电", "返回", "回来", "回去",
            "开灯", "关灯", "亮灯", "播报", "播放", "说", "导航",
        ]
        if any(marker in normalized for marker in action_markers):
            return False

        object_keywords = [
            "咖啡", "奶茶", "饮料", "水",
            "纸", "纸巾", "文件", "包", "包裹", "快递", "外卖",
            "钥匙", "充电器", "药", "物品", "餐",
        ]
        location_hints = [
            "大厅", "前台", "公司", "办公室", "会议室", "卫生间", "厕所", "回充点",
            "楼", "层", "室", "区", "点", "台", "站", "门口", "工位",
        ]
        has_object_token = any(token in normalized for token in object_keywords)
        has_location_hint = any(token in normalized for token in location_hints)
        if has_object_token and not has_location_hint:
            return False

        return bool(re.match(r"^(去|到|从|在)?[A-Za-z0-9_\-\u4e00-\u9fff]{1,16}$", normalized))

    def _looks_like_object_answer(self, user_input: str) -> bool:
        text = str(user_input or "").strip()
        if not text:
            return False
        normalized = re.sub(r"\s+", "", text)
        object_keywords = [
            "咖啡", "奶茶", "饮料", "水",
            "纸", "纸巾", "文件", "包", "包裹", "快递", "外卖",
            "钥匙", "充电器", "药", "物品", "餐",
        ]
        if not any(token in normalized for token in object_keywords):
            return False

        reject_markers = ["去", "到", "从", "在", "送", "给", "大厅", "前台", "公司", "办公室", "会议室", "楼", "层"]
        if any(marker in normalized for marker in reject_markers):
            return False
        return True

    def _replace_delivery_object(self, base_input: str, new_object: str) -> str:
        base = str(base_input or "").strip()
        obj = str(new_object or "").strip()
        if not obj:
            return base
        parts = re.split(r"[，,]", base, maxsplit=1)
        head = parts[0] if parts else base
        tail = parts[1] if len(parts) > 1 else ""

        updated_head, changed = re.subn(
            r"(拿|取|买|带|领)([^，。,.!?？！\s]{1,16})",
            lambda m: f"{m.group(1)}{obj}",
            head,
            count=1,
        )
        if changed:
            return f"{updated_head}，{tail}".strip("，") if tail else updated_head
        return f"拿{obj}"

    def _needs_delivery_clarification(self, user_input: str) -> Optional[Dict[str, Any]]:
        slots = self._extract_delivery_slots(user_input)
        if not slots.get("is_delivery_intent"):
            return None
        if slots.get("has_source") and slots.get("has_target"):
            return None

        missing = []
        if not slots.get("has_source"):
            missing.append("source")
        if not slots.get("has_target"):
            missing.append("target")

        if missing == ["source", "target"]:
            question = "要去哪拿？送到哪里？"
        elif missing == ["source"]:
            question = "要去哪拿这个物品？"
        else:
            question = "拿到后要送到哪里？"

        return {"missing": missing, "question": question}

    def _merge_pending_delivery_input(self, user_input: str) -> str:
        pending = self.session_context.get("pending_delivery_clarification")
        if not isinstance(pending, dict):
            return user_input

        base_input = str(pending.get("base_input", "")).strip()
        missing = pending.get("missing", [])
        if not base_input:
            self.session_context.pop("pending_delivery_clarification", None)
            return user_input

        supplement = str(user_input or "").strip()
        if not supplement:
            return base_input

        # 用户给了一个全新的动作指令时，放弃旧的澄清上下文。
        if self._looks_like_new_command_input(supplement):
            self.session_context.pop("pending_delivery_clarification", None)
            return supplement

        def _clean_location(text: str) -> str:
            text = str(text or "").strip()
            text = re.sub(r"^(去|到|从|在|拿|取|送到|送去|交给|给)", "", text)
            text = re.sub(r"(拿|取|买|带|领)$", "", text)
            return text.strip(" ，,。.;；")

        merged = ""
        if missing == ["source", "target"]:
            parts = re.split(r"[，,;；]\s*", supplement, maxsplit=1)
            if len(parts) == 2:
                source = _clean_location(parts[0])
                target = _clean_location(parts[1])
                if source and target and self._looks_like_location_answer(source) and self._looks_like_location_answer(target):
                    merged = f"{base_input}，去{source}拿，送到{target}"
            elif len(parts) == 1:
                source = _clean_location(parts[0])
                if source and self._looks_like_location_answer(source):
                    merged = f"{base_input}，去{source}拿"
                elif source and self._looks_like_object_answer(source):
                    updated_base = self._replace_delivery_object(base_input, source)
                    pending["base_input"] = updated_base
                    self.session_context["pending_delivery_clarification"] = pending
                    return updated_base
        elif missing == ["source"]:
            source = _clean_location(supplement)
            if source and self._looks_like_location_answer(source):
                merged = f"{base_input}，去{source}拿"
            elif source and self._looks_like_object_answer(source):
                updated_base = self._replace_delivery_object(base_input, source)
                pending["base_input"] = updated_base
                self.session_context["pending_delivery_clarification"] = pending
                return updated_base
        elif missing == ["target"]:
            target = _clean_location(supplement)
            if target and self._looks_like_location_answer(target):
                merged = f"{base_input}，送到{target}"
            elif target and self._looks_like_object_answer(target):
                updated_base = self._replace_delivery_object(base_input, target)
                pending["base_input"] = updated_base
                self.session_context["pending_delivery_clarification"] = pending
                return updated_base

        if not merged:
            # 不是有效补充，退出澄清态，按新输入处理。
            self.session_context.pop("pending_delivery_clarification", None)
            return supplement

        self.session_context.pop("pending_delivery_clarification", None)
        print("[DEBUG] 使用补充信息合并任务指令")
        return merged

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        raw = str(text or "").strip()
        if not raw:
            return None

        fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        candidates = [fenced, raw]

        for candidate in candidates:
            try:
                obj = json.loads(candidate)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

            match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
            if match:
                try:
                    obj = json.loads(match.group(0))
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass
        return None

    def _call_llm_json_once(self, messages: List[LLMMessage]) -> Optional[Dict[str, Any]]:
        if not self.llm:
            return None
        try:
            resp = self.llm.chat(messages=messages, tools=None, temperature=0.0)
        except Exception as e:
            print(f"[WARN] 澄清仲裁调用失败: {e}")
            return None
        data = self._extract_json_object(getattr(resp, "content", ""))
        if not isinstance(data, dict):
            return None
        return data

    def _resolve_input_with_llm_clarification(self, user_input: str) -> Dict[str, Any]:
        """
        Let LLM decide whether clarification is needed and how to merge follow-up.
        Returns:
            {"status": "ask", "question": "..."} or
            {"status": "proceed", "effective_input": "..."}
        """
        text = str(user_input or "").strip()
        if not text:
            return {"status": "proceed", "effective_input": user_input}

        # 兼容旧字段，避免历史残留干扰。
        pending = self.session_context.get("pending_clarification")
        if not pending:
            legacy = self.session_context.pop("pending_delivery_clarification", None)
            if isinstance(legacy, dict):
                pending = {
                    "base_input": str(legacy.get("base_input", "")).strip(),
                    "question": str(legacy.get("question", "")).strip(),
                }
                self.session_context["pending_clarification"] = pending

        if isinstance(pending, dict) and pending.get("base_input"):
            # 若明显不是任务补充（既不是动作，也不像地点/物品补充），直接退出澄清态。
            if (
                not self._is_action_request(text)
                and not self._looks_like_location_answer(text)
                and not self._looks_like_object_answer(text)
            ):
                self.session_context.pop("pending_clarification", None)
                return {"status": "proceed", "effective_input": text}

            base_input = str(pending.get("base_input", "")).strip()
            prev_question = str(pending.get("question", "")).strip()
            world_info = self._get_world_prompt_info()
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "你是任务澄清合并器。请判断用户这句话是：\n"
                        "1) 对上轮澄清问题的补充；\n"
                        "2) 全新指令/闲聊。\n"
                        "只返回 JSON，不要输出其他文本。\n"
                        "输出格式：\n"
                        "{\n"
                        "  \"decision\": \"merged\" | \"ask_more\" | \"new_command\",\n"
                        "  \"merged_input\": \"...\",           # decision=merged 时必填\n"
                        "  \"updated_base_input\": \"...\",     # decision=ask_more 时可填\n"
                        "  \"question\": \"...\"                # decision=ask_more 时必填\n"
                        "}\n"
                        "要求：\n"
                        "- 若用户在问身份/状态/闲聊（例如“你叫什么”），必须给 new_command。\n"
                        "- 若信息仍不足以执行任务，给 ask_more 并提出一个最短追问。\n"
                        "- 能从 world 已知地点推断的信息不要重复追问。\n"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"原始任务: {base_input}\n"
                        f"上轮追问: {prev_question}\n"
                        f"用户最新输入: {text}\n"
                        f"world信息: {world_info or '无'}"
                    ),
                ),
            ]
            decision_data = self._call_llm_json_once(messages) or {}
            decision = str(decision_data.get("decision", "")).strip().lower()

            if decision in {"new_command", "new", "ignore_pending"}:
                self.session_context.pop("pending_clarification", None)
                return {"status": "proceed", "effective_input": text}

            if decision in {"ask_more", "ask", "need_more"}:
                question = str(decision_data.get("question", "")).strip() or "请补充任务关键信息。"
                updated_base = str(decision_data.get("updated_base_input", "")).strip() or base_input
                question = self._refine_clarification_question(updated_base, question)
                self.session_context["pending_clarification"] = {
                    "base_input": updated_base,
                    "question": question,
                }
                return {"status": "ask", "question": question}

            merged_input = str(decision_data.get("merged_input", "")).strip()
            if merged_input:
                self.session_context.pop("pending_clarification", None)
                return {"status": "proceed", "effective_input": merged_input}

            # 仲裁失败时，优先按新命令处理，避免劫持输入。
            self.session_context.pop("pending_clarification", None)
            return {"status": "proceed", "effective_input": text}

        # 无 pending 时：仅对动作请求做澄清仲裁，其他输入直接交给主流程。
        if not self._is_action_request(text):
            return {"status": "proceed", "effective_input": text}

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是任务澄清仲裁器。判断当前指令是否缺少关键执行信息。\n"
                    "只返回 JSON，不要输出其他文本。\n"
                    "输出格式：\n"
                    "{\n"
                    "  \"need_clarification\": true | false,\n"
                    "  \"question\": \"...\",        # need_clarification=true 时必填\n"
                    "  \"normalized_input\": \"...\" # need_clarification=false 时可填\n"
                    "}\n"
                    "规则：\n"
                    "- 不要机械追问；有合理默认值时可直接执行。\n"
                    "- 对“你叫什么/你是谁/现在状态”等非任务命令，不要追问地点。\n"
                    "- 只在缺失会导致任务无法可靠执行的关键信息时才追问。"
                    "- 能从 world 已知地点推断的信息不要重复追问。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"用户指令: {text}\n"
                    f"world信息: {self._get_world_prompt_info() or '无'}"
                ),
            ),
        ]

        judge_data = self._call_llm_json_once(messages) or {}
        need_raw = judge_data.get("need_clarification", False)
        if isinstance(need_raw, str):
            need_clarification = need_raw.strip().lower() in {"1", "true", "yes", "y"}
        else:
            need_clarification = bool(need_raw)

        if need_clarification:
            question = str(judge_data.get("question", "")).strip() or "请补充任务关键信息。"
            question = self._refine_clarification_question(text, question)
            self.session_context["pending_clarification"] = {
                "base_input": text,
                "question": question,
            }
            return {"status": "ask", "question": question}

        normalized = str(judge_data.get("normalized_input", "")).strip() or text
        return {"status": "proceed", "effective_input": normalized}
    
    def think(self, user_input: str) -> Generator[BrainResponse, None, None]:
        """Use the main LLM loop directly and keep the generator response contract intact."""
        self._cancel_event.clear()

        if self.llm is None:
            yield from self._rule_based_think(user_input)
            return

        try:
            self.session_context["last_input"] = user_input
            self._set_current_intent_type(None)

            messages = [
                LLMMessage(role="system", content=self._get_system_prompt()),
            ]

            context_info = self._get_context_info()
            if context_info:
                messages.append(LLMMessage(role="system", content=f"[当前状态]\n{context_info}"))

            compound_hint = self._detect_compound_instruction(user_input)
            if compound_hint:
                messages.append(LLMMessage(role="system", content=compound_hint))

            planning_hint = self._get_planning_mode_hint(user_input)
            if planning_hint:
                messages.append(LLMMessage(role="system", content=planning_hint))

            messages.append(LLMMessage(role="user", content=user_input))

            if context_info:
                print("[DEBUG] 使用状态上下文")
            if compound_hint:
                print("[DEBUG] 检测到复合指令，已添加提示")
            if planning_hint:
                print("[DEBUG] 使用规划优先模式")

            available_tools = self._get_available_tools(user_input)
            allowed_tool_names = {
                tool.get("function", {}).get("name")
                for tool in available_tools
                if tool.get("function", {}).get("name")
            }
            tools = self.llm.get_tool_definitions(available_tools)
            tool_choice = None

            max_iterations = max(1, int(getattr(get_config().llm, "max_iterations", 4) or 4))
            iteration = 0
            final_text = ""

            all_steps = []
            executed_steps = []
            plan_shown = False
            shown_plan_length = 0
            consecutive_failures = 0
            executed_any_step = False
            had_failures = False
            no_step_rounds = 0
            terminal_error_emitted = False
            submit_mission_pending = False
            status_query_completed = False
            direct_text_emitted = False

            while iteration < max_iterations:
                iteration += 1

                llm_response = self.llm.chat(
                    messages=messages,
                    tools=tools,
                    temperature=0.1,
                    tool_choice=tool_choice,
                )

                if llm_response.tool_calls:
                    round_steps = []
                    for tool_call in llm_response.tool_calls:
                        try:
                            extracted_calls = self._extract_steps_from_tool_call(tool_call)
                            for fixed_call in extracted_calls:
                                if fixed_call["name"] not in allowed_tool_names:
                                    print(f"[WARN] 规划模式下忽略工具: {fixed_call['name']}")
                                    continue
                                round_steps.append({
                                    "skill": fixed_call["name"],
                                    "params": fixed_call["arguments"],
                                    "tool_call": tool_call,
                                })
                        except Exception as e:
                            print(f"[WARN] 解析工具调用失败: {e}")
                            continue

                    round_tool_names = {step.get("skill") for step in round_steps if step.get("skill")}
                    if "submit_mission" in round_tool_names:
                        self._set_current_intent_type("mission")
                    elif "system_status" in round_tool_names:
                        self._set_current_intent_type("status")

                    if self._is_simple_status_query(user_input):
                        status_steps = [step for step in round_steps if step.get("skill") == "system_status"]
                        if round_steps and not status_steps:
                            print(f"[WARN] 状态查询意图下收到非状态工具: {[s.get('skill') for s in round_steps]}")
                        round_steps = status_steps[:1]
                        print(f"[DEBUG] 状态查询意图: '{user_input}' - 保留步骤: {[s['skill'] for s in round_steps]}")

                    round_steps = self._sort_steps(round_steps)
                    round_steps = self._augment_steps_from_intent(user_input, all_steps, round_steps)
                    all_steps.extend(round_steps)

                    if not round_steps:
                        no_step_rounds += 1
                        if no_step_rounds >= 2:
                            terminal_error_emitted = True
                            yield BrainResponse(
                                type="error",
                                content="LLM未生成可执行计划。请重试，或简化指令后再试。",
                            )
                            break
                        if self.session_context.get("planning_only"):
                            messages.append(LLMMessage(
                                role="system",
                                content="规划模式下禁止调用 nav_list_maps/nav_list_waypoints，请直接返回动作步骤。",
                            ))
                        continue
                    no_step_rounds = 0

                    if iteration == 1 and round_steps and not plan_shown:
                        has_submit_mission = any(step.get("skill") == "submit_mission" for step in all_steps)
                        if has_submit_mission:
                            is_valid, issues = True, []
                        else:
                            is_valid, issues = self.plan_validator.validate_plan(user_input, all_steps)

                        yield BrainResponse(type="plan", content="", metadata={"steps": all_steps.copy()})

                        if not is_valid:
                            print(f"[PLAN VALIDATOR] 检测到规划问题: {issues}")
                            improvement_hint = self.plan_validator.get_improvement_hint(issues)
                            yield BrainResponse(type="debug", content=improvement_hint)
                            messages.append(LLMMessage(role="user", content=improvement_hint))
                            continue

                        plan_shown = True
                        shown_plan_length = len(all_steps)
                        self.session_context["last_plan"] = all_steps.copy()
                    elif self.session_context.get("planning_only") and round_steps and len(all_steps) > shown_plan_length:
                        is_valid, issues = self.plan_validator.validate_plan(user_input, all_steps)
                        yield BrainResponse(type="plan", content="", metadata={"steps": all_steps.copy()})
                        if not is_valid:
                            print(f"[PLAN VALIDATOR] 检测到规划问题: {issues}")
                            improvement_hint = self.plan_validator.get_improvement_hint(issues)
                            yield BrainResponse(type="debug", content=improvement_hint)
                            messages.append(LLMMessage(role="user", content=improvement_hint))
                            continue
                        shown_plan_length = len(all_steps)
                        self.session_context["last_plan"] = all_steps.copy()

                    for step in round_steps:
                        if self._cancel_event.is_set():
                            yield BrainResponse(type="error", content="任务已取消")
                            return

                        function_name = step["skill"]
                        arguments = self._normalize_step_arguments(function_name, step["params"])
                        step_key = f"{function_name}:{json.dumps(arguments, sort_keys=True)}"
                        if step_key in executed_steps:
                            continue

                        yield BrainResponse(
                            type="action",
                            content=f"执行技能: {function_name}",
                            metadata={
                                "skill": function_name,
                                "params": arguments,
                                "step_num": len(executed_steps) + 1,
                            },
                        )

                        skill = self.registry.get(function_name)
                        if not skill:
                            yield BrainResponse(type="error", content=f"技能 {function_name} 不存在")
                            continue

                        try:
                            result = skill.run(arguments, self.session_context)
                            if result is None:
                                error_msg = f"技能 {function_name} 返回 None"
                                yield BrainResponse(type="error", content=error_msg)
                                consecutive_failures += 1
                                continue

                            result_content = result.get("detail", "")
                            success = result.get("ok", False)
                            result_data = result.get("data")

                            if function_name == "submit_mission" and success:
                                if isinstance(result_data, dict):
                                    submit_mission_pending = bool(result_data.get("pending", True))
                                else:
                                    submit_mission_pending = True

                            yield BrainResponse(
                                type="result",
                                content=result_content,
                                metadata={
                                    "success": success,
                                    "skill": function_name,
                                    "data": result_data,
                                },
                            )

                            executed_steps.append(step_key)
                            executed_any_step = True

                            if function_name == "system_status" and self._is_simple_status_query(user_input):
                                status_query_completed = True
                                if success and result_content:
                                    final_text = result_content

                            if success:
                                consecutive_failures = 0
                            else:
                                had_failures = True
                                consecutive_failures += 1
                                if consecutive_failures >= 2:
                                    yield BrainResponse(
                                        type="error",
                                        content="连续执行失败，任务中止。请检查参数或手动处理。",
                                    )
                                    break

                            self._update_context(function_name, result)
                            messages.append(LLMMessage(
                                role="assistant",
                                content=f"调用了 {function_name}",
                                tool_calls=[step["tool_call"]],
                            ))
                            messages.append(LLMMessage(
                                role="tool",
                                content=json.dumps({"result": result_content, "success": success}),
                                tool_call_id=step["tool_call"].get("id", ""),
                            ))
                        except Exception as e:
                            error_msg = f"执行异常: {str(e)}"
                            yield BrainResponse(type="error", content=error_msg)
                            messages.append(LLMMessage(
                                role="tool",
                                content=json.dumps({"error": error_msg}),
                                tool_call_id=step["tool_call"].get("id", ""),
                            ))
                            had_failures = True
                            consecutive_failures += 1

                    if consecutive_failures >= 2:
                        break
                    if status_query_completed:
                        break
                    if self.session_context.get("planning_only") and round_steps:
                        if self._planning_requirements_met(user_input, all_steps):
                            break
                        messages.append(LLMMessage(
                            role="system",
                            content=self._get_planning_followup_hint(user_input, all_steps),
                        ))
                        continue
                    if round_steps and self._is_action_request(user_input):
                        if self._planning_requirements_met(user_input, all_steps):
                            break
                        messages.append(LLMMessage(
                            role="system",
                            content=self._get_planning_followup_hint(user_input, all_steps),
                        ))
                        continue
                else:
                    content = str(llm_response.content or "").strip()
                    if content:
                        self._set_current_intent_type("chat")
                        final_text = content
                        direct_text_emitted = True
                        yield BrainResponse(type="text", content=content)
                    break

            planning_complete = True
            if (self.session_context.get("planning_only") or self._is_action_request(user_input)) and executed_any_step:
                planning_complete = self._planning_requirements_met(user_input, all_steps)
            has_submit_mission = any(step.get("skill") == "submit_mission" for step in all_steps)

            if direct_text_emitted:
                pass
            elif self.session_context.get("planning_only") and executed_any_step and planning_complete:
                yield BrainResponse(type="text", content="本轮操作已执行完成。")
            elif self.session_context.get("planning_only") and not planning_complete:
                yield BrainResponse(
                    type="error",
                    content="规划未完整覆盖用户需求，请继续优化提示词或仿真场景。",
                )
            elif executed_any_step and not planning_complete:
                yield BrainResponse(
                    type="error",
                    content="本轮计划未完整覆盖用户需求，请补充 world 描述或重试更明确的指令。",
                )
            elif has_submit_mission and executed_any_step and not had_failures:
                if submit_mission_pending:
                    yield BrainResponse(type="text", content="任务已提交，正在执行中，请等待导航/回调事件。")
                else:
                    yield BrainResponse(type="text", content="本轮操作已执行完成。")
            elif final_text and not self._is_polluted_text(final_text):
                yield BrainResponse(type="text", content=final_text)
            elif executed_any_step and not had_failures:
                yield BrainResponse(type="text", content="本轮操作已执行完成。")
            elif executed_any_step and had_failures and not terminal_error_emitted:
                yield BrainResponse(
                    type="error",
                    content="本轮任务执行未成功，请查看上面的错误信息。",
                )
            elif not terminal_error_emitted:
                yield BrainResponse(
                    type="error",
                    content="未生成任何可执行结果。请重试，或把指令改成更短的动作序列。",
                )

            executed_skills = [s["skill"] for s in all_steps]
            history_summary = f"执行了 {', '.join(executed_skills)}" if executed_skills else "无操作"

            self.session_context["conversation_history"].append({
                "input": user_input,
                "summary": history_summary,
            })
            if len(self.session_context["conversation_history"]) > 3:
                self.session_context["conversation_history"] = self.session_context["conversation_history"][-3:]

            self._learn_from_interaction(user_input, all_steps)

        except Exception as e:
            yield BrainResponse(type="error", content=f"LLM处理失败: {str(e)}")
            import traceback
            traceback.print_exc()

    def _sort_steps(self, steps: List[Dict]) -> List[Dict]:
        """
        排序步骤，保证正确的执行顺序：
        1. 前置步骤（system_status, motion_stand, nav_start）
        2. 导航序列（nav_goto_location + system_wait 配对）
        3. 灯光/播报等中间步骤
        4. 最终导航序列（返回充电等）
        """
        if not steps:
            return steps

        # 第1步：提取前置步骤
        prefix_order = ["system_status", "motion_stand", "nav_start"]
        prefix_steps: List[Dict] = []
        used_indexes = set()

        for skill_name in prefix_order:
            for idx, step in enumerate(steps):
                if idx in used_indexes:
                    continue
                if step.get("skill") == skill_name:
                    prefix_steps.append(step)
                    used_indexes.add(idx)
                    break

        # 第2步：处理剩余步骤，将 nav_goto_location 和其对应的 system_wait 配对
        remaining = [
            (idx, step) for idx, step in enumerate(steps)
            if idx not in used_indexes
        ]

        sorted_remaining: List[Dict] = []
        processed_indexes = set()

        for idx, step in remaining:
            if idx in processed_indexes:
                continue

            skill = step.get("skill")

            # 如果是导航步骤，找到它对应的 wait 步骤
            if skill == "nav_goto_location":
                sorted_remaining.append(step)
                processed_indexes.add(idx)

                # 查找对应的 system_wait（应该紧跟在这个导航后）
                for wait_idx, wait_step in remaining:
                    if wait_idx not in processed_indexes and wait_step.get("skill") == "system_wait":
                        # 检查这个 wait 的目标是否与导航相符
                        wait_event = wait_step.get("params", {}).get("event_type")
                        nav_location_type = step.get("params", {}).get("location_type", "waypoint")
                        
                        # 如果 location_type 是 dock，应该配 dock_complete；否则配 arrival
                        expected_event = "dock_complete" if nav_location_type == "dock" else "arrival"
                        
                        if wait_event == expected_event:
                            sorted_remaining.append(wait_step)
                            processed_indexes.add(wait_idx)
                            break

            # 灯光/播报等步骤，按原始顺序添加
            elif skill in ["light_set", "light_on", "light_off", "audio_say", "audio_play"]:
                sorted_remaining.append(step)
                processed_indexes.add(idx)

            # 其他步骤（包括未配对的 system_wait）
            elif idx not in processed_indexes:
                sorted_remaining.append(step)
                processed_indexes.add(idx)

        return prefix_steps + sorted_remaining

    def _is_action_request(self, user_input: str) -> bool:
        """识别更像动作而不是查询的输入。"""
        action_keywords = [
            "去", "返回", "回来", "回充", "前往", "到达", "亮", "关灯", "开灯",
            "播报", "播放", "站立", "趴下", "启动导航", "停止",
            "拿", "取", "送", "带", "买", "领", "交给",
        ]
        return any(keyword in user_input for keyword in action_keywords)

    def _is_polluted_text(self, text: str) -> bool:
        """过滤模型把思维链或工具片段直接吐给用户的情况。"""
        polluted_markers = [
            "<think", "</think>", "<tool_call", "</tool_call>",
            "<arg_key>", "<arg_value>", "调用了", "调调用了",
        ]
        return any(marker in text for marker in polluted_markers)

    def _normalize_step_arguments(self, function_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """在执行前补齐少量可从上下文安全推导的参数。"""
        normalized = dict(arguments or {})

        if function_name == "system_wait" and normalized.get("event_type") == "arrival":
            if not normalized.get("waypoint_id"):
                pending = self.session_context.get("pending_arrival") or self.session_context.get("last_waypoint")
                if isinstance(pending, dict):
                    waypoint_id = pending.get("waypoint_id") or pending.get("id")
                    if waypoint_id:
                        normalized["waypoint_id"] = waypoint_id

        if function_name == "nav_start":
            has_map_name = bool(normalized.get("map_name"))
            has_map_id = normalized.get("map_id") is not None
            if not has_map_name and not has_map_id:
                resolver = self.session_context.get("world") or self.session_context.get("world_model")
                if resolver and hasattr(resolver, "get_default_map"):
                    try:
                        default_map = resolver.get_default_map()
                    except Exception:
                        default_map = None
                    if default_map:
                        if default_map.map_id is not None:
                            normalized["map_id"] = default_map.map_id
                        if getattr(default_map, "name", None):
                            normalized["map_name"] = default_map.name

            has_map_name = bool(normalized.get("map_name"))
            has_map_id = normalized.get("map_id") is not None
            if not has_map_name and not has_map_id:
                world_default_map = self.session_context.get("world_default_map")
                if isinstance(world_default_map, dict):
                    if world_default_map.get("id") is not None:
                        normalized["map_id"] = world_default_map.get("id")
                    if world_default_map.get("name"):
                        normalized["map_name"] = world_default_map.get("name")
                elif isinstance(world_default_map, int):
                    normalized["map_id"] = world_default_map
                elif isinstance(world_default_map, str) and world_default_map.strip():
                    normalized["map_name"] = world_default_map.strip()

            has_map_name = bool(normalized.get("map_name"))
            has_map_id = normalized.get("map_id") is not None
            if not has_map_name and not has_map_id:
                current_map = self.session_context.get("current_map")
                if isinstance(current_map, dict):
                    if current_map.get("id") is not None:
                        normalized["map_id"] = current_map.get("id")
                    if current_map.get("name"):
                        normalized["map_name"] = current_map.get("name")

        return normalized
    
    def _detect_compound_instruction(self, user_input: str) -> str:
        """检测复合指令并返回提示"""
        user_lower = user_input.lower()
        
        # 检测连接词
        connectors = ['然后', '再', '接着', '之后', '随后', '完成后', '以后']
        action_keywords = ['去', '亮', '灯', '播报', '播放', '说', '返回', '到', '前往']
        
        connector_count = sum(1 for c in connectors if c in user_input)
        action_count = sum(1 for a in action_keywords if a in user_lower)
        
        # 如果有多于2个动作且至少1个连接词，视为复合指令
        if action_count >= 2 and connector_count >= 1:
            # 将提示词修改得极其严厉，强制映射所有动作
            return f"""[复合指令检测 - 最高优先级]
用户输入包含多个动作步骤，请你务必完整规划所有步骤：
输入: "{user_input}"

你必须包含以下映射：
1. 动作请求必须调用工具，禁止纯文本回复。
2. 【查询类指令铁律】：当用户只是询问状态（如："在充电吗"、"电量多少"、"你在哪"）时，你只允许调用查询工具（如 system_status），并直接回答用户，**绝对禁止自作主张执行导航或回充等动作！**
3. 【导航与移动铁律】：任何形式的移动（包括去某个地点、返回回充点），**第一步必须是 motion_stand（站立）！** 机器狗趴着是无法移动的。
4. 标准导航顺序: system_status → motion_stand → [必要时 nav_start] → nav_goto_location
5. 回充标准流程: motion_stand → nav_goto_location(location="回充点", location_type="dock") → system_wait(event_type="dock_complete")
6. 参数用JSON格式，不要XML。
7. 一次性返回所有工具调用。
8. 复合指令处理 - 必须完整规划所有步骤... （保留你原来的复合指令说明）

【系统警告】禁止遗漏用户指令中的任何一个小动作！请仔细检查你生成的计划，确保包含了上述所有被触发的动词对应的工具调用！"""
        
        return ""

    def _get_available_tools(self, user_input: str) -> List[Dict[str, Any]]:
        """仅向 LLM 暴露 submit_mission 和 system_status 两个工具。"""
        allowed_names = {"submit_mission", "system_status"}
        tools = [
            tool
            for tool in self.registry.get_tools()
            if tool.get("function", {}).get("name") in allowed_names
        ]

        mission_tool = next(
            (tool for tool in tools if tool.get("function", {}).get("name") == "submit_mission"),
            None,
        )
        status_tool = next(
            (tool for tool in tools if tool.get("function", {}).get("name") == "system_status"),
            None,
        )

        if self._is_simple_status_query(user_input):
            return [status_tool] if status_tool else ([] if mission_tool is None else [mission_tool])

        if mission_tool:
            return [mission_tool]
        if status_tool:
            return [status_tool]
        return tools

    def _is_simple_status_query(self, user_input: str) -> bool:
        """识别纯状态查询，避免误触发 mission。"""
        if not user_input:
            return False

        if self._is_action_request(user_input):
            return False

        status_keywords = [
            "状态", "电量", "电池", "充电", "在充电吗",
            "位置", "在哪", "在哪儿", "现在怎么样", "情况",
        ]
        return any(keyword in user_input for keyword in status_keywords)

    def _get_world_prompt_info(self) -> str:
        """Return current world information for LLM grounding."""
        resolver = self.session_context.get("world") or self.session_context.get("world_model")
        if resolver and hasattr(resolver, "describe_for_prompt"):
            return resolver.describe_for_prompt(limit=50)

        world_prompt = self.session_context.get("world_prompt")
        if world_prompt:
            return world_prompt

        world_summary = self.session_context.get("world_summary")
        if world_summary:
            return f"当前 world: {world_summary}"
        return ""

    def _get_soul_prompt_info(self) -> str:
        soul = self.session_context.get("soul")
        if soul and hasattr(soul, "describe_for_prompt"):
            return soul.describe_for_prompt()

        soul_prompt = self.session_context.get("soul_prompt")
        if soul_prompt:
            return soul_prompt

        soul_summary = self.session_context.get("soul_summary")
        if soul_summary:
            return f"当前 Soul: {soul_summary}"
        return ""

    def _learn_from_interaction(self, user_input: str, steps: List[Dict[str, Any]]) -> None:
        soul = self.session_context.get("soul")
        if not soul or not hasattr(soul, "learn_from_interaction"):
            return

        try:
            soul.learn_from_interaction(
                user_input=user_input,
                steps=steps,
                session_context=self.session_context,
            )
            self.session_context["soul_summary"] = soul.describe()
            self.session_context["soul_prompt"] = soul.describe_for_prompt()
            self.session_context["soul_preferences"] = {
                key: pref.value for key, pref in soul.state.preferences.items()
            }
        except Exception as e:
            print(f"[WARN] Soul 学习失败: {e}")

    def _get_planning_mode_hint(self, user_input: str) -> str:
        """在 mock 规划模式下，明确告诉模型直接做任务规划。"""
        if not self.session_context.get("planning_only"):
            return ""

        lines = [
            "[仿真规划模式]",
            "当前目标是测试任务规划与决策，不是测试地图查询。",
            "不要调用 nav_list_maps 或 nav_list_waypoints。",
            "请直接基于已知场景规划动作序列。",
            "如果用户提到楼层、楼上或楼下，这通常表示切换地图，应先使用 nav_start(map_name=...)，再执行 nav_goto_location。",
            "如果用户要求拿、送、给物品，优先考虑 item_pickup、item_dropoff 或 item_place。",
            "不要只返回 system_status / motion_stand / nav_start，必须把后续动作一起规划出来。",
        ]

        mock_world = self.session_context.get("mock_world")
        if isinstance(mock_world, dict):
            current_map = mock_world.get("current_map")
            if current_map:
                lines.append(f"当前默认地图: {current_map}")
            aliases = mock_world.get("map_aliases", {})
            if aliases:
                alias_text = ", ".join(f"{alias}={target}" for alias, target in aliases.items())
                lines.append(f"地图别名: {alias_text}")
            waypoints = mock_world.get("waypoints", {})
            for map_name, names in waypoints.items():
                if names:
                    lines.append(f"{map_name} 路点: {', '.join(names)}")

        return "\n".join(lines)

    def _is_lookup_query(self, user_input: str) -> bool:
        """识别用户是否真的在问地图/路点列表。"""
        direct_keywords = [
            "哪些地图", "有什么地图", "地图列表", "列出地图",
            "哪些路点", "有什么路点", "路点列表", "列出路点",
        ]
        if any(keyword in user_input for keyword in direct_keywords):
            return True

        asks_for_list = any(keyword in user_input for keyword in ["哪些", "有什么", "列出", "查看", "看看"])
        mentions_world = any(keyword in user_input for keyword in ["地图", "路点", "楼层", "楼下", "楼上"])
        return asks_for_list and mentions_world

    def _planning_requirements_met(self, user_input: str, steps: List[Dict[str, Any]]) -> bool:
        """判断规划优先模式下本轮计划是否已经覆盖用户需求。"""
        skill_names = [step.get("skill", "") for step in steps]
        if not skill_names:
            return False

        has_navigation = any(name in {"nav_goto_location", "nav_goto_waypoint"} for name in skill_names)
        if self._is_action_request(user_input) and not has_navigation and any(k in user_input for k in ["去", "到", "返回", "回"]):
            return False

        if any(k in user_input for k in ["亮", "灯", "关灯"]) and not any(name.startswith("light_") for name in skill_names):
            return False

        if any(k in user_input for k in ["播报", "播放", "说"]) and not any(name in {"audio_play", "tts_speak"} for name in skill_names):
            return False

        if any(k in user_input for k in ["回充", "充电", "回充点", "充电点", "回桩"]):
            has_dock_nav = any(
                step.get("skill") == "nav_goto_location" and step.get("params", {}).get("location_type") == "dock"
                for step in steps
            )
            has_dock_wait = any(
                step.get("skill") == "system_wait" and step.get("params", {}).get("event_type") == "dock_complete"
                for step in steps
            )
            if not (has_dock_nav and has_dock_wait):
                return False

        if self._has_implicit_return_to_charge_intent(user_input):
            has_dock_nav = any(
                step.get("skill") == "nav_goto_location" and step.get("params", {}).get("location_type") == "dock"
                for step in steps
            )
            if not has_dock_nav:
                return False

        if any(k in user_input for k in ["拿", "取", "给我", "送到", "放到", "交给"]):
            if not any(name in {"item_pickup", "item_dropoff", "item_place"} for name in skill_names):
                return False

        if self._detect_compound_instruction(user_input) and len(steps) < 4:
            return False

        return True

    def _get_planning_followup_hint(self, user_input: str, steps: List[Dict[str, Any]]) -> str:
        """当首轮只规划了前置步骤时，提醒模型补全剩余动作。"""
        planned = ", ".join(step.get("skill", "") for step in steps if step.get("skill"))
        return (
            "[规划未完成]\n"
            f"用户原始指令: {user_input}\n"
            f"你目前只规划了这些步骤: {planned}\n"
            "请继续补全剩余动作，不要重复已经执行的步骤。"
        )

    def _make_synthetic_step(self, skill: str, params: Dict[str, Any]) -> Dict[str, Any]:
        arguments = dict(params or {})
        return {
            "skill": skill,
            "params": arguments,
            "tool_call": {
                "id": f"synthetic_{skill}_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": skill,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            },
        }

    def _augment_steps_from_intent(self, user_input: str, existing_steps: List[Dict[str, Any]], round_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """为明显遗漏的后置动作补一层低风险兜底。"""
        if not round_steps:
            return round_steps

        # 如果是查询问题，不做增强（直接返回LLM规划的步骤）
        query_keywords = ['?', '？', '多少', '什么', '哪些', '吗', '呢', '哪里', '怎样', '如何']
        is_query = any(kw in user_input for kw in query_keywords)
        if is_query:
            return round_steps

        combined_steps = list(existing_steps) + list(round_steps)
        augmented_steps = list(round_steps)

        if self._has_charge_tail_intent(user_input) or self._has_implicit_return_to_charge_intent(user_input):
            has_dock_nav = any(
                step.get("skill") == "nav_goto_location" and step.get("params", {}).get("location_type") == "dock"
                for step in combined_steps
            )
            has_dock_wait = any(
                step.get("skill") == "system_wait" and step.get("params", {}).get("event_type") == "dock_complete"
                for step in combined_steps
            )
            has_arrival_wait = any(
                step.get("skill") == "system_wait" and step.get("params", {}).get("event_type") == "arrival"
                for step in combined_steps
            )
            has_regular_nav = any(
                step.get("skill") in {"nav_goto_location", "nav_goto_waypoint"}
                and step.get("params", {}).get("location_type") != "dock"
                for step in combined_steps
            )

            if has_regular_nav and not has_arrival_wait:
                synthetic_wait = self._make_synthetic_step("system_wait", {"event_type": "arrival"})
                augmented_steps.append(synthetic_wait)
                combined_steps.append(synthetic_wait)

            if not has_dock_nav:
                return_target = self._infer_return_target(combined_steps)
                dock_params = {
                    "location": return_target.get("location", "回充点"),
                    "location_type": return_target.get("location_type", "dock"),
                }
                synthetic_dock = self._make_synthetic_step("nav_goto_location", dock_params)
                augmented_steps.append(synthetic_dock)
                combined_steps.append(synthetic_dock)
                has_dock_nav = dock_params.get("location_type") == "dock"

            if not has_dock_wait:
                event_type = "dock_complete" if has_dock_nav else "arrival"
                synthetic_dock_wait = self._make_synthetic_step("system_wait", {"event_type": event_type})
                augmented_steps.append(synthetic_dock_wait)

            post_return_intent = self._get_post_return_action_intent(user_input)
            if post_return_intent:
                augmented_steps = self._reorder_post_return_actions(augmented_steps, post_return_intent)

        return augmented_steps

    def _has_charge_tail_intent(self, user_input: str) -> bool:
        return any(keyword in user_input for keyword in ["回充", "充电", "回充点", "充电点", "回桩"])

    def _has_implicit_return_to_charge_intent(self, user_input: str) -> bool:
        if self._has_charge_tail_intent(user_input):
            return False

        normalized = re.sub(r"\s+", "", user_input or "")
        if not normalized:
            return False

        soul_preferences = self.session_context.get("soul_preferences") or {}
        if soul_preferences.get("return_behavior") == "charge":
            if any(keyword in normalized for keyword in ("返回", "回来", "回去")):
                explicit_targets = ["地图", "大厅", "前台", "会议室", "厕所", "卫生间", "楼上", "楼下", "回充点", "充电点"]
                explicit_return = any(
                    f"返回{target}" in normalized or f"回到{target}" in normalized or f"回{target}" in normalized
                    for target in explicit_targets
                )
                if not explicit_return:
                    return True

        explicit_targets = ["地图", "大厅", "前台", "会议室", "厕所", "卫生间", "楼上", "楼下", "回充点", "充电点"]
        return_patterns = ["返回", "回来", "回去"]
        followers = ["并", "然后", "再", "之后", "随后", "同时", "播报", "说", "播放", "闪", "亮", "开灯", "关灯"]

        for keyword in return_patterns:
            start = normalized.find(keyword)
            while start != -1:
                tail = normalized[start + len(keyword):]
                if not tail:
                    return True
                if tail[0] in "，,。！？；":
                    return True
                if any(tail.startswith(prefix) for prefix in followers):
                    return True
                if not any(tail.startswith(target) for target in explicit_targets):
                    if len(tail) <= 2:
                        return True
                start = normalized.find(keyword, start + len(keyword))
        return False

    def _infer_return_target(self, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        resolver = self.session_context.get("world") or self.session_context.get("world_model")
        current_map = self.session_context.get("current_map") or {}
        current_map_id = current_map.get("id") if isinstance(current_map, dict) else None
        current_map_name = current_map.get("name") if isinstance(current_map, dict) else None

        reference_location = None
        for step in reversed(steps):
            if step.get("skill") != "nav_goto_location":
                continue
            params = step.get("params", {})
            if params.get("location_type") == "dock":
                continue
            location = params.get("location")
            if location:
                reference_location = str(location)
                break

        if resolver and hasattr(resolver, "resolve_return_target"):
            resolved = resolver.resolve_return_target(
                reference_location=reference_location,
                current_map_id=current_map_id,
                current_map_name=current_map_name,
            )
            if resolved:
                return {
                    "location": getattr(resolved, "name", None) or "回充点",
                    "location_type": getattr(resolved, "location_type", "dock") or "dock",
                }

        return {"location": "回充点", "location_type": "dock"}

    def _get_post_return_action_intent(self, user_input: str) -> Dict[str, bool]:
        normalized = re.sub(r"\s+", "", user_input or "")
        if not normalized:
            return {}

        indexes = [normalized.rfind(keyword) for keyword in ("返回", "回来", "回去")]
        last_index = max(indexes)
        if last_index < 0:
            return {}

        tail = normalized[last_index:]
        return {
            "audio": any(keyword in tail for keyword in ["播报", "说", "播放"]),
            "light": any(keyword in tail for keyword in ["灯", "亮", "闪"]),
        }

    def _reorder_post_return_actions(self, steps: List[Dict[str, Any]], post_return_intent: Dict[str, bool]) -> List[Dict[str, Any]]:
        if not steps:
            return steps

        dock_index = next(
            (
                idx for idx, step in enumerate(steps)
                if step.get("skill") == "nav_goto_location" and step.get("params", {}).get("location_type") == "dock"
            ),
            None,
        )
        if dock_index is None:
            return steps

        dock_wait_index = next(
            (
                idx for idx, step in enumerate(steps[dock_index + 1:], dock_index + 1)
                if step.get("skill") == "system_wait" and step.get("params", {}).get("event_type") == "dock_complete"
            ),
            dock_index,
        )

        moved_indexes = set()
        trailing_actions: List[Dict[str, Any]] = []
        for idx, step in enumerate(steps[:dock_index]):
            skill = step.get("skill")
            if post_return_intent.get("audio") and skill in {"audio_play", "tts_speak"}:
                moved_indexes.add(idx)
                trailing_actions.append(step)
                continue
            if post_return_intent.get("light") and skill in {"light_set", "light_on", "light_off"}:
                moved_indexes.add(idx)
                trailing_actions.append(step)

        if not trailing_actions:
            return steps

        reordered: List[Dict[str, Any]] = []
        for idx, step in enumerate(steps):
            if idx in moved_indexes:
                continue
            reordered.append(step)
            if idx == dock_wait_index:
                reordered.extend(trailing_actions)
        return reordered
    
    def _get_context_info(self) -> str:
        """获取结构化的上下文状态（不是对话历史）"""
        parts = []
        
        current_map = self.session_context.get("current_map")
        if current_map:
            parts.append(f"地图: {current_map.get('name', '未知')}")
        
        current_location = self.session_context.get("current_location")
        if current_location:
            parts.append(f"位置: {current_location}")
        
        if self.adapter and hasattr(self.adapter, 'get_status'):
            try:
                status = self.adapter.get_status()
                if status.nav_running:
                    parts.append("状态: 正在导航")
                else:
                    parts.append("状态: 待机")
            except Exception:
                pass
        
        carrying = self.session_context.get("carrying_item")
        if carrying:
            parts.append(f"携带: {carrying}")

        world_name = self.session_context.get("world_name")
        if world_name:
            parts.append(f"world: {world_name}")

        world_default_map = self.session_context.get("world_default_map")
        if world_default_map:
            parts.append(f"world默认地图: {world_default_map}")
        
        world_summary = self.session_context.get("world_summary")
        if world_summary:
            parts.append(f"world摘要: {world_summary}")

        soul_summary = self.session_context.get("soul_summary")
        if soul_summary:
            parts.append(f"Soul摘要: {soul_summary}")
        return "\n".join(parts) if parts else ""
        
        # 当前地图
        current_map = self.session_context.get("current_map")
        if current_map:
            parts.append(f"地图: {current_map.get('name', '未知')}")
        
        # 当前位置
        current_location = self.session_context.get("current_location")
        if current_location:
            parts.append(f"位置: {current_location}")
        
        # 导航状态
        if self.adapter and hasattr(self.adapter, 'get_status'):
            try:
                status = self.adapter.get_status()
                if status.nav_running:
                    parts.append("状态: 正在导航")
                else:
                    parts.append("状态: 待机")
            except:
                pass
        
        # 携带物品
        carrying = self.session_context.get("carrying_item")
        if carrying:
            parts.append(f"携带: {carrying}")
        
        world_summary = self.session_context.get("world_summary")
        if world_summary:
            parts.append(f"world: {world_summary}")
        return "\n".join(parts) if parts else ""
    
    def _summarize_responses(self, responses: List[Dict]) -> str:
        if not responses:
            return "任务完成"
        
        parts = []
        for r in responses:
            skill = r.get("skill", "")
            # 只保留关键信息
            if skill:
                parts.append(skill)
        
        return f"执行了: {', '.join(parts[:3])}" if parts else "已处理"

    def _extract_steps_from_tool_call(self, tool_call: Dict) -> List[Dict[str, Any]]:
        """从单个 tool_call 中提取一个或多个步骤。"""
        recovered_calls = self._recover_compound_tool_call(tool_call)
        if recovered_calls:
            return recovered_calls

        fixed_call = self._fix_tool_call(tool_call)
        return [fixed_call] if fixed_call else []

    def _recover_compound_tool_call(self, tool_call: Dict) -> List[Dict[str, Any]]:
        """恢复被模型错误压成一个 tool_call 的复合任务。"""
        function_data = tool_call.get("function", {})
        name_str = function_data.get("name", "") or ""
        args_raw = function_data.get("arguments", "") or ""
        if isinstance(args_raw, str):
            args_str = args_raw
        elif isinstance(args_raw, dict):
            args_str = json.dumps(args_raw, ensure_ascii=False)
        else:
            return []

        skill_names = sorted(self.registry.list_all(), key=len, reverse=True)
        if not args_str:
            return []

        hit_count = sum(args_str.count(skill) for skill in skill_names)
        if hit_count < 2:
            return []

        import re

        pair_pattern = r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"'
        raw_pairs = re.findall(pair_pattern, args_str)
        if not raw_pairs:
            return []

        def decode_json_string(raw: str) -> str:
            try:
                return json.loads(f'"{raw}"')
            except Exception:
                return raw

        recovered: List[Dict[str, Any]] = []
        current_step: Optional[Dict[str, Any]] = None

        if name_str in self.registry.list_all():
            recovered.append({"name": name_str, "arguments": {}})

        def flush_current():
            nonlocal current_step
            if current_step:
                recovered.append(current_step)
                current_step = None

        def find_skills_in_order(text: str) -> List[str]:
            hits = []
            for skill in skill_names:
                start = 0
                while True:
                    index = text.find(skill, start)
                    if index == -1:
                        break
                    hits.append((index, skill))
                    start = index + len(skill)
            hits.sort(key=lambda item: item[0])

            ordered = []
            for _, skill in hits:
                if not ordered or ordered[-1] != skill:
                    ordered.append(skill)
            return ordered

        for raw_key, raw_value in raw_pairs:
            key = decode_json_string(raw_key)
            value = self._coerce_argument_value(decode_json_string(raw_value))

            skills_in_key = find_skills_in_order(key)
            if skills_in_key:
                for skill_name in skills_in_key[:-1]:
                    flush_current()
                    recovered.append({"name": skill_name, "arguments": {}})

                flush_current()
                current_step = {"name": skills_in_key[-1], "arguments": {}}

                param_name = None
                if "<arg_key>" in key:
                    param_name = key.split("<arg_key>")[-1].strip()
                elif "\n" in key:
                    param_name = key.split("\n")[-1].strip()

                if param_name and param_name not in self.registry.list_all():
                    current_step["arguments"][param_name] = value
                continue

            clean_key = key.strip()
            if current_step and clean_key:
                current_step["arguments"][clean_key] = value

        flush_current()

        normalized: List[Dict[str, Any]] = []
        for step in recovered:
            if step["name"] in self.registry.list_all():
                normalized.append({
                    "name": step["name"],
                    "arguments": step.get("arguments", {})
                })

        if len(normalized) <= 1:
            return []
        return normalized

    def _coerce_argument_value(self, value: Any) -> Any:
        """把字符串参数转成更合适的类型。"""
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if stripped.isdigit():
            try:
                return int(stripped)
            except ValueError:
                pass

        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return stripped
    
    def _fix_tool_call(self, tool_call: Dict) -> Optional[Dict]:
        """
        修复格式混乱的工具调用
        智谱AI有时会返回格式错误的 tool_call
        """
        try:
            function_data = tool_call.get('function', {})
            name_str = function_data.get('name', '')
            args_str = function_data.get('arguments', '{}')
            
            # 如果参数是null或空，尝试从name_str中提取
            if not args_str or args_str == 'null' or args_str == '{}':
                # 可能是参数嵌在name中
                combined = name_str
            else:
                combined = name_str + args_str
            
            # 提取函数名
            import re
            function_name = None
            
            # 常见技能名模式
            skill_patterns = [
                r'(nav_\w+)',
                r'(motion_\w+)',
                r'(system_\w+)',
                r'(light_\w+)',
                r'(audio_\w+)',
                r'(smart_\w+)',
                r'(tts)',
                r'(play_audio)',
            ]
            
            for pattern in skill_patterns:
                match = re.search(pattern, combined)
                if match:
                    function_name = match.group(1)
                    break
            
            if not function_name:
                # 如果找不到，清理原始name
                # 移除所有XML标签
                import re
                cleaned_name = re.sub(r'<[^>]+>', '', name_str)
                cleaned_name = cleaned_name.strip()
                # 如果清理后还有内容，尝试匹配技能名
                if cleaned_name:
                    for pattern in skill_patterns:
                        match = re.search(pattern, cleaned_name)
                        if match:
                            function_name = match.group(1)
                            break
                
                if not function_name:
                    return None

            alias_map = {
                "tts": "tts_speak",
                "play_audio": "audio_play",
            }
            function_name = alias_map.get(function_name, function_name)
            
            # 提取参数
            args = {}
            
            # 方法1：标准XML格式
            pattern1 = r'<arg_key>([^<]+)</arg_key>\s*<arg_value>([^<]*)</arg_value>'
            matches1 = re.findall(pattern1, combined)
            for key, value in matches1:
                key = key.strip()
                if key and not key.startswith('<'):
                    args[key] = value.strip()
            
            # 方法2：简化的 <key>value</key> 格式
            if not args:
                pattern2 = r'<(map_name|location|color|mode|text|waypoint_id|file|audio_file|code|speed|preset_name)\u003e([^<]+)</\1>'
                matches2 = re.findall(pattern2, combined)
                for key, value in matches2:
                    args[key] = value.strip()
            
            # 方法3：JSON格式（可能被包裹在XML中）
            if not args:
                try:
                    # 尝试找JSON对象
                    json_match = re.search(r'\{[^}]+\}', combined)
                    if json_match:
                        args = json.loads(json_match.group(0))
                except:
                    pass
            
            # 特殊处理：如果提取的key包含XML标签，需要清理
            cleaned_args = {}
            for key, value in args.items():
                # 清理key
                clean_key = key.replace('</arg_key>', '').replace('<arg_value>', '').strip()
                if clean_key and not clean_key.startswith('<'):
                    if clean_key in {"waypoint_id", "code"}:
                        try:
                            value = int(value)
                        except (TypeError, ValueError):
                            pass
                    cleaned_args[clean_key] = value
            
            return {
                'name': function_name,
                'arguments': cleaned_args if cleaned_args else args
            }
            
        except Exception as e:
            print(f"[ERROR] 修复工具调用失败: {e}")
            return None
    
    # ===== Mission-mode overrides (keep near bottom to take precedence) =====
    def _detect_compound_instruction(self, user_input: str) -> str:
        """Detect compound instruction and bias model toward one submit_mission call."""
        user_input = user_input or ""
        user_lower = user_input.lower()
        connectors = ["然后", "再", "接着", "之后", "随后", "完成后", "并", "并且"]
        action_keywords = ["去", "到", "前往", "返回", "回充", "充电", "灯", "播报", "播放", "说"]

        connector_count = sum(1 for c in connectors if c in user_input)
        action_count = sum(1 for a in action_keywords if a in user_lower)
        if action_count >= 2 and connector_count >= 1:
            return (
                "[复合指令]\n"
                f"用户输入: \"{user_input}\"\n"
                "请只调用一次 submit_mission，并在 tasks 数组中按顺序覆盖全部动作。"
            )
        return ""

    def _planning_requirements_met(self, user_input: str, steps: List[Dict[str, Any]]) -> bool:
        """Mission模式下的完成判定：动作请求必须有 submit_mission 且 tasks 非空。"""
        if not steps:
            return False

        skill_names = [step.get("skill", "") for step in steps]
        has_submit_mission = any(name == "submit_mission" for name in skill_names)
        has_system_status = any(name == "system_status" for name in skill_names)

        if self._is_simple_status_query(user_input):
            return has_system_status or has_submit_mission

        if self._is_action_request(user_input):
            if not has_submit_mission:
                return False
            for step in reversed(steps):
                if step.get("skill") != "submit_mission":
                    continue
                params = step.get("params") or {}
                tasks = params.get("tasks")
                return isinstance(tasks, list) and len(tasks) > 0
            return False

        return bool(has_submit_mission or has_system_status)

    def _augment_steps_from_intent(
        self,
        user_input: str,
        existing_steps: List[Dict[str, Any]],
        round_steps: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """In mission mode, do not synthesize legacy micro-skills."""
        return round_steps

    def _fix_tool_call(self, tool_call: Dict) -> Optional[Dict]:
        """
        Normalize tool_call from provider to registry-compatible format.
        Priority: honor direct function name when it is already a registered skill.
        """
        try:
            function_data = tool_call.get("function", {}) or {}
            raw_name = str(function_data.get("name", "") or "").strip()
            raw_args = function_data.get("arguments", {})

            def _parse_arguments(raw: Any) -> Dict[str, Any]:
                if isinstance(raw, dict):
                    return raw
                if isinstance(raw, list):
                    return {"tasks": raw}
                if raw is None:
                    return {}
                if not isinstance(raw, str):
                    return {}

                text = raw.strip()
                if not text or text in {"null", "None"}:
                    return {}

                try:
                    decoded = json.loads(text)
                    if isinstance(decoded, dict):
                        return decoded
                    if isinstance(decoded, list):
                        return {"tasks": decoded}
                except Exception:
                    pass
                return {}

            if raw_name in self.registry.list_all():
                return {"name": raw_name, "arguments": _parse_arguments(raw_args)}

            args_text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False)
            combined = f"{raw_name}{args_text}"

            import re

            skill_patterns = [
                r"(submit_mission)",
                r"(system_status)",
                r"(nav_\w+)",
                r"(motion_\w+)",
                r"(system_\w+)",
                r"(light_\w+)",
                r"(audio_\w+)",
                r"(smart_\w+)",
                r"(tts)",
                r"(play_audio)",
            ]

            function_name = None
            for pattern in skill_patterns:
                match = re.search(pattern, combined)
                if match:
                    function_name = match.group(1)
                    break

            if not function_name:
                return None

            alias_map = {
                "tts": "tts_speak",
                "play_audio": "audio_play",
            }
            function_name = alias_map.get(function_name, function_name)

            args = _parse_arguments(raw_args)
            if not args and isinstance(raw_args, str):
                try:
                    json_match = re.search(r"\{.*\}", raw_args.strip())
                    if json_match:
                        decoded = json.loads(json_match.group(0))
                        if isinstance(decoded, dict):
                            args = decoded
                        elif isinstance(decoded, list):
                            args = {"tasks": decoded}
                except Exception:
                    pass

            return {"name": function_name, "arguments": args or {}}
        except Exception as e:
            print(f"[ERROR] 修复工具调用失败: {e}")
            return None

    def _current_intent_type(self) -> str:
        intent = str(self.session_context.get("current_intent_type") or "").strip().lower()
        return intent if intent in {"mission", "status", "chat"} else ""

    def _set_current_intent_type(self, intent_type: Optional[str]) -> str:
        normalized = str(intent_type or "").strip().lower()
        if normalized not in {"mission", "status", "chat"}:
            self.session_context["current_intent_type"] = None
            return ""
        self.session_context["current_intent_type"] = normalized
        return normalized

    def _get_system_prompt(self) -> str:
        """Build the runtime prompt from docs and add low-latency planning rules."""
        config = get_config()
        identity = config.app.identity
        base_prompt = (self.prompt_manager.get_prompt() or "").strip()
        identity_doc = (self.prompt_manager.get_identity() or "").strip()
        agent_doc = (self.prompt_manager.get_agent() or "").strip()
        tools_doc = (self.prompt_manager.get_tools() or "").strip()
        soul_doc = (self.prompt_manager.get_soul() or "").strip()

        available_tools = self._get_available_tools("")
        tool_lines = "\n".join(
            f"- {tool['function']['name']}: {tool['function']['description']}"
            for tool in available_tools
            if tool.get("function", {}).get("name")
        )

        world_prompt = self._get_world_prompt_info()
        soul_prompt = self._get_soul_prompt_info()
        current_map = self.session_context.get("current_map", {})
        if isinstance(current_map, dict) and current_map:
            map_info = f"{current_map.get('name', '未命名')}(ID:{current_map.get('id', 'unknown')})"
        else:
            map_info = "未加载"

        runtime_rules = (
            "# Runtime Rules\n"
            "【追问规则】：如果用户指令缺少关键地点或信息，导致无法执行，请直接回复自然语言追问，绝对不要调用任何工具。\n"
            "【一站式规划铁律】：只要信息充足，你必须将所有需要的物理动作（移动、亮灯、播报、等待）一次性全部打包进 submit_mission 的 tasks 数组中。禁止自己一步一步拆解工具调用。\n"
            "【状态查询规则】：纯状态、电量、充电查询时，只允许调用 system_status，然后直接文字回复。\n"
            "【闲聊规则】：身份介绍、解释说明、普通闲聊时，不要调用任何工具。"
        )

        sections = [section for section in (base_prompt, runtime_rules) if section]
        if identity_doc:
            sections.append(f"# Identity 文档\n{identity_doc}")
        if agent_doc:
            sections.append(f"# Agent 文档\n{agent_doc}")
        if tools_doc:
            sections.append(f"# Tools 文档\n{tools_doc}")
        if soul_doc:
            sections.append(f"# Soul 文档\n{soul_doc}")
        if tool_lines:
            sections.append(f"# 可用工具\n{tool_lines}")
        if world_prompt:
            sections.append(f"# World 上下文\n{world_prompt}")
        if soul_prompt:
            sections.append(f"# Soul 上下文\n{soul_prompt}")
        sections.append(
            "# 当前状态\n"
            f"- 身份: {identity}\n"
            f"- 地图: {map_info}\n"
            f"- 位置: {self.session_context.get('current_location', '未知')}\n"
            f"- 当前意图: {self._current_intent_type() or 'unknown'}"
        )
        return "\n\n---\n\n".join(section for section in sections if section)

    def _resolve_input_with_llm_clarification(self, user_input: str) -> Dict[str, Any]:
        """Disabled fast path placeholder: the main LLM loop now handles clarification directly."""
        return {
            "status": "proceed",
            "effective_input": str(user_input or ""),
            "intent_type": self._current_intent_type() or "",
        }

    def _detect_compound_instruction(self, user_input: str) -> str:
        """Compound handling is delegated to the main prompt and LLM planner."""
        return ""

    def _get_available_tools(self, user_input: str) -> List[Dict[str, Any]]:
        """Expose both top-level tools and let the main LLM choose between text reply and tool call."""
        allowed_names = {"submit_mission", "system_status"}
        return [
            tool
            for tool in self.registry.get_tools()
            if tool.get("function", {}).get("name") in allowed_names
        ]

    def _is_action_request(self, user_input: str) -> bool:
        return self._current_intent_type() == "mission"

    def _is_simple_status_query(self, user_input: str) -> bool:
        return self._current_intent_type() == "status"

    def _planning_requirements_met(self, user_input: str, steps: List[Dict[str, Any]]) -> bool:
        skill_names = [step.get("skill", "") for step in steps]
        if not skill_names:
            return False

        intent_type = self._current_intent_type()
        if intent_type == "chat":
            return True
        if intent_type == "status":
            return any(name == "system_status" for name in skill_names)
        if intent_type == "mission":
            for step in steps:
                if step.get("skill") != "submit_mission":
                    continue
                params = step.get("params", {})
                tasks = params.get("tasks") if isinstance(params, dict) else None
                if isinstance(tasks, list) and tasks:
                    return True
            return False
        return bool(skill_names)

    def _get_planning_followup_hint(self, user_input: str, steps: List[Dict[str, Any]]) -> str:
        planned = ", ".join(step.get("skill", "") for step in steps if step.get("skill"))
        intent_type = self._current_intent_type()
        if intent_type == "mission":
            return (
                "[规划未完成]\n"
                f"原始输入: {user_input}\n"
                f"当前步骤: {planned}\n"
                "这是一个任务请求。请补全为一次 submit_mission 调用，并确保 tasks 数组完整覆盖用户要做的事。"
            )
        if intent_type == "status":
            return (
                "[规划未完成]\n"
                f"原始输入: {user_input}\n"
                f"当前步骤: {planned}\n"
                "这是一个状态查询。请使用 system_status，并直接给出简洁文字回答。"
            )
        return (
            "[规划未完成]\n"
            f"原始输入: {user_input}\n"
            f"当前步骤: {planned}\n"
            "请继续补全当前轮次需要的输出。"
        )

    def _augment_steps_from_intent(self, user_input: str, existing_steps: List[Dict[str, Any]], round_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Do not synthesize semantic steps from keywords; trust the LLM plan."""
        return round_steps

    def _rule_based_think(self, user_input: str):
        """基于规则的思考（LLM不可用时使用）"""
        from fishmindos.brain.smart_brain import SmartBrain
        
        rule_brain = SmartBrain(self.registry, self.adapter)
        brain_responses = rule_brain.think(user_input)
        
        for resp in brain_responses:
            yield BrainResponse(
                type=resp.type,
                content=resp.content,
                metadata=resp.metadata
            )
    
    def _update_context(self, skill_name: str, result: Dict):
        """更新会话上下文 - 安全处理失败结果"""
        # 安全获取 data，防止为 None
        data = result.get("data")
        if not isinstance(data, dict):
            data = {}
        
        # nav_start 成功时，保存当前地图信息
        if skill_name == "nav_start" and result.get("ok"):
            map_id = data.get("map_id") or data.get("id")
            map_name = data.get("map_name") or data.get("name")
            print(f"[DEBUG] nav_start 结果: map_id={map_id}, map_name={map_name}")
            if map_id:
                self.session_context["current_map"] = {
                    "id": map_id,
                    "name": map_name or str(map_id)
                }
                self.session_context["current_location"] = map_name or str(map_id)
                print(f"[DEBUG] 上下文已更新: current_map={self.session_context['current_map']}")
        
        # nav_goto_location 成功时，保存当前位置
        if skill_name == "nav_goto_location" and result.get("ok"):
            location = data.get("location") or data.get("waypoint_name")
            if location:
                self.session_context["current_location"] = location
            waypoint_id = data.get("waypoint_id")
            waypoint_name = data.get("waypoint_name") or location
            if waypoint_id:
                pending = {"waypoint_id": waypoint_id, "name": waypoint_name}
                self.session_context["pending_arrival"] = pending
                self.session_context["last_waypoint"] = pending

        if skill_name == "system_wait" and result.get("ok") and data.get("event_type") == "arrival":
            self.session_context.pop("pending_arrival", None)
        
        if skill_name == "item_pickup" and result.get("ok"):
            self.session_context["carrying_item"] = data.get("item")
        
        if skill_name == "item_dropoff" and result.get("ok"):
            self.session_context["carrying_item"] = None
    
    def think_simple(self, user_input: str) -> List[Dict[str, Any]]:
        """简化的思考接口（兼容旧版）"""
        simple_responses = []
        for resp in self.think(user_input):
            if resp.type == "action":
                simple_responses.append({
                    "type": "skill_call",
                    "skill": resp.metadata.get("skill", ""),
                    "params": resp.metadata.get("params", {})
                })
            elif resp.type == "result":
                simple_responses.append({
                    "type": "skill_result",
                    "success": resp.metadata.get("success", False),
                    "message": resp.content
                })
            elif resp.type == "text":
                simple_responses.append({
                    "type": "text",
                    "text": resp.content
                })
        
        return simple_responses
    
    def cancel(self):
        """取消当前任务"""
        self._cancel_event.set()
    
    def get_current_plan(self) -> Optional[TaskPlan]:
        """获取当前任务计划"""
        return self._current_plan
    
    @staticmethod
    def list_supported_providers() -> List[str]:
        """列出支持的LLM提供商"""
        from fishmindos.brain.llm_providers import LLMFactory
        return LLMFactory.list_providers()

