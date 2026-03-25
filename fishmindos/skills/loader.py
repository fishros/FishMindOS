"""
FishMindOS 技能发现与加载模块
支持动态发现、加载和热重载技能
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass
from datetime import datetime
import threading
import time

from fishmindos.skills.base import Skill, SkillRegistry


@dataclass
class SkillMetadata:
    """技能元数据"""
    name: str
    description: str
    version: str
    author: str
    category: str
    file_path: Path
    module_name: str
    class_name: str
    loaded_at: Optional[str] = None
    dependencies: List[str] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


@dataclass
class LoadedSkill:
    """已加载的技能"""
    metadata: SkillMetadata
    instance: Skill
    module: Any
    mtime: float  # 文件修改时间，用于热重载


class SkillDiscoverer:
    """
    技能发现器
    扫描指定目录发现可用技能
    """
    
    # 默认技能搜索路径
    DEFAULT_PATHS = [
        "skill_store",  # 项目根目录下的skill_store
        "skills",       # 项目根目录下的skills
        "~/.fishmindos/skills",  # 用户目录
    ]
    
    def __init__(self, search_paths: List[str] = None):
        self.search_paths = search_paths or self.DEFAULT_PATHS
        self._skill_manifests: Dict[str, Path] = {}
    
    def discover(self) -> List[SkillMetadata]:
        """
        发现所有可用技能
        
        Returns:
            技能元数据列表
        """
        skills = []
        seen_names = set()  # 用于去重
        
        for path_str in self.search_paths:
            path = Path(path_str).expanduser().resolve()
            if not path.exists():
                continue
            
            # 查找技能清单文件
            manifest_path = path / "skills_manifest.json"
            if manifest_path.exists():
                for skill in self._load_from_manifest(manifest_path):
                    if skill.name not in seen_names:
                        skills.append(skill)
                        seen_names.add(skill.name)
            
            # 查找独立的.py技能文件
            for skill in self._scan_directory(path):
                if skill.name not in seen_names:
                    skills.append(skill)
                    seen_names.add(skill.name)
                else:
                    print(f"[WARN] 跳过重复技能: {skill.name} (位于 {skill.file_path})")
        
        return skills
    
    def _load_from_manifest(self, manifest_path: Path) -> List[SkillMetadata]:
        """从清单文件加载技能"""
        skills = []
        
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            
            for skill_def in manifest.get("skills", []):
                file_path = manifest_path.parent / skill_def.get("file", "")
                if not file_path.exists():
                    continue
                metadata = SkillMetadata(
                    name=skill_def.get("name", "unknown"),
                    description=skill_def.get("description", ""),
                    version=skill_def.get("version", "1.0.0"),
                    author=skill_def.get("author", "unknown"),
                    category=skill_def.get("category", "custom"),
                    file_path=file_path,
                    module_name=skill_def.get("module", ""),
                    class_name=skill_def.get("class", "Skill"),
                    dependencies=skill_def.get("dependencies", [])
                )
                skills.append(metadata)
        
        except Exception as e:
            print(f"加载技能清单失败 {manifest_path}: {e}")
        
        return skills
    
    def _scan_directory(self, directory: Path) -> List[SkillMetadata]:
        """扫描目录查找技能文件"""
        skills = []
        
        for file_path in directory.glob("*.py"):
            # 跳过以_开头的文件
            if file_path.name.startswith("_"):
                continue
            
            # 尝试解析技能元数据
            metadata = self._parse_skill_file(file_path)
            if metadata:
                skills.append(metadata)
        
        return skills
    
    def _parse_skill_file(self, file_path: Path) -> Optional[SkillMetadata]:
        """解析技能文件提取元数据"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 简单的元数据解析（从注释或类定义中提取）
            # 查找 SKILL_METADATA 字典
            if "SKILL_METADATA" in content:
                # 尝试提取元数据
                import re
                match = re.search(r'SKILL_METADATA\s*=\s*\{([^}]+)\}', content, re.DOTALL)
                if match:
                    # 这里简化处理，实际应该用更安全的方式解析
                    pass
            
            # 查找继承自Skill的类
            class_match = None
            for line in content.split('\n'):
                if 'class' in line and 'Skill' in line and '(' in line:
                    match = re.search(r'class\s+(\w+)\s*\(', line)
                    if match:
                        class_match = match.group(1)
                        break
            
            if class_match:
                return SkillMetadata(
                    name=file_path.stem,
                    description=f"Auto-discovered skill from {file_path.name}",
                    version="1.0.0",
                    author="auto",
                    category="custom",
                    file_path=file_path,
                    module_name=file_path.stem,
                    class_name=class_match
                )
        
        except Exception as e:
            print(f"解析技能文件失败 {file_path}: {e}")
        
        return None


class SkillLoader:
    """
    技能加载器
    支持动态加载、热重载
    """
    
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._loaded_skills: Dict[str, LoadedSkill] = {}
        self._discoverer = SkillDiscoverer()
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_watching = threading.Event()
        self._hot_reload_enabled = False
        self._adapter = None  # 存储适配器用于热重载
    
    def load_all(self, search_paths: List[str] = None) -> int:
        """
        加载所有发现的技能
        
        Returns:
            加载的技能数量
        """
        if search_paths:
            self._discoverer.search_paths = search_paths
        
        skills = self._discoverer.discover()
        loaded_count = 0
        
        for metadata in skills:
            if self.load_skill(metadata):
                loaded_count += 1
        
        return loaded_count
    
    def load_skill(self, metadata: SkillMetadata) -> bool:
        """
        加载单个技能
        
        Args:
            metadata: 技能元数据
            
        Returns:
            是否成功
        """
        try:
            # 检查文件是否存在
            if not metadata.file_path.exists():
                print(f"技能文件不存在: {metadata.file_path}")
                return False
            
            # 检查依赖
            for dep in metadata.dependencies:
                if not self.registry.has(dep):
                    print(f"技能 {metadata.name} 依赖 {dep} 未加载")
                    return False
            
            # 动态导入模块
            spec = importlib.util.spec_from_file_location(
                metadata.module_name,
                metadata.file_path
            )
            if not spec or not spec.loader:
                print(f"无法创建模块规范: {metadata.file_path}")
                return False
            
            module = importlib.util.module_from_spec(spec)
            
            # 将模块添加到sys.modules以便技能内部可以相互导入
            sys.modules[metadata.module_name] = module
            
            # 执行模块
            spec.loader.exec_module(module)
            
            # 获取技能类
            skill_class = getattr(module, metadata.class_name, None)
            if not skill_class:
                print(f"在 {metadata.file_path} 中找不到类 {metadata.class_name}")
                return False
            
            # 检查是否是Skill的子类
            if not issubclass(skill_class, Skill):
                print(f"{metadata.class_name} 不是 Skill 的子类")
                return False
            
            # 创建实例
            instance = skill_class()
            
            # 如果有适配器，立即设置（支持热重载）
            if self._adapter:
                instance.set_adapter(self._adapter)
            
            # 记录加载信息
            metadata.loaded_at = datetime.now().isoformat()
            loaded = LoadedSkill(
                metadata=metadata,
                instance=instance,
                module=module,
                mtime=metadata.file_path.stat().st_mtime
            )
            
            # 注册到注册表
            self.registry.register(instance)
            self._loaded_skills[metadata.name] = loaded
            
            print(f"[OK] Loaded skill: {metadata.name} ({metadata.file_path.name})")
            return True
        
        except Exception as e:
            print(f"[FAIL] Failed to load skill {metadata.name}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def unload_skill(self, name: str) -> bool:
        """
        卸载技能
        
        Args:
            name: 技能名称
            
        Returns:
            是否成功
        """
        if name not in self._loaded_skills:
            return False
        
        try:
            # 从注册表移除
            self.registry.unregister(name)
            
            # 从已加载列表移除
            loaded = self._loaded_skills.pop(name)
            
            # 从sys.modules移除（可选，取决于是否允许重新加载）
            if loaded.metadata.module_name in sys.modules:
                del sys.modules[loaded.metadata.module_name]
            
            print(f"[OK] Unloaded skill: {name}")
            return True
        
        except Exception as e:
            print(f"[FAIL] Failed to unload skill {name}: {e}")
            return False
    
    def set_adapter(self, adapter):
        """
        设置适配器，用于新加载的技能和热重载
        
        Args:
            adapter: 机器人适配器
        """
        self._adapter = adapter
        
        # 为已加载的所有技能设置适配器
        for loaded in self._loaded_skills.values():
            loaded.instance.set_adapter(adapter)
    
    def reload_skill(self, name: str) -> bool:
        """
        重新加载技能（热重载）
        
        Args:
            name: 技能名称
            
        Returns:
            是否成功
        """
        if name not in self._loaded_skills:
            print(f"技能 {name} 未加载，无法重载")
            return False
        
        loaded = self._loaded_skills[name]
        metadata = loaded.metadata
        
        # 先卸载
        if not self.unload_skill(name):
            return False
        
        # 重新加载（会自动应用适配器）
        return self.load_skill(metadata)
    
    def enable_hot_reload(self, interval: float = 2.0):
        """
        启用热重载
        
        Args:
            interval: 检查间隔（秒）
        """
        if self._hot_reload_enabled:
            return
        
        self._hot_reload_enabled = True
        self._stop_watching.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_files,
            args=(interval,),
            daemon=True
        )
        self._watch_thread.start()
        print(f"[OK] Hot reload enabled (check interval: {interval}s)")
    
    def disable_hot_reload(self):
        """禁用热重载"""
        if not self._hot_reload_enabled:
            return
        
        self._stop_watching.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=1.0)
        self._hot_reload_enabled = False
        print("[OK] Hot reload disabled")
    
    def _watch_files(self, interval: float):
        """监控文件变化"""
        while not self._stop_watching.is_set():
            time.sleep(interval)
            
            for name, loaded in list(self._loaded_skills.items()):
                try:
                    current_mtime = loaded.metadata.file_path.stat().st_mtime
                    if current_mtime > loaded.mtime:
                        print(f"检测到技能文件变化: {name}，正在重载...")
                        if self.reload_skill(name):
                            self._loaded_skills[name].mtime = current_mtime
                except Exception:
                    pass  # 文件可能被删除
    
    def get_loaded_skills(self) -> List[SkillMetadata]:
        """获取所有已加载的技能"""
        return [loaded.metadata for loaded in self._loaded_skills.values()]
    
    def is_loaded(self, name: str) -> bool:
        """检查技能是否已加载"""
        return name in self._loaded_skills


class SkillManager:
    """
    技能管理器
    统一管理技能的发现、加载、热重载
    """
    
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self.loader = SkillLoader(registry)
        self.discoverer = SkillDiscoverer()
    
    def initialize(self, search_paths: List[str] = None, enable_hot_reload: bool = False) -> int:
        """
        初始化技能系统
        
        Args:
            search_paths: 搜索路径列表
            enable_hot_reload: 是否启用热重载
            
        Returns:
            加载的技能数量
        """
        print("[INFO] Discovering skills...")
        
        if search_paths:
            self.discoverer.search_paths = search_paths
        
        skills = self.discoverer.discover()
        print(f"  发现 {len(skills)} 个技能")
        
        print("[INFO] Loading skills...")
        loaded = self.loader.load_all(search_paths)
        print(f"  成功加载 {loaded} 个技能")
        
        if enable_hot_reload:
            self.loader.enable_hot_reload()
        
        return loaded
    
    def shutdown(self):
        """关闭技能系统"""
        self.loader.disable_hot_reload()
        
        # 卸载所有自定义技能
        for name in list(self.loader._loaded_skills.keys()):
            self.loader.unload_skill(name)
    
    def reload_all(self) -> int:
        """重新加载所有技能"""
        print("[INFO] Reloading all skills...")
        
        # 先卸载所有
        for name in list(self.loader._loaded_skills.keys()):
            self.loader.unload_skill(name)
        
        # 重新加载
        return self.loader.load_all()
    
    def get_status(self) -> Dict[str, Any]:
        """获取技能系统状态"""
        return {
            "total_skills": len(self.registry.list_all()),
            "custom_skills": len(self.loader._loaded_skills),
            "builtin_skills": len(self.registry.list_all()) - len(self.loader._loaded_skills),
            "hot_reload_enabled": self.loader._hot_reload_enabled,
            "search_paths": self.discoverer.search_paths
        }


def create_skill_manager(registry: SkillRegistry) -> SkillManager:
    """工厂函数：创建技能管理器"""
    return SkillManager(registry)
