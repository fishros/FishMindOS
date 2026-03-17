from __future__ import annotations

from pathlib import Path

from fishmindos import FishMindOSApp


def test_delivery_flow_success(tmp_path: Path) -> None:
    app = FishMindOSApp(skills_dir=tmp_path / "skills")
    result = app.run_text("到行政拿纸巾送到厕所")

    assert result["status"] == "success"
    assert len(result["events"]) == 5
    assert result["events"][0].detail.startswith("已到达")


def test_plugin_skill_persistent_and_reusable(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"

    app = FishMindOSApp(skills_dir=skills_dir)
    script_path = app.generate_reusable_skill(
        name="custom notify",
        response_text='自定义通知完成 "ok"',
        description="测试插件技能",
    )

    assert Path(script_path).exists()
    assert "custom_notify" in app.registry.names()

    # 模拟重启，确保技能从脚本自动加载
    app_restarted = FishMindOSApp(skills_dir=skills_dir)
    assert "custom_notify" in app_restarted.registry.names()

    result = app_restarted.registry.get("custom_notify").run({}, {})
    assert result["ok"] is True
    assert result["detail"] == '自定义通知完成 "ok"'


def test_invalid_plugin_file_does_not_break_loading(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    (skills_dir / "bad_plugin.py").write_text("raise RuntimeError('boom')", encoding="utf-8")

    app = FishMindOSApp(skills_dir=skills_dir)
    assert "bad_plugin" not in app.registry.names()
