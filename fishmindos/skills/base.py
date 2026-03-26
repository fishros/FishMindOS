"""
技能基类和接口定义
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from fishmindos.core.models import SkillContext, SkillResult


class Skill(ABC):
    """
    技能基类
    所有机器狗技能都需要继承此类
    """
    
    # 技能元数据
    name: str = ""
    description: str = ""
    category: str = "general"  # 技能分类: navigation, motion, system, etc.
    version: str = "1.0.0"
    
    # 是否作为工具暴露给LLM
    expose_as_tool: bool = True
    
    # 输入参数定义 (JSON Schema格式)
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    def __init__(self):
        self._adapter = None
    
    def set_adapter(self, adapter):
        """设置适配器"""
        self._adapter = adapter
    
    @property
    def adapter(self):
        """获取适配器"""
        return self._adapter
    
    @abstractmethod
    def execute(self, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        """
        执行技能
        
        Args:
            params: 技能参数
            context: 执行上下文
            
        Returns:
            SkillResult: 执行结果
        """
        pass
    
    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        验证参数
        
        Returns:
            (是否有效, 错误信息)
        """
        required = self.parameters.get("required", [])
        properties = self.parameters.get("properties", {})
        
        for field in required:
            if field not in params or params[field] is None:
                return False, f"缺少必需参数: {field}"
        
        for field, value in params.items():
            if field in properties:
                prop_schema = properties[field]
                if not self._validate_type(value, prop_schema.get("type")):
                    return False, f"参数 {field} 类型错误"
        
        return True, ""
    
    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """验证参数类型"""
        if expected_type == "string":
            return isinstance(value, str)
        elif expected_type == "integer":
            return isinstance(value, int)
        elif expected_type == "number":
            return isinstance(value, (int, float))
        elif expected_type == "boolean":
            return isinstance(value, bool)
        elif expected_type == "array":
            return isinstance(value, list)
        elif expected_type == "object":
            return isinstance(value, dict)
        return True
    
    def get_tool_definition(self) -> Dict[str, Any]:
        """
        获取工具定义 (用于LLM function calling)
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def run(self, params: Dict[str, Any], context_dict: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        运行技能 (兼容旧接口)
        修复：执行后将上下文数据写回外部状态
        """
        context = SkillContext()
        if context_dict:
            context.user_text = context_dict.get("user_text", "")
            # 深拷贝外部状态到技能上下文
            context.session_data = context_dict.copy()
            # Keep a live reference for async executors that need to update the real session later.
            context.shared_session_data = context_dict
        
        # 参数验证
        valid, error = self.validate_params(params)
        if not valid:
            return {"ok": False, "detail": error, "data": None}
        
        try:
            result = self.execute(params, context)
            # 检查结果有效性
            if result is None:
                return {"ok": False, "detail": "技能返回None", "data": None}
            if not hasattr(result, 'to_dict'):
                return {"ok": False, "detail": "技能结果格式错误", "data": None}
            
            result_dict = result.to_dict()
            if result_dict is None:
                return {"ok": False, "detail": "to_dict返回None", "data": None}
            
            # 修复：将技能上下文数据写回外部状态
            if context_dict is not None:
                context_dict.update(context.session_data)
            return result_dict
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"ok": False, "detail": f"执行异常: {str(e)}", "data": None}


class MacroSkill(Skill):
    """
    宏技能基类
    可以组合多个基础技能
    """
    
    sub_skills: List[str] = []  # 子技能列表
    
    def __init__(self, skill_registry=None):
        super().__init__()
        self._registry = skill_registry
    
    def set_registry(self, registry):
        """设置技能注册表"""
        self._registry = registry
    
    def call_skill(self, skill_name: str, params: Dict[str, Any], context: SkillContext) -> SkillResult:
        """调用其他技能"""
        if not self._registry:
            return SkillResult(False, "技能注册表未设置")
        
        skill = self._registry.get(skill_name)
        if not skill:
            return SkillResult(False, f"技能 {skill_name} 不存在")
        
        return skill.execute(params, context)


class SkillRegistry:
    """
    技能注册表
    管理所有可用的技能
    """
    
    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._categories: Dict[str, List[str]] = {}
    
    def register(self, skill: Skill) -> None:
        """注册技能"""
        if not skill.name:
            raise ValueError("技能必须有名称")
        
        # 检查重复
        if skill.name in self._skills:
            print(f"[WARN] 技能 '{skill.name}' 已存在，跳过重复注册")
            return
        
        self._skills[skill.name] = skill
        
        # 按分类组织
        category = getattr(skill, "category", "general")
        if category not in self._categories:
            self._categories[category] = []
        if skill.name not in self._categories[category]:
            self._categories[category].append(skill.name)
    
    def unregister(self, name: str) -> bool:
        """注销技能"""
        if name in self._skills:
            skill = self._skills[name]
            del self._skills[name]
            
            # 从分类中移除
            category = getattr(skill, "category", "general")
            if category in self._categories and name in self._categories[category]:
                self._categories[category].remove(name)
            return True
        return False
    
    def get(self, name: str) -> Optional[Skill]:
        """获取技能"""
        return self._skills.get(name)
    
    def has(self, name: str) -> bool:
        """检查技能是否存在"""
        return name in self._skills
    
    def list_all(self) -> List[str]:
        """列出所有技能名称"""
        return list(self._skills.keys())
    
    def list_by_category(self, category: str) -> List[str]:
        """按分类列出技能"""
        return self._categories.get(category, [])
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取所有可作为工具的技能定义"""
        tools = []
        for skill in self._skills.values():
            if getattr(skill, "expose_as_tool", True):
                tools.append(skill.get_tool_definition())
        return tools
    
    def set_adapter_for_all(self, adapter):
        """为所有技能设置适配器"""
        for skill in self._skills.values():
            skill.set_adapter(adapter)


class SkillExecutor:
    """
    技能执行器
    负责任务的执行和协调
    """
    
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._execution_history: List[Dict] = []
    
    def execute(self, skill_name: str, params: Dict[str, Any], 
                context: SkillContext = None) -> SkillResult:
        """执行单个技能"""
        if context is None:
            context = SkillContext()
        
        skill = self.registry.get(skill_name)
        if not skill:
            return SkillResult(False, f"技能 {skill_name} 不存在")
        
        # 记录执行历史
        execution_record = {
            "skill": skill_name,
            "params": params,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "status": "running"
        }
        self._execution_history.append(execution_record)
        
        try:
            # 验证参数
            valid, error = skill.validate_params(params)
            if not valid:
                execution_record["status"] = "failed"
                execution_record["error"] = error
                return SkillResult(False, error)
            
            # 执行技能
            result = skill.execute(params, context)
            
            execution_record["status"] = "success" if result.success else "failed"
            execution_record["result"] = result.message
            
            return result
            
        except Exception as e:
            execution_record["status"] = "failed"
            execution_record["error"] = str(e)
            return SkillResult(False, f"执行异常: {str(e)}")
    
    def execute_chain(self, steps: List[Dict[str, Any]], 
                     context: SkillContext = None) -> SkillResult:
        """
        执行技能链
        
        steps格式: [
            {"skill": "skill_name", "params": {...}, "on_fail": "abort|continue"},
            ...
        ]
        """
        if context is None:
            context = SkillContext()
        
        results = []
        for i, step in enumerate(steps):
            skill_name = step.get("skill")
            params = step.get("params", {})
            on_fail = step.get("on_fail", "abort")
            
            result = self.execute(skill_name, params, context)
            results.append({
                "step": i + 1,
                "skill": skill_name,
                "success": result.success,
                "message": result.message
            })
            
            if not result.success:
                if on_fail == "abort":
                    return SkillResult(
                        False, 
                        f"步骤 {i+1} 失败: {result.message}",
                        {"executed_steps": results}
                    )
        
        return SkillResult(
            True,
            f"成功执行 {len(steps)} 个步骤",
            {"steps": results}
        )
    
    def get_history(self) -> List[Dict]:
        """获取执行历史"""
        return self._execution_history.copy()
