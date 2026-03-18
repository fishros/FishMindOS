# TOOLS

## Macro Tools

### robot_navigation_assistant

用途：

- 去某个位置
- 按地图名启动导航
- 查当前位置
- 查导航状态
- 列出地图

规则：

- 直接用 `location_name` 或 `map_name`
- 不要自己查 `map_id` 或 `waypoint_id`
- `回充` 优先当成 dock 语义

### robot_task_assistant

用途：

- 列任务
- 看任务描述
- 执行任务
- 取消任务
- 创建导航任务

规则：

- 直接用 `task_name`
- 创建导航任务时，直接给 `name / map_name / waypoint_names / dock_waypoint_name / start_nav / stand_first`
- 不要让模型自己拼 Blockly 程序

### robot_task_chain

用途：

- 保存任务链
- 查看任务链
- 删除任务链
- 执行任务链

规则：

- `steps` 里存宏观步骤
- 不要把任务链拆成底层 CRUD 查询

## Direct Tools

### robot_light

- `set`
- 开灯默认红灯常亮：`{"action": "set", "code": 11}`
- 关灯：`{"action": "set", "on": false}`
- 灯光 code 映射（必须用 code，不要用 on: true）：
  - 红灯常亮: 11，红灯慢闪: 21，红灯快闪: 31
  - 黄灯常亮: 12，黄灯慢闪: 22，黄灯快闪: 32
  - 绿灯常亮: 13，绿灯慢闪: 23，绿灯快闪: 33
- 用户说"打开绿灯"→ `{"action": "set", "code": 13}`
- 用户说"开灯"不指定颜色 → `{"action": "set", "code": 11}`

### robot_motion

- `apply_preset`
- `stand` = 站立
- `lie_down` = 趴下

### robot_audio

- `tts_play`

### robot_status

- `charging_status`
- `battery_soc`

## General Rules

- 查状态优先查，不要直接控制
- 没有明确目标时，不要猜 ID
- 名字、地图、路点、任务的模糊匹配由运行时处理，不由模型处理
