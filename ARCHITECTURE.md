# FishMindOS Architecture

## Core Flow

```text
User Text
  -> InteractionLayer
  -> AgentCoreRuntime
     -> FastPathPlanner
     -> LLMTaskPlanner
  -> TaskExecutor
  -> LocalMCPClient
  -> LocalMCPServer
  -> Macro Skills / Runtime Skills
  -> Robot HTTP API / rosbridge
```

## Design Goal

这套结构参考 openclaw 的思路，但不依赖 openclaw 本身：

- 高频命令先走本地快路径
- 大模型只面对宏观工具
- 名字解析、任务模板、任务链都下沉到 Python 运行时
- prompt 身份、风格、工具语义分文件提供给模型

## Layers

### interaction

职责：

- 接收终端或其他入口传来的文本
- 统一转成 `InteractionEvent`

### agent_core

职责：

- 先做 `FastPathPlanner`
- 没命中时，再做 `LLMTaskPlanner`
- 输出 `TaskSequence`

当前关键模块：

- `fastpath.py`
- `planner.py`
- `llm.py`
- `runtime.py`

### mcp

职责：

- 暴露工具列表
- 执行工具调用
- 暴露 prompt resources

当前关键模块：

- `LocalMCPServer`
- `LocalMCPClient`
- `PromptResourceCatalog`

### skill_runtime

职责：

- 封装底层 HTTP API 和 rosbridge
- 提供宏观工具
- 负责名字模糊匹配、任务模板创建、任务链存取和执行

当前关键模块：

- `nav_skills.py`
- `assistant_skills.py`
- `task_chain_store.py`
- `dog_motion.py`
- `rosbridge_api.py`

### execution_runtime

职责：

- 把 `TaskSequence` 转成 `TaskPlan`
- 顺序执行步骤
- 支持 reply-only 的空计划成功返回

## Prompt Resources

给模型看的资源拆成：

- `IDENTITY.md`
- `SOUL.md`
- `USER.md`
- `AGENT.md`
- `TOOLS.md`
- `TASK_SPEC.md`

这样能把身份、说话方式、规划规则、工具语义分开维护。

## Macro Tools

大模型默认优先使用：

- `robot_navigation_assistant`
- `robot_task_assistant`
- `robot_task_chain`

底层 CRUD 工具保留在运行时，不直接让模型自己拼多段查询链。
