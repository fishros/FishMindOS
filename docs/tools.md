# FishMindOS 工具体系

## 总则

当前对大模型可见的工具只有两个：

1. `submit_mission`
2. `system_status`

不要再把用户请求拆成大量底层工具调用。  
导航、回充、灯光、播报、人机协同等待，都应统一编排进一次 `submit_mission` 调用中。

底层导航、动作、灯光、回调、等待类能力属于系统内部实现细节，不应直接作为大模型工具使用。

---

## 工具 1: submit_mission

### 作用

把一个完整的物理任务，转换成按顺序执行的 `tasks` 数组，并一次性提交给系统执行。

这是唯一的任务执行入口。

### 适用场景

- 去某个地点
- 返回回充
- 开灯、关灯、闪灯
- 到点后播报
- 取物、送物
- 需要等待人类确认后再继续的任务
- 多步骤复合任务

### 参数格式

`submit_mission` 的参数是一个对象，核心字段是：

```json
{
  "tasks": [
    {"action": "goto", "target": "大厅"},
    {"action": "light", "color": "green"},
    {"action": "dock"}
  ]
}
```

### 可用 action

#### `goto`

前往一个语义地点。

参数：

- `target`: 目标地点名称

示例：

```json
{"action": "goto", "target": "卫生间"}
```

#### `dock`

返回回充点。

参数：无

示例：

```json
{"action": "dock"}
```

#### `light`

设置灯光。

参数：

- `color`: 灯光颜色，当前使用 `red` / `yellow` / `green`

示例：

```json
{"action": "light", "color": "green"}
```

#### `speak`

播报一句话。

参数：

- `text`: 播报内容

示例：

```json
{"action": "speak", "text": "任务完成"}
```

#### `wait_confirm`

等待人类确认后再继续执行。

适用于取快递、送纸、交付物品、等待人放置物体等场景。

参数：通常无

示例：

```json
{"action": "wait_confirm"}
```

#### `query`

在任务流内部读取一次基础状态，然后继续后续动作。

这不是普通对话问答工具，而是任务流中的即时辅助动作。

参数：无

示例：

```json
{"action": "query"}
```

---

## 工具 2: system_status

### 作用

用于纯状态查询。

### 适用场景

- 现在电量多少
- 当前在哪里
- 是否正在导航
- 是否正在充电
- 当前整体状态如何

### 使用原则

当用户只是查询状态时：

1. 调用 `system_status`
2. 根据结果直接用自然语言回答
3. 不要调用 `submit_mission`

---

## 规划原则

### 什么时候用 `submit_mission`

只要用户要求执行真实动作，就应该优先用 `submit_mission`。

例如：

- “去大厅”
- “去厕所，到了开绿灯，然后回来充电”
- “去大厅拿快递，送到公司，再回充”

### 什么时候用 `system_status`

只有在用户明确是查状态，而不是让系统做动作时，才用 `system_status`。

例如：

- “现在电量多少”
- “当前在干什么”
- “是不是在充电”

### 什么时候不用工具

如果用户是在聊天、问身份、问解释、问能力范围，则直接回答，不调用任何工具。

例如：

- “你叫什么”
- “你是谁”
- “你能做什么”

---

## 示例

### 示例 1: 简单导航

用户：

`去大厅，然后回来充电`

应生成：

```json
{
  "tasks": [
    {"action": "goto", "target": "大厅"},
    {"action": "dock"}
  ]
}
```

### 示例 2: 到点后执行动作

用户：

`去卫生间，到了开绿灯，然后回来充电`

应生成：

```json
{
  "tasks": [
    {"action": "goto", "target": "卫生间"},
    {"action": "light", "color": "green"},
    {"action": "dock"}
  ]
}
```

### 示例 3: 人机协同

用户：

`去大厅拿快递，送到公司，再回充`

应生成：

```json
{
  "tasks": [
    {"action": "goto", "target": "大厅"},
    {"action": "speak", "text": "请帮我把快递放到篮子上"},
    {"action": "wait_confirm"},
    {"action": "goto", "target": "公司"},
    {"action": "speak", "text": "已经取到快递，请拿走"},
    {"action": "wait_confirm"},
    {"action": "dock"}
  ]
}
```

### 示例 4: 状态查询

用户：

`现在电量多少`

应调用：

- `system_status`

然后直接用自然语言回答，不生成 `submit_mission`。

---

## stop_nav 规则补充

- 当用户要求“关闭导航 / 停止导航 / 取消当前导航”时，这属于动作执行，不属于状态查询。
- 此时应调用 `submit_mission`，并生成：

```json
{
  "tasks": [
    {"action": "stop_nav"}
  ]
}
```

- 不要把“关闭导航”错误规划成 `system_status`。
