from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional


# ========== 配置数据类 ==========

@dataclass
class LLMConfig:
    """LLM配置 - 支持多提供商"""
    provider: str = "zhipu"  # zhipu, openai, claude, qwen, gemini, ollama
    api_key: str = ""
    base_url: Optional[str] = None  # 自定义API地址（如需要）
    model: str = "glm-4.5-Air"
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 30
    max_iterations: int = 4


@dataclass
class NavServerConfig:
    """导航服务器配置"""
    host: str = "127.0.0.1"
    port: int = 8888


@dataclass
class NavAppConfig:
    """导航应用配置"""
    host: str = "127.0.0.1"
    port: int = 8888


@dataclass
class RosbridgeConfig:
    """Rosbridge WebSocket配置"""
    host: str = "127.0.0.1"
    port: int = 8888
    path: str = "/api/rt"
    use_ssl: bool = False


@dataclass
class WebSocketConfig:
    """WebSocket通用配置"""
    enabled: bool = True
    reconnect_interval: int = 5
    max_reconnect_attempts: int = 10
    ping_interval: int = 30


@dataclass
class CallbackConfig:
    """回调配置"""
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8081
    path: str = "/callback/nav_event"
    url: Optional[str] = None
    max_events: int = 100

    def get_url(self) -> str:
        if self.url:
            return self.url
        host = "127.0.0.1" if self.host == "0.0.0.0" else self.host
        path = self.path or "/callback/nav_event"
        if not path.startswith("/"):
            path = f"/{path}"
        return f"http://{host}:{self.port}{path}"


@dataclass
class WorldConfig:
    """Semantic world configuration."""
    enabled: bool = True
    path: str = "fishmindos/world/semantic_map.json"
    auto_switch_map: bool = True
    prefer_current_map: bool = True
    adapter_fallback: bool = False


@dataclass
class SoulConfig:
    """Long-term learning configuration."""
    enabled: bool = True
    path: str = "fishmindos/soul/soul.json"
    max_memories: int = 200


@dataclass
class SkillConfig:
    """技能配置"""
    search_paths: list = field(default_factory=lambda: ["skill_store", "skills"])
    hot_reload: bool = False
    auto_discover: bool = True


@dataclass
class MissionConfig:
    """任务流执行配置"""
    wait_confirm_reminder_enabled: bool = True
    wait_confirm_reminder_interval_sec: int = 20
    wait_confirm_reminder_text: str = "请确认后我再继续执行。"


@dataclass
class AppConfig:
    """应用全局配置"""
    debug: bool = False
    log_level: str = "INFO"
    identity: str = "机器人助手"
    prompt_profile: Optional[str] = None
    language: str = "zh"


@dataclass
class FishMindConfig:
    """FishMindOS 完整配置"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    nav_server: NavServerConfig = field(default_factory=NavServerConfig)
    nav_app: NavAppConfig = field(default_factory=NavAppConfig)
    rosbridge: RosbridgeConfig = field(default_factory=RosbridgeConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    callback: CallbackConfig = field(default_factory=CallbackConfig)
    world: WorldConfig = field(default_factory=WorldConfig)
    soul: SoulConfig = field(default_factory=SoulConfig)
    mission: MissionConfig = field(default_factory=MissionConfig)
    skills: SkillConfig = field(default_factory=SkillConfig)
    app: AppConfig = field(default_factory=AppConfig)
    
    @classmethod
    def from_file(cls, config_path: str) -> "FishMindConfig":
        """从文件加载配置"""
        path = Path(config_path)
        
        if not path.exists():
            return cls()
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return cls._from_dict(data)
    
    @classmethod
    def from_env(cls) -> "FishMindConfig":
        """从环境变量加载配置"""
        config = cls()
        
        # LLM配置
        if os.getenv("FISHMIND_LLM_PROVIDER"):
            config.llm.provider = os.getenv("FISHMIND_LLM_PROVIDER")
        if os.getenv("FISHMIND_LLM_API_KEY"):
            config.llm.api_key = os.getenv("FISHMIND_LLM_API_KEY")
        if os.getenv("FISHMIND_LLM_MODEL"):
            config.llm.model = os.getenv("FISHMIND_LLM_MODEL")
        if os.getenv("FISHMIND_LLM_BASE_URL"):
            config.llm.base_url = os.getenv("FISHMIND_LLM_BASE_URL")
        if os.getenv("FISHMIND_LLM_MAX_ITERATIONS"):
            config.llm.max_iterations = int(os.getenv("FISHMIND_LLM_MAX_ITERATIONS"))
        
        # 服务器配置
        if os.getenv("FISHMIND_NAV_SERVER_HOST"):
            config.nav_server.host = os.getenv("FISHMIND_NAV_SERVER_HOST")
        if os.getenv("FISHMIND_NAV_SERVER_PORT"):
            config.nav_server.port = int(os.getenv("FISHMIND_NAV_SERVER_PORT"))
        if os.getenv("FISHMIND_NAV_APP_HOST"):
            config.nav_app.host = os.getenv("FISHMIND_NAV_APP_HOST")
        if os.getenv("FISHMIND_NAV_APP_PORT"):
            config.nav_app.port = int(os.getenv("FISHMIND_NAV_APP_PORT"))
        
        # Rosbridge配置
        if os.getenv("FISHMIND_ROSBRIDGE_HOST"):
            config.rosbridge.host = os.getenv("FISHMIND_ROSBRIDGE_HOST")
        if os.getenv("FISHMIND_ROSBRIDGE_PORT"):
            config.rosbridge.port = int(os.getenv("FISHMIND_ROSBRIDGE_PORT"))

        if os.getenv("FISHMIND_CALLBACK_ENABLED"):
            config.callback.enabled = os.getenv("FISHMIND_CALLBACK_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_CALLBACK_HOST"):
            config.callback.host = os.getenv("FISHMIND_CALLBACK_HOST")
        if os.getenv("FISHMIND_CALLBACK_PORT"):
            config.callback.port = int(os.getenv("FISHMIND_CALLBACK_PORT"))
        if os.getenv("FISHMIND_CALLBACK_PATH"):
            config.callback.path = os.getenv("FISHMIND_CALLBACK_PATH")
        if os.getenv("FISHMIND_CALLBACK_URL"):
            config.callback.url = os.getenv("FISHMIND_CALLBACK_URL")
        if os.getenv("FISHMIND_WORLD_ENABLED"):
            config.world.enabled = os.getenv("FISHMIND_WORLD_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_WORLD_PATH"):
            config.world.path = os.getenv("FISHMIND_WORLD_PATH")
        if os.getenv("FISHMIND_WORLD_AUTO_SWITCH_MAP"):
            config.world.auto_switch_map = os.getenv("FISHMIND_WORLD_AUTO_SWITCH_MAP").lower() == "true"
        if os.getenv("FISHMIND_WORLD_PREFER_CURRENT_MAP"):
            config.world.prefer_current_map = os.getenv("FISHMIND_WORLD_PREFER_CURRENT_MAP").lower() == "true"
        if os.getenv("FISHMIND_WORLD_ADAPTER_FALLBACK"):
            config.world.adapter_fallback = os.getenv("FISHMIND_WORLD_ADAPTER_FALLBACK").lower() == "true"
        if os.getenv("FISHMIND_SOUL_ENABLED"):
            config.soul.enabled = os.getenv("FISHMIND_SOUL_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_SOUL_PATH"):
            config.soul.path = os.getenv("FISHMIND_SOUL_PATH")
        if os.getenv("FISHMIND_SOUL_MAX_MEMORIES"):
            config.soul.max_memories = int(os.getenv("FISHMIND_SOUL_MAX_MEMORIES"))
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_ENABLED"):
            config.mission.wait_confirm_reminder_enabled = os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_INTERVAL_SEC"):
            config.mission.wait_confirm_reminder_interval_sec = int(os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_INTERVAL_SEC"))
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_TEXT"):
            config.mission.wait_confirm_reminder_text = os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_TEXT")
        if os.getenv("FISHMIND_APP_IDENTITY"):
            config.app.identity = os.getenv("FISHMIND_APP_IDENTITY")
        if os.getenv("FISHMIND_APP_PROMPT_PROFILE"):
            config.app.prompt_profile = os.getenv("FISHMIND_APP_PROMPT_PROFILE") or None
        
        return config
    
    @classmethod
    def auto_load(cls, config_path: str = "fishmindos.config.json") -> "FishMindConfig":
        """自动加载配置（优先级：环境变量 > 配置文件 > 默认值）
        
        环境变量按字段覆盖，不是整块替换：
        - FISHMIND_LLM_PROVIDER: 覆盖 llm.provider
        - FISHMIND_LLM_MODEL: 覆盖 llm.model
        - 以此类推...
        """
        # 1. 从文件加载基础配置
        config = cls.from_file(config_path)
        
        # 2. 按字段应用环境变量覆盖（细粒度）
        # LLM 配置
        if os.getenv("FISHMIND_LLM_PROVIDER"):
            config.llm.provider = os.getenv("FISHMIND_LLM_PROVIDER")
        if os.getenv("FISHMIND_LLM_API_KEY"):
            config.llm.api_key = os.getenv("FISHMIND_LLM_API_KEY")
        if os.getenv("FISHMIND_LLM_MODEL"):
            config.llm.model = os.getenv("FISHMIND_LLM_MODEL")
        if os.getenv("FISHMIND_LLM_BASE_URL"):
            config.llm.base_url = os.getenv("FISHMIND_LLM_BASE_URL")
        if os.getenv("FISHMIND_LLM_TEMPERATURE"):
            config.llm.temperature = float(os.getenv("FISHMIND_LLM_TEMPERATURE"))
        if os.getenv("FISHMIND_LLM_MAX_TOKENS"):
            config.llm.max_tokens = int(os.getenv("FISHMIND_LLM_MAX_TOKENS"))
        if os.getenv("FISHMIND_LLM_TIMEOUT"):
            config.llm.timeout = int(os.getenv("FISHMIND_LLM_TIMEOUT"))
        if os.getenv("FISHMIND_LLM_MAX_ITERATIONS"):
            config.llm.max_iterations = int(os.getenv("FISHMIND_LLM_MAX_ITERATIONS"))
        
        # 导航服务器配置
        if os.getenv("FISHMIND_NAV_SERVER_HOST"):
            config.nav_server.host = os.getenv("FISHMIND_NAV_SERVER_HOST")
        if os.getenv("FISHMIND_NAV_SERVER_PORT"):
            config.nav_server.port = int(os.getenv("FISHMIND_NAV_SERVER_PORT"))
        
        # 导航应用配置
        if os.getenv("FISHMIND_NAV_APP_HOST"):
            config.nav_app.host = os.getenv("FISHMIND_NAV_APP_HOST")
        if os.getenv("FISHMIND_NAV_APP_PORT"):
            config.nav_app.port = int(os.getenv("FISHMIND_NAV_APP_PORT"))
        
        # Rosbridge 配置
        if os.getenv("FISHMIND_ROSBRIDGE_HOST"):
            config.rosbridge.host = os.getenv("FISHMIND_ROSBRIDGE_HOST")
        if os.getenv("FISHMIND_ROSBRIDGE_PORT"):
            config.rosbridge.port = int(os.getenv("FISHMIND_ROSBRIDGE_PORT"))
        if os.getenv("FISHMIND_ROSBRIDGE_PATH"):
            config.rosbridge.path = os.getenv("FISHMIND_ROSBRIDGE_PATH")
        if os.getenv("FISHMIND_CALLBACK_ENABLED"):
            config.callback.enabled = os.getenv("FISHMIND_CALLBACK_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_CALLBACK_HOST"):
            config.callback.host = os.getenv("FISHMIND_CALLBACK_HOST")
        if os.getenv("FISHMIND_CALLBACK_PORT"):
            config.callback.port = int(os.getenv("FISHMIND_CALLBACK_PORT"))
        if os.getenv("FISHMIND_CALLBACK_PATH"):
            config.callback.path = os.getenv("FISHMIND_CALLBACK_PATH")
        if os.getenv("FISHMIND_CALLBACK_URL"):
            config.callback.url = os.getenv("FISHMIND_CALLBACK_URL")
        if os.getenv("FISHMIND_WORLD_ENABLED"):
            config.world.enabled = os.getenv("FISHMIND_WORLD_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_WORLD_PATH"):
            config.world.path = os.getenv("FISHMIND_WORLD_PATH")
        if os.getenv("FISHMIND_WORLD_AUTO_SWITCH_MAP"):
            config.world.auto_switch_map = os.getenv("FISHMIND_WORLD_AUTO_SWITCH_MAP").lower() == "true"
        if os.getenv("FISHMIND_WORLD_PREFER_CURRENT_MAP"):
            config.world.prefer_current_map = os.getenv("FISHMIND_WORLD_PREFER_CURRENT_MAP").lower() == "true"
        if os.getenv("FISHMIND_WORLD_ADAPTER_FALLBACK"):
            config.world.adapter_fallback = os.getenv("FISHMIND_WORLD_ADAPTER_FALLBACK").lower() == "true"
        if os.getenv("FISHMIND_SOUL_ENABLED"):
            config.soul.enabled = os.getenv("FISHMIND_SOUL_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_SOUL_PATH"):
            config.soul.path = os.getenv("FISHMIND_SOUL_PATH")
        if os.getenv("FISHMIND_SOUL_MAX_MEMORIES"):
            config.soul.max_memories = int(os.getenv("FISHMIND_SOUL_MAX_MEMORIES"))
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_ENABLED"):
            config.mission.wait_confirm_reminder_enabled = os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_ENABLED").lower() == "true"
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_INTERVAL_SEC"):
            config.mission.wait_confirm_reminder_interval_sec = int(os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_INTERVAL_SEC"))
        if os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_TEXT"):
            config.mission.wait_confirm_reminder_text = os.getenv("FISHMIND_WAIT_CONFIRM_REMINDER_TEXT")
        
        # 技能配置
        if os.getenv("FISHMIND_SKILLS_HOT_RELOAD"):
            config.skills.hot_reload = os.getenv("FISHMIND_SKILLS_HOT_RELOAD").lower() == "true"
        
        # 应用配置
        if os.getenv("FISHMIND_APP_DEBUG"):
            config.app.debug = os.getenv("FISHMIND_APP_DEBUG").lower() == "true"
        if os.getenv("FISHMIND_APP_LOG_LEVEL"):
            config.app.log_level = os.getenv("FISHMIND_APP_LOG_LEVEL")
        if os.getenv("FISHMIND_APP_IDENTITY"):
            config.app.identity = os.getenv("FISHMIND_APP_IDENTITY")
        if os.getenv("FISHMIND_APP_PROMPT_PROFILE"):
            config.app.prompt_profile = os.getenv("FISHMIND_APP_PROMPT_PROFILE") or None
        
        return config
    
    def save_to_file(self, config_path: str):
        """保存配置到文件"""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._to_dict(), f, indent=2, ensure_ascii=False)
    
    def _to_dict(self) -> Dict[str, Any]:
        return {
            "llm": asdict(self.llm),
            "nav_server": asdict(self.nav_server),
            "nav_app": asdict(self.nav_app),
            "rosbridge": asdict(self.rosbridge),
            "websocket": asdict(self.websocket),
            "callback": asdict(self.callback),
            "world": asdict(self.world),
            "soul": asdict(self.soul),
            "mission": asdict(self.mission),
            "skills": asdict(self.skills),
            "app": asdict(self.app)
        }
    
    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "FishMindConfig":
        config = cls()
        if "llm" in data:
            config.llm = LLMConfig(**data["llm"])
        if "nav_server" in data:
            config.nav_server = NavServerConfig(**data["nav_server"])
        if "nav_app" in data:
            config.nav_app = NavAppConfig(**data["nav_app"])
        if "rosbridge" in data:
            config.rosbridge = RosbridgeConfig(**data["rosbridge"])
        if "websocket" in data:
            config.websocket = WebSocketConfig(**data["websocket"])
        if "callback" in data:
            callback_data = dict(data["callback"])
            if "ip" in callback_data and "host" not in callback_data:
                callback_data["host"] = callback_data.pop("ip")
            config.callback = CallbackConfig(**callback_data)
        if "world" in data:
            config.world = WorldConfig(**data["world"])
        if "soul" in data:
            config.soul = SoulConfig(**data["soul"])
        if "mission" in data:
            config.mission = MissionConfig(**data["mission"])
        if "skills" in data:
            config.skills = SkillConfig(**data["skills"])
        if "app" in data:
            config.app = AppConfig(**data["app"])
        return config


# ========== 向后兼容的旧配置函数 ==========

DEFAULT_CONFIG_FILE = "fishmindos.config.json"


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    if config_path is not None:
        return Path(config_path)
    env_path = os.getenv("FISHMINDOS_CONFIG_FILE")
    if env_path:
        return Path(env_path)
    return Path.cwd() / DEFAULT_CONFIG_FILE


def load_runtime_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = resolve_config_path(config_path)
    if not path.exists():
        return {}
    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        return {}
    data = json.loads(raw_text)
    if not isinstance(data, dict):
        raise ValueError("FishMindOS config file must contain a JSON object.")
    return data


def get_config_value(
    section: str,
    key: str,
    env_var: str,
    default: Any = None,
    config_path: str | Path | None = None,
) -> Any:
    env_value = os.getenv(env_var)
    if env_value not in (None, ""):
        return env_value
    data = load_runtime_config(config_path=config_path)
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        return default
    value = section_data.get(key, default)
    if value in ("", None):
        return default
    return value


def get_section_config(
    section: str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    data = load_runtime_config(config_path=config_path)
    section_data = data.get(section, {})
    if not isinstance(section_data, dict):
        return {}
    return dict(section_data)


# ========== 全局配置实例 ==========

_config: Optional[FishMindConfig] = None


def get_config() -> FishMindConfig:
    """获取全局配置"""
    global _config
    if _config is None:
        _config = FishMindConfig.auto_load()
    return _config


def set_config(config: FishMindConfig):
    """设置全局配置"""
    global _config
    _config = config
