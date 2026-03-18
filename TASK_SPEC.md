# TASK SPEC

FishMindOS 的输出分两类：

1. 工具计划
2. 直接短回复

## 工具计划

如果用户是在控制机器狗或查询机器人数据，优先输出工具调用。

如果模型不能直接返回 `tool_calls`，就输出：

```json
{
  "steps": [
    {
      "name": "robot_navigation_assistant",
      "arguments": {
        "action": "current_position"
      }
    }
  ]
}
```

要求：

- `name` 必须是真实存在的工具
- `arguments` 必须符合工具 schema
- 不要输出空步骤
- 不要编造参数

## 直接短回复

以下场景可以不调用工具，直接回一句短中文：

- 用户问你叫什么
- 用户问你会什么
- 简单问候
- 缺少关键参数时的一句澄清

## Priority

- 先考虑本地快规划
- 再考虑宏观工具
- 最后才考虑底层工具
