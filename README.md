# FishMindOS

FishMindOS 是一套面向机器狗控制的文本智能体框架。

目标不是直接替代底层控制器，而是把自然语言指令稳定地转换成可执行的机器人动作。

当前主链路：

```text
interaction -> agent_core -> local MCP -> execution_runtime -> skill_runtime -> robot HTTP / rosbridge
```

## Current Design

### 1. Fast Path First

高频、明确、低歧义的指令先走本地快路径，例如：

- 你叫什么
- 你会什么
- 开灯 / 关灯   
- 站立 / 趴下
- 开始导航，地图为 26 层
- 现在是否在充电
- 列出任务
- 执行任务 xxx
- 创建任务链
- 创建导航任务

### 2. LLM Only Sees Macro Tools

大模型默认优先看到这些宏观工具：

- `robot_navigation_assistant`
- `robot_task_assistant`
- `robot_task_chain`
- `robot_audio`
- `robot_light`
- `robot_motion`
- `robot_status`

地图名、路点名、任务名的模糊匹配，以及导航任务模板和任务链的组装，都由 Python 运行时完成。

### 3. Prompt Files

给模型的规则拆成：

- `IDENTITY.md`
- `SOUL.md`
- `USER.md`
- `AGENT.md`
- `TOOLS.md`
- `TASK_SPEC.md`

## Run

```powershell
conda activate yolov3
python main.py
```

如果要走机器狗实时控制，还需要：

```powershell
pip install websocket-client
```

## Config

主要配置文件：

- `fishmindos.config.json`
- `fishmindos.config.example.json`

关键字段：

- `llm.provider / model / api_key / prompt_mode`
- `nav.scheme / host / port`
- `rosbridge.host / port / path`
- `planner.motion_aliases`
- `task_chains.storage_file`

## Docs

- 架构说明：`ARCHITECTURE.md`
- 模型规则：`AGENT.md`、`TOOLS.md`、`TASK_SPEC.md`
- 机器狗身份：`IDENTITY.md`、`SOUL.md`、`USER.md`
