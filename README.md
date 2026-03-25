# FishMindOS

FishMindOS 是一个面向机器人/机器狗/无人机等的具身智能编排框架。  
它把用户输入的自然语言指令拆成结构化任务流，再通过适配器调用你的导航、动作、灯光、语音、回调等能力。

当前仓库默认接的是 `FishBot` 风格接口，但这个项目的核心目标不是绑定某一台机器人，而是把它收敛成一套可以迁移到别的机器人上的 OS 框架。

---

## 0. 环境要求

在开始之前，至少要满足下面这些条件：

- Python：建议 `Python 3.10+`。
- 环境管理：推荐使用 `conda`，也可以直接用系统 Python 虚拟环境。
- LLM 连通性：需要能访问你配置的大模型 API。
- 真机运行前提：需要你的机器人导航服务、应用服务、`rosbridge`、回调地址都可连通。
- 仿真运行前提：不需要真机，但仍需要可访问的 LLM API。

如果你要跑真机链路，建议先确认这几项：

- `nav_server.host:port` 可访问
- `nav_app.host:port` 可访问
- `rosbridge.host:port` 可访问
- `callback.enabled=true` 时，本机回调端口可被机器人侧访问

最小推荐环境示例：

```text
Python 3.10+
conda (recommended)
一个可用的 LLM API Key
一套可访问的机器人导航/状态接口
```

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

---

## 1. 这套系统现在是什么

当前主链路是：

```text
用户输入
  -> interaction/manager.py
  -> brain/llm_brain.py
  -> tools: submit_mission / system_status
  -> brain/mission_manager.py
  -> adapters/fishbot.py
  -> 你的导航 / rosbridge / 回调接口
```

几个关键点：

- LLM 不再直接微操底层技能。
- LLM 主要负责两类事：
  - `submit_mission`：生成任务流
  - `system_status`：回答状态查询
- 小脑 `MissionManager` 负责真正执行任务流，靠事件驱动推进，不靠阻塞等待。
- `world` 负责语义地图和地点理解。
- `soul` 负责长期偏好和可控学习。

---

## 2. 当前保留的运行方式

### 2.1 真机运行

```bash
python -m fishmindos
```

这条链路会走真实入口：

- [fishmindos/__main__.py](/d:/FishMindOS/fishmindos/__main__.py)
- [fishmindos/config.py](/d:/FishMindOS/fishmindos/config.py)
- [fishmindos/adapters/fishbot.py](/d:/FishMindOS/fishmindos/adapters/fishbot.py)
- [fishmindos/brain/llm_brain.py](/d:/FishMindOS/fishmindos/brain/llm_brain.py)
- [fishmindos/interaction/manager.py](/d:/FishMindOS/fishmindos/interaction/manager.py)

适合：

- 联调真实导航接口
- 联调 rosbridge / callback
- 测试真实任务执行

### 2.2 仿真运行

```bash
python mock_fishmindos.py
```

这条链路会：

- 复用真实的 FishMindOS 主入口
- 只把真实机器人适配器替换成 mock 适配器
- 保留当前的 world / soul / prompt / mission_manager 逻辑

适合：

- 测 LLM 规划是否合理
- 测任务流是否能按事件推进
- 不连接真机时做回归

---

## 3. 目录说明

你最需要关心的是这些文件和目录：

```text
FishMindOS/
├─ fishmindos.config.json
├─ fishmindos.config.example.json
├─ mock_fishmindos.py
├─ docs/
│  ├─ prompt.md
│  ├─ identity.md
│  ├─ agent.md
│  ├─ tools.md
│  ├─ Soul.md
│  └─ profiles/
├─ fishmindos/
│  ├─ __main__.py
│  ├─ config.py
│  ├─ adapters/
│  ├─ brain/
│  ├─ interaction/
│  ├─ skills/
│  ├─ world/
│  └─ soul/
└─ skill_store/
```

### 核心职责

- [fishmindos/__main__.py](/d:/FishMindOS/fishmindos/__main__.py)  
  系统装配入口。读取配置、连接适配器、初始化 world/soul/brain/UI。

- [fishmindos/config.py](/d:/FishMindOS/fishmindos/config.py)  
  配置模型定义和配置加载。

- [fishmindos/adapters/base.py](/d:/FishMindOS/fishmindos/adapters/base.py)  
  机器人适配器接口定义。你要适配别的机器人，主要看这个文件。

- [fishmindos/adapters/fishbot.py](/d:/FishMindOS/fishmindos/adapters/fishbot.py)  
  当前默认的真实机器人适配器实现。

- [fishmindos/brain/llm_brain.py](/d:/FishMindOS/fishmindos/brain/llm_brain.py)  
  大脑。负责意图理解、工具选择、提示词拼接。

- [fishmindos/brain/mission_manager.py](/d:/FishMindOS/fishmindos/brain/mission_manager.py)  
  小脑。负责事件驱动执行任务流。

- [fishmindos/skills/builtin/mission.py](/d:/FishMindOS/fishmindos/skills/builtin/mission.py)  
  `submit_mission` 工具入口。

- [fishmindos/skills/builtin/system.py](/d:/FishMindOS/fishmindos/skills/builtin/system.py)  
  `system_status` 工具入口。

- [fishmindos/interaction/manager.py](/d:/FishMindOS/fishmindos/interaction/manager.py)  
  终端 UI。

- [fishmindos/interaction/callback_receiver.py](/d:/FishMindOS/fishmindos/interaction/callback_receiver.py)  
  内置 HTTP 回调接收器，把底层回调转成系统事件。

- [fishmindos/world/](/d:/FishMindOS/fishmindos/world)  
  语义地图层。

- [fishmindos/soul/](/d:/FishMindOS/fishmindos/soul)  
  长期偏好和学习层。

---

## 4. 快速开始

### 4.1 准备配置

建议先复制一份配置文件：

```bash
copy fishmindos.config.example.json fishmindos.config.json
```

然后至少填这几类配置：

#### 1. LLM

```json
{
  "llm": {
    "provider": "your-provider",
    "api_key": "your-api-key",
    "base_url": null,
    "model": "your-model",
    "temperature": 0.2,
    "timeout": 30
  }
}
```

#### 2. 机器人导航接口

```json
{
  "nav_server": {
    "host": "<NAV_SERVER_HOST>",
    "port": "<NAV_SERVER_HOST>"
  },
  "nav_app": {
    "host": "<NAV_APP_HOST>",
    "port": "<NAV_SERVER_HOST>"
  },
  "rosbridge": {
    "host": "<ROSBRIDGE_HOST>",
    "port": "<NAV_SERVER_HOST>",
    "path": "/api/rt",
    "use_ssl": false
  }
}
```

#### 3. 应用身份

```json
{
  "app": {
    "identity": "你的机器人名字",
    "prompt_profile": "your_profile",
    "language": "zh",
    "debug": false
  }
}
```

#### 4. world / soul / callback

```json
{
  "world": {
    "enabled": true,
    "path": "fishmindos/world/semantic_map.json",
    "auto_switch_map": true,
    "prefer_current_map": true,
    "adapter_fallback": false
  },
  "soul": {
    "enabled": true,
    "path": "fishmindos/soul/soul.json",
    "max_memories": 200
  },
  "callback": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 8081,
    "path": "/callback/nav_event",
    "url": null
  }
}
```

### 4.2 启动

```bash
python -m fishmindos
```

启动后你会看到：

- 技能系统初始化
- 适配器连接检查
- LLM 初始化
- 交互层启动

### 4.3 常用交互命令

进入终端后可以直接输入：

- `去大厅`
- `去卫生间拿纸然后回充`
- `你还有多少电`
- `world`
- `确认`
- `停止`
- `退出`

---

## 5. world 怎么用

`world` 是语义地图层，不是底层地图文件本身。

它的作用是：

- 让 LLM 知道“大厅 / 卫生间 / 前台 / 回充点”这些地点是什么意思
- 让 LLM 理解别名、用途、关系
- 在任务规划时把自然语言地点映射成实际地图里的位置

### 5.1 在 UI 里设置默认 world

启动后输入：

```text
world
```

系统会：

1. 列出当前适配器能读到的地图
2. 让你选一张作为默认地图
3. 生成或刷新对应的 world 文件

### 5.2 补充语义信息

建议为常用点补这些内容：

- description：这个点通常用来干什么
- aliases：常见别名
- category：地点类别
- task_hints：该点常见任务
- relations：和其他点的关系

这样 LLM 对世界的理解会稳定很多。

---

## 6. soul 是什么

`soul` 是长期偏好和经验层。

它不是世界事实库，而是“使用习惯 / 偏好 / 可控记忆”：

- 用户喜欢怎样称呼某个地点
- 默认任务结束是否回充
- 某些任务的长期偏好

当前 `soul` 会从任务流里做受控学习，并写回：

- [fishmindos/soul/soul.json](/d:/FishMindOS/fishmindos/soul/soul.json)

如果你不想用长期学习，可以在配置里关掉：

```json
{
  "soul": {
    "enabled": false
  }
}
```

---

## 7. prompt / profile 怎么用

系统提示词来自：

- [docs/prompt.md](/d:/FishMindOS/docs/prompt.md)
- [docs/identity.md](/d:/FishMindOS/docs/identity.md)
- [docs/agent.md](/d:/FishMindOS/docs/agent.md)
- [docs/tools.md](/d:/FishMindOS/docs/tools.md)
- [docs/Soul.md](/d:/FishMindOS/docs/Soul.md)

同时支持 profile 覆盖：

```text
docs/profiles/<profile_name>/
  ├─ identity.md
  └─ agent.md
```

### 使用方式

1. 新建一个 profile 目录：

```text
docs/profiles/my_robot/
```

2. 至少放两份文件：

- `identity.md`
- `agent.md`

3. 在配置里指定：

```json
{
  "app": {
    "identity": "小虎机器人",
    "prompt_profile": "my_robot"
  }
}
```

这样你就能把同一套框架换成另一套机器人身份和交互风格，而不需要改核心代码。

---

## 8. 怎么换 LLM API

如果你说的“换 API”是换大模型提供商，主要改配置，不需要改主链代码。

改 [fishmindos.config.json](/d:/FishMindOS/fishmindos.config.json) 里的：

- `llm.provider`
- `llm.api_key`
- `llm.base_url`
- `llm.model`
- `llm.timeout`

也可以用环境变量覆盖：

- `FISHMIND_LLM_PROVIDER`
- `FISHMIND_LLM_API_KEY`
- `FISHMIND_LLM_BASE_URL`
- `FISHMIND_LLM_MODEL`
- `FISHMIND_LLM_TIMEOUT`
- `FISHMIND_APP_PROMPT_PROFILE`
- `FISHMIND_APP_IDENTITY`

---

## 9. 怎么换机器人 API

如果你说的“换 API”是把这套系统接到另一台机器人上，核心不是改 README，不是改 prompt，而是改适配器。

### 9.1 你要实现什么

你需要基于 [RobotAdapter](/d:/FishMindOS/fishmindos/adapters/base.py) 实现自己的适配器。

最关键的方法包括：

- `connect()`
- `disconnect()`
- `list_maps()`
- `get_map()`
- `list_waypoints()`
- `get_waypoint()`
- `start_navigation()`
- `stop_navigation()`
- `goto_waypoint()`
- `goto_point()`
- `get_navigation_status()`
- `navigate_to()`
- `execute_docking_async()`
- `get_status()`
- `get_basic_status()`
- `set_light()`
- `play_audio()`
- `set_callback_url()`
- `handle_callback_event()`
- `get_callback_state()`

### 9.2 推荐做法

1. 复制一份模板，例如新建：

- [your_robot.py](/d:/FishMindOS/fishmindos/adapters/your_robot.py)

2. 让它继承 `RobotAdapter`

3. 先接通最小闭环：

- 地图读取
- 路点读取
- 导航到路点
- 回充
- 状态查询
- 语音
- 灯光

4. 再接回调事件

### 9.3 当前代码下怎么切换到你自己的适配器

当前主入口 [__main__.py](/d:/FishMindOS/fishmindos/__main__.py) 是直接调用：

- [create_fishbot_adapter](/d:/FishMindOS/fishmindos/adapters/__init__.py)

所以如果你要正式替换成自己的机器人，最直接的方式有两种：

#### 方式 A：直接把默认工厂切到你的适配器

改：

- [fishmindos/adapters/__init__.py](/d:/FishMindOS/fishmindos/adapters/__init__.py)
- [fishmindos/__main__.py](/d:/FishMindOS/fishmindos/__main__.py)

把 `create_fishbot_adapter` 换成你的工厂。

#### 方式 B：做成多适配器工厂

更推荐后续这样演进：

1. 在配置里增加 `adapter.type`
2. 在 `adapters/__init__.py` 里做统一工厂
3. 在 `__main__.py` 里按配置选择适配器

如果你准备把这套框架交给别人复用，建议走方式 B。

---

## 10. 怎么让它变成“自己的机器人 OS”

如果你希望别人拿到这套工程后，换掉接口和人设，就能变成“他们自己的机器人 OS”，建议按下面步骤做。

### 第一步：换身份

改配置：

```json
{
  "app": {
    "identity": "你们机器人的名字",
    "prompt_profile": "你们自己的 profile"
  }
}
```

再新增：

```text
docs/profiles/<你们的profile>/
  ├─ identity.md
  └─ agent.md
```

### 第二步：换 world

把默认地图导入成你们自己的 world，补地点描述、别名、任务提示。

### 第三步：换适配器

把 `FishBotAdapter` 换成你们自己的机器人适配器。

### 第四步：接事件

无论你们底层是 HTTP 回调、WebSocket、ROS topic 还是 SDK 回调，最终都要映射成这些系统事件：

- `nav_arrived`
- `dock_completed`
- `action_failed`
- `human_confirmed`

这样小脑 `MissionManager` 才能继续工作。

### 第五步：保留统一入口

对外只保留这两个入口：

```bash
python -m fishmindos
python -m mock_fishmindos
```

这样别人拿到后，既能连真机，也能先仿真验证。

---

## 11. callback 需要满足什么

真实执行链是事件驱动的，所以 callback 很重要。

底层导航系统至少应该能让上层识别出：

- 导航开始
- 到达路点
- 回充完成
- 失败事件
- 当前姿态 / 目标点信息（可选但强烈建议）

内置接收器在：

- [fishmindos/interaction/callback_receiver.py](/d:/FishMindOS/fishmindos/interaction/callback_receiver.py)

如果你的机器人回调字段不同，重点改这里和适配器里的事件映射逻辑。

---

## 12. 仿真建议

建议开发顺序是：

1. 先跑：

```bash
python -m mock_fishmindos
```

2. 验证：

- 规划是否合理
- 任务流顺序是否合理
- `wait_confirm` 是否合理
- `dock` 是否收敛

3. 再跑：

```bash
python -m fishmindos
```

4. 联调真实接口和回调

---

## 13. 给二次开发者的建议

如果你打算把这套系统交给别人继续接机器人，优先保持下面这些边界清晰：

- `brain/` 只做理解、规划、调度
- `mission_manager.py` 只做事件驱动执行
- `adapters/` 只负责和真实机器人 API 对接
- `world/` 只负责地点语义
- `soul/` 只负责长期偏好
- `docs/profiles/` 只负责机器人身份和交互风格

这几层不要混。

尤其不要把：

- 机器人接口细节
- 地点硬编码
- 用户偏好
- LLM 提示词

混在同一层代码里。

---

## 14. 当前最常见的改造路径

### 完全变成你们自己的机器人 OS

你需要同时改：

- 适配器
- profile
- world
- 回调映射
- 配置模板

但可以继续保留：

- `LLMBrain`
- `MissionManager`
- `InteractionManager`
- `submit_mission / system_status`

---

## 15. 最后一句

如果你把这套系统理解成三层，会最清楚：

- **大脑**：理解用户要什么
- **小脑**：按事件把任务稳定执行完
- **机体接口**：把动作真正发给你的机器人

换 LLM、换人设、换 world、换机器人，本质上都是在替换其中一层，而不是把整个系统推倒重来。
