"""
FishMindOS - Main Application Entry Point
Simplified version for one-click startup
"""

from __future__ import annotations

import argparse
import os
import sys
import signal
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fishmindos.skills import create_default_registry, SkillRegistry
from fishmindos.skills.loader import create_skill_manager, SkillManager
from fishmindos.adapters import create_fishbot_adapter
from fishmindos.brain.llm_brain import LLMBrain
from fishmindos.interaction import InteractionManager, TerminalChannel
from fishmindos.interaction.callback_receiver import CallbackReceiver
from fishmindos.config import get_config
from fishmindos.world import WorldResolver
from fishmindos.soul import Soul


def _configure_console_encoding() -> None:
    """Configure a UTF-8 capable console on Windows."""
    if os.name != "nt":
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class FishMindOS:
    """
    FishMindOS Main Application
    Integrates all components for easy startup
    """
    
    def __init__(self):
        self.registry: Optional[SkillRegistry] = None
        self.skill_manager: Optional[SkillManager] = None
        self.adapter = None
        self.brain: Optional[LLMBrain] = None
        self.interaction: Optional[InteractionManager] = None
        self.interaction_channel: Optional[TerminalChannel] = None
        self.callback_receiver: Optional[CallbackReceiver] = None
        self.world_resolver: Optional[WorldResolver] = None
        self.soul: Optional[Soul] = None
        self._running = False

    def _apply_callback_config(self, config) -> Optional[str]:
        """把配置中的回调地址同步到适配器和会话上下文。"""
        callback = getattr(config, "callback", None)
        if callback is None:
            return None

        callback_url = callback.get_url() if callback.enabled else ""

        if self.adapter and hasattr(self.adapter, "set_callback_url"):
            self.adapter.set_callback_url(callback_url, callback.enabled)

        if self.brain:
            self.brain.session_context["callback_enabled"] = callback.enabled
            self.brain.session_context["callback_url"] = callback_url or "未设置"
            self.brain.session_context["callback_host"] = callback.host
            self.brain.session_context["callback_port"] = callback.port
            self.brain.session_context["callback_path"] = callback.path

        return callback_url or None

    def _should_start_embedded_callback_receiver(self, config) -> bool:
        callback = getattr(config, "callback", None)
        if callback is None or not callback.enabled:
            return False

        if not callback.url:
            return True

        try:
            parsed = urlparse(callback.url)
        except Exception:
            return False

        expected_host = "127.0.0.1" if callback.host == "0.0.0.0" else callback.host
        parsed_path = (parsed.path or "/").rstrip("/") or "/"
        expected_path = (callback.path or "/callback/nav_event").rstrip("/") or "/"
        return (
            parsed.hostname in {expected_host, callback.host, "127.0.0.1"}
            and parsed.port == callback.port
            and parsed_path == expected_path
        )

    def _sync_callback_state_to_brain(self) -> None:
        if not self.brain or not self.adapter or not hasattr(self.adapter, "get_callback_state"):
            return

        callback_state = self.adapter.get_callback_state()
        session = self.brain.session_context
        session["callback_event_count"] = callback_state.get("event_count", 0)
        session["callback_last_event"] = callback_state.get("last_event")
        session["callback_last_event_at"] = callback_state.get("last_event_at")

        if isinstance(callback_state.get("current_pose"), dict):
            session["callback_current_pose"] = callback_state.get("current_pose")

        if isinstance(callback_state.get("target_pose"), dict):
            session["callback_target_pose"] = callback_state.get("target_pose")

        current_map_id = callback_state.get("current_map_id")
        if current_map_id is not None:
            map_name = None
            if hasattr(self.adapter, "resolve_current_map") and getattr(self.adapter, "_connected", False):
                map_info = self.adapter.resolve_current_map()
                if map_info:
                    current_map_id = map_info.id
                    map_name = map_info.name
            session["current_map"] = {"id": current_map_id, "name": map_name or str(current_map_id)}

        arrived_waypoint_id = callback_state.get("arrived_waypoint_id")
        target_waypoint_name = callback_state.get("target_waypoint_name")
        if arrived_waypoint_id:
            session["pending_arrival"] = None
            session["last_waypoint"] = {"waypoint_id": arrived_waypoint_id, "name": target_waypoint_name}
            if target_waypoint_name:
                session["current_location"] = target_waypoint_name

        if callback_state.get("dock_complete_at"):
            session["current_location"] = "回充点"

    def _initialize_world(self, config) -> Optional[WorldResolver]:
        world_config = getattr(config, "world", None)
        if world_config is None or not world_config.enabled:
            self.world_resolver = None
            return None

        world_path = Path(world_config.path)
        if not world_path.is_absolute():
            world_path = Path.cwd() / world_path

        self.world_resolver = WorldResolver.from_path(
            world_path,
            adapter=self.adapter,
            soul=self.soul,
            auto_switch_map=world_config.auto_switch_map,
            prefer_current_map=world_config.prefer_current_map,
            adapter_fallback=world_config.adapter_fallback,
        )
        return self.world_resolver

    def _initialize_soul(self, config) -> Optional[Soul]:
        soul_config = getattr(config, "soul", None)
        if soul_config is None or not soul_config.enabled:
            self.soul = None
            return None

        soul_path = Path(soul_config.path)
        if not soul_path.is_absolute():
            soul_path = Path.cwd() / soul_path

        self.soul = Soul.from_path(str(soul_path), max_memories=soul_config.max_memories)
        return self.soul

    def _sync_world_to_brain(self) -> None:
        if not self.brain:
            return

        if self.world_resolver is None:
            self.brain.session_context.pop("world", None)
            self.brain.session_context.pop("world_model", None)
            self.brain.session_context["world_enabled"] = False
            self.brain.session_context.pop("world_summary", None)
            self.brain.session_context.pop("world_prompt", None)
            self.brain.session_context.pop("world_name", None)
            self.brain.session_context.pop("world_default_map", None)
            self.brain.session_context.pop("world_known_locations", None)
            self.brain.session_context.pop("world_adapter_fallback", None)
            return

        self.brain.session_context["world"] = self.world_resolver
        self.brain.session_context["world_model"] = self.world_resolver
        self.brain.session_context["world_enabled"] = True
        self.brain.session_context["world_summary"] = self.world_resolver.describe()
        self.brain.session_context["world_prompt"] = self.world_resolver.describe_for_prompt(limit=50)
        self.brain.session_context["world_name"] = getattr(self.world_resolver.world, "name", "default")
        self.brain.session_context["world_default_map"] = (
            self.world_resolver.world.default_map_name
            or self.world_resolver.world.default_map_id
        )
        self.brain.session_context["world_known_locations"] = self.world_resolver.list_known_locations()
        self.brain.session_context["world_adapter_fallback"] = self.world_resolver.adapter_fallback

    def _sync_soul_to_brain(self) -> None:
        if not self.brain:
            return

        if self.soul is None:
            if self.world_resolver and hasattr(self.world_resolver, "set_soul"):
                self.world_resolver.set_soul(None)
            self.brain.session_context.pop("soul", None)
            self.brain.session_context["soul_enabled"] = False
            self.brain.session_context.pop("soul_summary", None)
            self.brain.session_context.pop("soul_prompt", None)
            self.brain.session_context.pop("soul_preferences", None)
            return

        if self.world_resolver and hasattr(self.world_resolver, "set_soul"):
            self.world_resolver.set_soul(self.soul)
        self.brain.session_context["soul"] = self.soul
        self.brain.session_context["soul_enabled"] = True
        self.brain.session_context["soul_summary"] = self.soul.describe()
        self.brain.session_context["soul_prompt"] = self.soul.describe_for_prompt()
        self.brain.session_context["soul_preferences"] = {
            key: pref.value for key, pref in self.soul.state.preferences.items()
        }

    def _handle_callback_event(self, record) -> None:
        event = record.get("event", {})
        if self.adapter and hasattr(self.adapter, "handle_callback_event"):
            self.adapter.handle_callback_event(event)

        if self.brain:
            self.brain.session_context["callback_event_count"] = record.get("count", 0)
            self.brain.session_context["callback_last_payload"] = event
            self._sync_callback_state_to_brain()

    def _start_callback_receiver(self, config) -> Optional[str]:
        callback = getattr(config, "callback", None)
        if callback is None or not callback.enabled:
            return None
        if not self._should_start_embedded_callback_receiver(config):
            return None
        if self.callback_receiver is not None:
            return callback.get_url()

        receiver = CallbackReceiver(
            host=callback.host,
            port=callback.port,
            path=callback.path,
            max_events=callback.max_events,
        )
        receiver.add_handler(self._handle_callback_event)
        receiver.start()
        self.callback_receiver = receiver
        return callback.get_url()
    
    def initialize(
        self,
        nav_server_host: str = "127.0.0.1",
        nav_server_port: int = 9001,
        nav_app_host: str = "127.0.0.1",
        nav_app_port: int = 9002,
        skill_paths: Optional[list] = None,
        enable_hot_reload: bool = False
    ) -> bool:
        """
        Initialize the system
        
        Args:
            nav_server_host: nav_server address
            nav_server_port: nav_server port
            nav_app_host: nav_app address
            nav_app_port: nav_app port
            skill_paths: Additional skill search paths
            enable_hot_reload: Enable skill hot reload
            
        Returns:
            Whether initialization succeeded
        """
        try:
            # Load config
            config = get_config()
            
            print("正在初始化 FishMindOS...")
            print()
            
            # 1. Create skill registry
            print("1. Initializing skill system...")
            self.registry = create_default_registry()
            print(f"   Built-in skills: {len(self.registry.list_all())}")
            
            # 2. Load custom skills
            self.skill_manager = create_skill_manager(self.registry)
            # 合并配置文件中和 CLI 参数中的技能路径
            config_paths = config.skills.search_paths if hasattr(config.skills, 'search_paths') else []
            cli_paths = skill_paths if skill_paths else []
            paths = list(dict.fromkeys(config_paths + cli_paths))  # 去重且保持顺序
            loaded = self.skill_manager.initialize(
                search_paths=paths,
                enable_hot_reload=enable_hot_reload or config.skills.hot_reload
            )
            print(f"   Custom skills: {loaded}")
            
            # 3. Connect to robot
            print("2. Connecting to robot...")
            
            # Get Rosbridge settings from config
            rosbridge_host = config.rosbridge.host
            rosbridge_port = config.rosbridge.port
            rosbridge_path = config.rosbridge.path
            
            self.adapter = create_fishbot_adapter(
                nav_server_host=nav_server_host,
                nav_server_port=nav_server_port,
                nav_app_host=nav_app_host,
                nav_app_port=nav_app_port,
                rosbridge_host=rosbridge_host,
                rosbridge_port=rosbridge_port,
                rosbridge_path=rosbridge_path,
                status_cache_ttl_sec=getattr(config.app, "status_cache_ttl_sec", 1.0),
            )

            callback_url = self._apply_callback_config(config)
            callback_receiver_url = None
            if getattr(config, "callback", None) and config.callback.enabled:
                try:
                    callback_receiver_url = self._start_callback_receiver(config)
                except OSError as e:
                    print(f"   Callback receiver WARN: {e}")
            if getattr(config, "callback", None) and config.callback.enabled and callback_url:
                print(f"   Callback: OK {callback_url}")
                if callback_receiver_url:
                    print(f"   Callback receiver: OK http://{config.callback.host}:{config.callback.port}")
            
            # 执行健康检查
            health = self.adapter.connect()
            
            # 打印详细的健康检查结果
            print(f"   {self.adapter.vendor_name}")
            print(f"   整体状态: {health['overall_status']}")
            print(f"   - nav_server: {'OK' if health['nav_server']['connected'] else 'ERR'} {nav_server_host}:{nav_server_port}")
            if health['nav_server']['error']:
                print(f"     错误: {health['nav_server']['error']}")
            print(f"   - nav_app: {'OK' if health['nav_app']['connected'] else 'ERR'} {nav_app_host}:{nav_app_port}")
            if health['nav_app']['error']:
                print(f"     错误: {health['nav_app']['error']}")
            print(f"   - rosbridge: {'OK' if health['rosbridge']['connected'] else 'ERR'} {rosbridge_host}:{rosbridge_port}")
            if health['rosbridge']['error']:
                print(f"     错误: {health['rosbridge']['error']}")

            if health['success']:
                # Set adapter for all skills
                self.registry.set_adapter_for_all(self.adapter)
                # Set adapter for skill loader (support hot reload)
                self.skill_manager.loader.set_adapter(self.adapter)
            else:
                print("   Warning: 所有连接都失败，将以离线模式运行")
            
            # 4. Initialize brain (只初始化一次LLM provider)
            world_resolver = self._initialize_world(config)
            if world_resolver:
                print(f"   World: OK {config.world.path} ({world_resolver.describe()})")
            soul = self._initialize_soul(config)
            if soul:
                print(f"   Soul: OK {config.soul.path} ({soul.describe()})")
            print("3. Initializing brain...")
            
            # Create LLM provider (唯一初始化点)
            from fishmindos.brain.llm_providers import create_llm_provider
            llm_provider = None
            llm_status = {"initialized": False, "provider": None, "model": None, "error": None}
            
            try:
                llm_provider = create_llm_provider(config.llm)
                llm_status["initialized"] = True
                llm_status["provider"] = config.llm.provider
                llm_status["model"] = config.llm.model
                print(f"   OK LLM: {config.llm.provider} ({config.llm.model})")
            except Exception as e:
                llm_status["error"] = str(e)
                print(f"   WARN LLM初始化失败: {e}")
                print(f"     将使用规则引擎(SmartBrain)")
            
            # Create LLM brain (传入已初始化的provider，避免重复初始化)
            self.brain = LLMBrain(self.registry, self.adapter, llm_provider)
            self._sync_world_to_brain()
            self._sync_soul_to_brain()
            self._apply_callback_config(config)
            self._sync_callback_state_to_brain()
            
            if llm_status["initialized"]:
                print("   OK LLM brain ready (AI推理)")
            else:
                print("   OK Rule engine ready (规则推理)")
            
            # 5. Initialize interaction layer
            print("4. Initializing interaction layer...")
            self.interaction = InteractionManager(self.brain)
            self.interaction_channel = TerminalChannel(self.interaction)
            print("   Terminal UI ready")
            
            print()
            print("=" * 60)
            print("  FishMindOS Initialized!")
            print("=" * 60)
            print()
            
            return True
            
        except Exception as e:
            print(f"\nInitialization failed: {e}")
            if self.callback_receiver:
                self.callback_receiver.stop()
                self.callback_receiver = None
            import traceback
            traceback.print_exc()
            return False
    
    def run(self):
        """Run main loop"""
        if not self.interaction_channel:
            print("Error: System not initialized")
            return
        
        self._running = True
        
        # Setup signal handling
        def signal_handler(signum, frame):
            print("\n\nInterrupt received, shutting down...")
            self.shutdown()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            self.interaction_channel.start()
        except Exception as e:
            print(f"\nRuntime error: {e}")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Shutdown system"""
        if not self._running:
            return
        
        print("\nShutting down FishMindOS...")
        
        if self.skill_manager:
            self.skill_manager.shutdown()

        if self.interaction_channel:
            self.interaction_channel.stop()

        if self.callback_receiver:
            self.callback_receiver.stop()
            self.callback_receiver = None
        
        if self.adapter:
            self.adapter.disconnect()
        
        self._running = False
        print("Goodbye!")
    
    def get_status(self):
        """Get system status"""
        if not self.skill_manager:
            return {"initialized": False}
        
        return {
            "initialized": True,
            "skills": self.skill_manager.get_status(),
            "adapter": self.adapter.vendor_name if self.adapter else None,
            "running": self._running
        }


def main():
    """Main function"""
    _configure_console_encoding()

    parser = argparse.ArgumentParser(
        description="FishMindOS - Smart Robot Dog Control System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with default config
  python -m fishmindos

  # Specify API addresses
  python -m fishmindos --nav-server 192.168.1.100 --nav-app 192.168.1.100

  # Enable skill hot reload (dev mode)
  python -m fishmindos --hot-reload

  # Specify custom skill paths
  python -m fishmindos --skill-path ./my_skills
        """
    )
    
    # Load defaults from config
    config = get_config()
    
    parser.add_argument(
        "--nav-server",
        default=config.nav_server.host,
        help=f"nav_server address (default: {config.nav_server.host})"
    )
    parser.add_argument(
        "--nav-server-port",
        type=int,
        default=config.nav_server.port,
        help=f"nav_server port (default: {config.nav_server.port})"
    )
    parser.add_argument(
        "--nav-app",
        default=config.nav_app.host,
        help=f"nav_app address (default: {config.nav_app.host})"
    )
    parser.add_argument(
        "--nav-app-port",
        type=int,
        default=config.nav_app.port,
        help=f"nav_app port (default: {config.nav_app.port})"
    )
    parser.add_argument(
        "--skill-path",
        action="append",
        help="Custom skill search path (can specify multiple)"
    )
    parser.add_argument(
        "--hot-reload",
        action="store_true",
        help="Enable skill hot reload (development mode)"
    )
    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 2.0.0"
    )
    
    args = parser.parse_args()
    
    # Create and initialize app
    app = FishMindOS()
    
    if app.initialize(
        nav_server_host=args.nav_server,
        nav_server_port=args.nav_server_port,
        nav_app_host=args.nav_app,
        nav_app_port=args.nav_app_port,
        skill_paths=args.skill_path,
        enable_hot_reload=args.hot_reload
    ):
        # Run main loop
        app.run()
    else:
        print("\nSystem initialization failed, exiting")
        sys.exit(1)


# Backwards compatibility
class FishMindOSApp(FishMindOS):
    """Backwards compatible class name"""
    pass


if __name__ == "__main__":
    main()
