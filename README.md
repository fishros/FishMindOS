# FishMindOS

FishMindOS 是一套面向机器狗的中文任务控制框架。  
它把自然语言指令转换成一串可执行的技能步骤，再通过适配器去调用导航、动作、灯光、播报、回调等能力。

当前仓库主要保留了两条运行链：

- 真实链路：`python -m fishmindos`
- 仿真链路：`python mock_fishmindos.py`

本文档会说明：

- 当前框架是怎么组织的
- 每个保留文件的作用
- 如何启动真实系统和仿真系统
- 配置文件各段的用途
- 回调、技能、LLM、导航之间的关系
- 常见调试入口和维护建议

本文档刻意不写任何真实敏感信息，例如内部地址、令牌、密钥、端口组合等。  
示例中的地址、路径、参数名都只作为结构说明使用。

## 1. 当前整体结构

### 1.1 真实运行链

`python -m fishmindos` 的主流程：

1. 入口在 `fishmindos/__main__.py`
2. 读取根目录配置文件 `fishmindos.config.json`
3. 创建默认技能注册表
4. 连接机器人适配器
5. 初始化大脑
   - 优先使用 `LLMBrain`
   - 如果 LLM 不可用，则回退到规则引擎
6. 初始化终端交互层
7. 进入命令行对话循环
8. 如果启用了回调，则同时启动内置回调接收器

### 1.2 仿真运行链

仓库中保留一个 mock 入口：

- `mock_fishmindos.py`
  - 使用真实 LLM
  - 使用假的机器人适配器
  - 适合测试“LLM 会不会排对任务”

### 1.3 核心分层

当前保留的核心分层如下：

```text
用户输入
  -> interaction/manager.py
  -> brain/llm_brain.py
  -> skills/__init__.py + skills/base.py + skills/builtin/*
  -> adapters/fishbot.py / adapters/base.py
  -> nav_server / nav_app / rosbridge / callback
```

如果开启导航回调，则链路中还会多一条：

```text
导航服务回调
  -> interaction/callback_receiver.py
  -> adapters/fishbot.py
  -> brain.session_context
  -> system_wait / system_status / 导航相关技能
```

## 2. 目录说明

当前仓库的核心目录大致如下：

```text
FishMindOS/
├─ README.md
├─ fishmindos.config.json
├─ fishmindos.config.example.json
├─ mock_fishmindos.py
├─ docs/
└─ fishmindos/
   ├─ __init__.py
   ├─ __main__.py
   ├─ config.py
   ├─ core/
   ├─ adapters/
   ├─ brain/
   ├─ skills/
   └─ interaction/
```

## 3. 文件级说明

下面是当前保留文件的职责说明。

### 3.1 根目录文件

`README.md`

- 项目总览文档
- 说明结构、配置、启动方式和维护方式

`fishmindos.config.json`

- 实际运行时读取的本地配置文件
- 这里通常放你的真实运行参数
- 不建议把敏感值提交到公共仓库

`fishmindos.config.example.json`

- 脱敏示例配置
- 用来说明配置结构
- 新机器或新环境建议先参考这个文件

`mock_fishmindos.py`

- 真 LLM + 假机器人
- 主要测试规划能力、任务拆解能力、工具调用顺序

### 3.2 `fishmindos/` 包入口与配置

`fishmindos/__init__.py`

- 包级导出
- 对外暴露技能系统和 FishBot 适配器的常用工厂/类型

`fishmindos/__main__.py`

- 主入口
- `python -m fishmindos` 会从这里启动
- 负责：
  - 读取配置
  - 初始化技能系统
  - 初始化适配器
  - 初始化 LLMBrain
  - 初始化交互层
  - 启动内置回调接收器
  - 优雅关闭

`fishmindos/config.py`

- 定义所有配置数据结构
- 负责从：
  - JSON 文件
  - 环境变量
  - 默认值
  组合出最终运行配置
- 包含当前主要配置段：
  - `llm`
  - `nav_server`
  - `nav_app`
  - `rosbridge`
  - `websocket`
  - `callback`
  - `skills`
  - `app`

### 3.3 `fishmindos/core/`

`fishmindos/core/__init__.py`

- 导出核心数据模型

`fishmindos/core/models.py`

- 定义系统核心数据结构
- 主要包括：
  - `SkillContext`
  - `SkillResult`
  - `Robot` 相关执行事件
  - 通用事件/状态枚举
- 技能执行层大量依赖这个文件

### 3.4 `fishmindos/adapters/`

`fishmindos/adapters/__init__.py`

- 适配器层对外导出

`fishmindos/adapters/base.py`

- 机器人适配器抽象基类
- 规定统一接口，例如：
  - 地图查询
  - 路点查询
  - 导航启动/停止
  - 站立/趴下
  - 灯光控制
  - 音频播报
  - 回调配置与事件接收

`fishmindos/adapters/fishbot.py`

- 当前真实机器人适配器
- 是真实链路中最关键的设备连接层
- 主要负责：
  - HTTP 请求导航接口
  - 通过 WebSocket 连接实时控制接口
  - 管理导航状态
  - 管理回调状态
  - 在导航开始、到达、回充、位姿更新等事件到来时更新内部状态

`fishmindos/adapters/ws_client.py`

- WebSocket 客户端实现
- 负责 rosbridge 或兼容 WebSocket 的连接、收发、重连、订阅管理

`fishmindos/adapters/your_robot.py`

- 预留模板文件
- 用于以后适配别的机器人或别的控制接口
- 当前默认主链不依赖它

### 3.5 `fishmindos/brain/`

`fishmindos/brain/llm_brain.py`

- 当前主大脑
- 把自然语言转成技能调用
- 负责：
  - 生成 system prompt
  - 维护 session context
  - 处理多轮 tool calling
  - 调用技能
  - 更新上下文
  - 在失败时控制是否继续执行
- 如果你要调“LLM 为什么笨”或“为什么规划不完整”，通常先看这个文件

`fishmindos/brain/llm_providers.py`

- LLM 提供商适配层
- 封装不同模型服务的调用方式
- 当前大脑通过这个文件与外部模型通信

`fishmindos/brain/planner.py`

- 规则规划器
- 用于把复杂任务拆成多个子任务
- 在规则引擎或部分回退流程中仍然会用到

`fishmindos/brain/smart_brain.py`

- 规则引擎版本的大脑
- 当 LLM 初始化失败或不可用时作为后备方案

`fishmindos/brain/prompt_manager.py`

- 负责读取 `docs/` 里的提示词文档
- 可以加载：
  - `identity.md`
  - `agent.md`
  - `tools.md`
  - `prompt.md`
- 当前主链里它仍然存在，但真正的主 prompt 逻辑仍以 `llm_brain.py` 为中心
- 也就是说：
  - 它是“提示文档管理器”
  - 不是当前唯一的 prompt 来源

### 3.6 `fishmindos/skills/`

`fishmindos/skills/__init__.py`

- 默认技能注册入口
- 把内置技能注册进统一注册表

`fishmindos/skills/base.py`

- 技能基类
- 定义技能的统一接口、元数据、参数模式、执行包装

`fishmindos/skills/loader.py`

- 自定义技能发现与加载器
- 支持从 `skills.search_paths` 指定目录扫描额外技能
- 如果启用热重载，也主要由这里管理

#### 3.6.1 内置技能目录 `fishmindos/skills/builtin/`

`__init__.py`

- 内置技能子包入口

`navigation.py`

- 导航技能
- 包括：
  - `nav_start`
  - `nav_stop`
  - `nav_goto_waypoint`
  - `nav_goto_location`
  - `nav_get_status`
  - `nav_list_maps`
  - `nav_list_waypoints`
- 是地图、路点、回充等逻辑的核心

`motion.py`

- 站立、趴下、动作预设等技能

`audio.py`

- 音频播报和 TTS 技能
- 典型技能：
  - `audio_play`
  - `tts_speak`

`lights.py`

- 灯光控制技能
- 支持按颜色、模式或 code 控制

`items.py`

- 物品模拟/任务技能
- 用于“取物、送物、放物、检查携带物”

`system.py`

- 系统状态技能
- 典型能力：
  - 电量
  - 导航状态
  - 充电状态
  - 位姿
  - 等待事件 `system_wait`

`callback.py`

- 回调相关技能
- 典型能力：
  - `callback_set`
  - `callback_status`
  - `callback_server_start`

### 3.7 `fishmindos/interaction/`

`fishmindos/interaction/__init__.py`

- 交互层导出入口

`fishmindos/interaction/manager.py`

- 当前终端交互主文件
- 负责：
  - 打印欢迎头
  - 读取用户输入
  - 展示 `[PLAN]`
  - 展示技能执行流
  - 清洗脏输出
  - 处理中止和退出

`fishmindos/interaction/callback_receiver.py`

- 内置回调接收器
- 当前 `python -m fishmindos` 启用 callback 时，可以直接在进程内起一个小型 HTTP 服务接收导航事件
- 不需要再依赖独立 `test.py`

### 3.8 `docs/`

`docs/README.md`

- 文档目录说明

`docs/identity.md`

- 角色/身份提示文档

`docs/agent.md`

- Agent 行为说明文档

`docs/tools.md`

- 工具和技能说明文档

`docs/Soul.md`

- `Soul / 灵魂学习` 架构文档
- 描述长期偏好沉淀、规则学习和个性化演化层

`docs/prompt.md`

- 系统提示规则文档

`docs/ADAPTER_GUIDE.md`

- 适配器扩展说明文档

## 4. 配置文件说明

推荐以 `fishmindos.config.example.json` 为模板，整理出自己的 `fishmindos.config.json`。

### 4.1 `llm`

负责大模型配置。

典型字段：

- `provider`
- `api_key`
- `base_url`
- `model`
- `temperature`
- `max_tokens`
- `timeout`

建议：

- 不要把真实密钥写进 README、脚本示例或公共仓库
- 生产环境优先使用环境变量覆盖敏感项

### 4.2 `nav_server`

- 导航后端服务地址
- 主要用于地图、路点、任务等导航接口

### 4.3 `nav_app`

- 导航应用侧接口地址
- 常用于任务执行、播报等控制接口

### 4.4 `rosbridge`

- WebSocket 连接配置
- 用于实时控制相关能力

常见字段：

- `host`
- `port`
- `path`
- `use_ssl`

`use_ssl` 的含义：

- `false` 表示使用 `ws://`
- `true` 表示使用 `wss://`

### 4.5 `websocket`

- WebSocket 通用行为
- 例如是否启用、重连间隔、最大重连次数、ping 间隔

### 4.6 `callback`

- 导航回调配置
- 控制 FishMindOS 是否接收导航事件

关键字段：

- `enabled`
- `host`
- `port`
- `path`
- `url`
- `max_events`

行为说明：

- 当 `enabled=false` 时，不启用回调
- 当 `enabled=true` 且 `url` 为空时，会根据 `host + port + path` 自动拼出 URL
- 当回调地址指向本机时，`python -m fishmindos` 可以自动启动内置回调接收器

### 4.7 `skills`

- 自定义技能发现与热重载设置

常见字段：

- `search_paths`
- `hot_reload`
- `auto_discover`

含义：

- `search_paths`
  - 启动时会去这些目录找自定义技能
- `hot_reload`
  - 是否启用热重载
- `auto_discover`
  - 是否自动扫描并发现技能

### 4.8 `app`

- 应用级配置
- 例如身份名、日志等级、语言等

## 5. 启动方式

### 5.1 真实链路启动

在项目根目录执行：

```bash
python -m fishmindos
```

如果只想看版本：

```bash
python -m fishmindos --version
```

常用可选参数：

```bash
python -m fishmindos --hot-reload
python -m fishmindos --skill-path ./custom_skills
python -m fishmindos --nav-server <host> --nav-app <host>
```

### 5.2 仿真链路启动

#### 方案：测真实 LLM 的规划能力

```bash
python mock_fishmindos.py
```

适合测试：

- 是否会先站立再导航
- 是否会正确插入 `system_wait`
- 是否能识别“完成后亮灯/完成后播报”
- 是否会生成多余步骤

适合测试：

- 骨架流程是否连通
- 简化交互是否稳定
- 无真机情况下做快速结构验证

## 6. 真实运行时的推荐操作步骤

### 6.1 初次启动

1. 准备 `fishmindos.config.json`
2. 检查 LLM 配置是否有效
3. 检查导航接口与实时接口是否可达
4. 如果要接收导航事件，启用 `callback`
5. 运行 `python -m fishmindos`

### 6.2 启动后你会看到什么

主程序通常会依次打印：

1. 技能系统初始化
2. 机器人连接与健康检查
3. 大脑初始化
4. 交互层初始化
5. 终端欢迎界面

然后你就可以在终端直接输入自然语言指令，例如：

- 去某个地点
- 打开某种灯光
- 播报某句话
- 查看电量
- 返回回充点

### 6.3 退出

可以使用：

- `退出`
- `exit`
- `quit`
- `Ctrl+C`

系统会尽量走统一的 shutdown 流程，关闭技能加载器、回调接收器和设备连接。

## 7. 回调机制说明

当前主链已经支持导航回调驱动的上下文更新。

### 7.1 为什么要启用回调

启用回调后，系统可以更及时地知道：

- 导航何时启动
- 正在去哪个目标点
- 当前位姿
- 目标位姿
- 到达了哪个点
- 回充何时完成

这会直接影响：

- `system_status`
- `system_wait`
- `nav_goto_location`
- 大脑中的 `session_context`

### 7.2 回调接收器做什么

`interaction/callback_receiver.py` 会在本机起一个轻量 HTTP 服务，用来：

- 接收回调 POST
- 暂存最近若干条事件
- 将事件分发给适配器
- 在终端打印简短回调日志

### 7.3 当前回调对主流程的影响

回调事件到来后，会更新：

- 当前地图
- 当前位置
- 目标位置
- 是否在导航
- 到达信息
- 回充完成状态

所以现在等待逻辑不再只依赖轮询，也会优先利用回调。

## 8. 技能系统工作方式

技能系统是这套项目的动作执行骨架。

### 8.1 技能执行的统一模式

每个技能通常有：

- `name`
- `description`
- `parameters`
- `execute()`

执行结果统一返回 `SkillResult`，最终转换成：

- `ok`
- `detail`
- `data`

### 8.2 默认内置技能分类

- 导航技能
- 动作技能
- 音频技能
- 灯光技能
- 系统技能
- 物品任务技能
- 回调技能

### 8.3 自定义技能

如果你要扩展技能，优先从这几个位置入手：

- `fishmindos/skills/base.py`
- `fishmindos/skills/loader.py`
- `fishmindos.config.json` 中的 `skills.search_paths`

推荐做法：

1. 在自定义目录里新增技能文件
2. 保持与内置技能相同的接口风格
3. 把目录加入 `search_paths`
4. 重启程序或启用热重载

## 9. LLM 与规则引擎的关系

### 9.1 正常情况

优先使用 `LLMBrain`：

- 识别用户意图
- 生成技能步骤
- 执行技能
- 更新上下文

### 9.2 LLM 不可用时

会回退到 `SmartBrain` 或规则规划器。

这意味着：

- 系统不一定彻底不可用
- 但复杂中文复合任务的表现通常会下降

### 9.3 提示词文档的定位

`docs/` 目录主要承担：

- 角色说明
- 工具说明
- Prompt 规则沉淀

但当前真实主链里的核心 system prompt 仍然以 `llm_brain.py` 为主。  
因此：

- 改 `docs/` 会有帮助
- 但并不代表主行为一定完全随文档变化
- 真正的主行为仍要结合 `llm_brain.py` 一起看

## 10. 调试建议

### 10.1 如果要查“为什么不执行”

优先看：

- `fishmindos/brain/llm_brain.py`
- `fishmindos/skills/builtin/navigation.py`
- `fishmindos/skills/builtin/system.py`
- `fishmindos/adapters/fishbot.py`

### 10.2 如果要查“为什么计划不对”

优先看：

- `fishmindos/brain/llm_brain.py`
- `fishmindos/brain/planner.py`
- `docs/prompt.md`
- `docs/tools.md`

### 10.3 如果要查“为什么回调没生效”

优先看：

- `fishmindos/config.py`
- `fishmindos/interaction/callback_receiver.py`
- `fishmindos/adapters/fishbot.py`
- 终端中 callback 相关日志

### 10.4 如果要查“为什么技能没被加载”

优先看：

- `fishmindos/skills/loader.py`
- `fishmindos/skills/__init__.py`
- 配置里的 `skills.search_paths`

## 11. 仓库中哪些内容不是核心运行链

下面这些通常不是主链核心逻辑：

- `.git/`
- `.vscode/`
- `.claude/`
- `__pycache__/`
- `.pytest_cache/`
- `skill_store/`
  - 如果你当前没有在里面放自定义技能，它只是预留目录

## 12. 维护建议

### 12.1 配置管理

- `fishmindos.config.example.json` 保持脱敏
- `fishmindos.config.json` 只放本机运行配置
- 敏感项尽量走环境变量

### 12.2 文档维护

建议每次做较大改动时，同时更新：

- 本 README
- `docs/tools.md`
- `docs/prompt.md`

### 12.3 回归测试建议

每次改完大脑或导航逻辑，至少回归这几类指令：

- 单步导航
- 导航 + 灯光
- 导航 + 播报
- 回充
- 回充完成后动作
- 取物送物复合链

推荐先在 mock 里过一遍，再上真机。

## 13. 一个最常见的工作流

### 方案一：先测规划，再上真机

1. 在 `mock_fishmindos.py` 中验证 LLM 规划
2. 确认工具顺序正确
3. 再运行 `python -m fishmindos`
4. 在真实链路中测试接口联通、回调联通和执行结果

### 方案二：直接调真实链路

1. 准备配置文件
2. 启动 `python -m fishmindos`
3. 先测试：
   - 查看状态
   - 站立
   - 简单导航
   - 回充
4. 再测试复合任务

## 14. 总结

当前这份仓库已经收敛成一套相对清晰的主链：

- `__main__.py` 负责组装系统
- `config.py` 负责配置
- `skills/` 负责动作定义
- `adapters/` 负责对接真实能力
- `brain/` 负责规划和决策
- `interaction/` 负责终端与回调入口
- `mock_fishmindos.py` 负责仿真验证

如果以后你继续裁剪仓库，建议优先保住这几块：

- `fishmindos/__main__.py`
- `fishmindos/config.py`
- `fishmindos/skills/`
- `fishmindos/adapters/`
- `fishmindos/brain/`
- `fishmindos/interaction/`
- `mock_fishmindos.py`
- `fishmindos.config.example.json`

这样基本就能继续维持“真实运行 + 仿真验证”这两条主线。

## 15. 后续改进方向

下面这些是比较值得继续推进的方向，其中最重要的是补一层 `world`，也就是“世界地图 / 世界模型”。

### 15.1 新增 `world` 层

当前系统已经有：

- 当前地图
- 当前路点
- 当前位姿
- 目标点
- 导航状态

但这些信息主要还是分散在：

- `session_context`
- `adapter` 内部状态
- 回调事件
- 技能执行结果

后续建议把它们统一收口到一个新的模块，例如：

```text
fishmindos/world/
├─ __init__.py
├─ model.py
├─ map_graph.py
├─ semantic_store.py
├─ state_tracker.py
└─ resolver.py
```

这个 `world` 层建议承担以下职责：

- 维护“当前在哪一层、哪张图、哪个路点、哪个语义区域”
- 维护跨地图关系，例如“楼下 = 1层，楼上 = 26层”
- 维护语义别名，例如“前台、大厅、回充点、厕所”的标准化名称
- 维护地图与路点的全局索引
- 维护目标点与当前位置的关系
- 维护机器人携带物、任务状态、回充状态等长期状态

### 15.2 世界地图应该解决什么问题

目前很多问题本质上都来自“系统只知道当前地图，不知道更大的世界关系”。

增加世界地图后，应该重点解决这些能力：

1. 跨楼层理解

- 用户说“去楼下”
- 系统能直接解析成某个目标地图
- 不再只把它当成普通地点名

2. 全局地点解析

- 用户说“去大厅”
- 如果多个地图里都有“大厅”，系统能结合当前地图、上下文和常用规则做选择
- 如果无法唯一确定，再决定是否追问

3. 回充点全局统一

- 不同地图里的回充点名称可能不同
- 世界层可以把它们归一成统一语义：`dock`

4. 路径级任务理解

- 用户说“去大厅，亮红灯，然后去厕所，再回充”
- 世界层可以知道这些地点分别属于哪张图、是否需要切图、是否可以直接导航

5. 长任务状态保持

- 当前任务做到哪一步
- 上一次到达了哪个点
- 当前带着什么东西
- 下一步应该去哪

### 15.3 世界地图建议的数据结构

可以把世界信息拆成几类对象：

#### 地图对象

- `map_id`
- `map_name`
- `aliases`
- `floor`
- `building`
- `description`

#### 路点对象

- `waypoint_id`
- `waypoint_name`
- `aliases`
- `map_id`
- `type`
- `pose`
- `tags`

#### 语义地点对象

例如：

- `大厅`
- `前台`
- `厕所`
- `回充点`

它不一定只绑定一个具体 waypoint，而是一个“语义概念”。  
解析时再由 `resolver` 决定落到哪个具体地图和 waypoint。

#### 世界状态对象

- `current_map`
- `current_waypoint`
- `current_pose`
- `target_map`
- `target_waypoint`
- `nav_running`
- `charging`
- `carrying_item`
- `last_arrival`
- `last_callback_event`

### 15.4 世界层与当前模块的关系

如果以后增加 `world`，建议让它和现有模块这样协作：

#### 与 `adapter` 的关系

`adapter` 负责拿原始事实：

- 当前位姿
- 当前地图
- 当前目标点
- 到达事件
- 回充完成事件

`world` 负责把这些原始事实转成统一状态。

#### 与 `skills` 的关系

技能不再自己反复猜地图和路点，而是优先向 `world` 查询：

- “大厅”对应哪个地图
- 当前是否需要先切图
- 当前任务的等待对象是谁

#### 与 `brain` 的关系

`LLMBrain` 不必只看零散的 `session_context`，而是可以直接拿一份结构化世界状态。

这样 prompt 里就可以明确写：

- 当前地图
- 当前楼层
- 当前所在语义地点
- 已知世界中的关键地点
- 当前目标

这会明显提升复杂任务规划质量。

### 15.5 世界层与回调的结合

当前系统已经能收到这些导航事件：

- 启动导航
- 导航中位置更新
- 目标点更新
- 到达目标
- 回充完成

这些事件很适合直接喂给 `world/state_tracker.py`。

建议未来形成这样的链路：

```text
callback_receiver
  -> adapter.handle_callback_event()
  -> world.state_tracker.apply_event()
  -> world model updated
  -> brain / skills read latest world state
```

这样做的好处是：

- 等待逻辑更稳定
- 当前地图和位置更准确
- 不再大量依赖技能间手动写回上下文

### 15.6 世界层与仿真系统的结合

后续 mock 系统也建议接入 `world`，这样仿真就不只是“假接口”，而是真正的“假世界”。

建议 future mock 支持：

- 多张地图
- 多楼层
- 路点别名
- 语义地点
- 物品分布
- 电量变化
- 回充状态变化

这样你就可以在 mock 中直接测：

- “去楼下拿纸，送到大厅，再回充”
- “去前台，再去厕所，最后回到当前楼层回充点”
- “如果当前在 26 层，大厅指的是哪一个大厅”

### 15.7 推荐的落地顺序

如果后面真要做 `world`，我建议按这个顺序来：

1. 先做只读版世界状态

- 不改变主链执行逻辑
- 先把当前地图、路点、位姿、回调事件统一收口

2. 再做地点解析器

- 把“楼下、楼上、大厅、前台、回充点”这种自然语言映射成结构化目标

3. 再把导航技能接到 `world`

- `nav_goto_location`
- `nav_start`
- `system_wait`

4. 最后再让 `LLMBrain` 直接依赖 `world`

- 把 prompt 里的状态来源切换到世界模型
- 减少零散 session context 的判断逻辑

### 15.8 一个理想目标

当 `world` 层成熟后，希望系统能做到：

- 不只是“知道当前地图”
- 而是“知道整个可导航世界”
- 不只是“执行单个技能”
- 而是“在一个稳定的世界模型里完成连续任务”

那时 FishMindOS 会更像一个真正有空间理解能力的机器人控制系统，而不只是一个“LLM + 技能调用器”。
