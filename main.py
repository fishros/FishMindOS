from __future__ import annotations

from fishmindos import FishMindOSApp


def main() -> None:
    app = FishMindOSApp()

    generated = app.generate_reusable_skill(
        name="announce_arrival",
        response_text="已通过插件技能播报：机器人已到达指定位置。",
        description="示例：由 OS 生成的可复用插件技能",
    )
    print(f"已生成插件技能脚本: {generated}")

    text = "到行政拿纸巾送到厕所"
    result = app.run_text(text)

    print(f"任务: {text}")
    print(f"状态: {result['status']}")
    print("执行日志:")
    for event in result["events"]:
        print(f"- [{event.status.value}] {event.step_id}: {event.detail}")

    print("\n当前技能列表:")
    for name in result["skills"]:
        print(f"- {name}")


if __name__ == "__main__":
    main()
