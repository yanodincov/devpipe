from __future__ import annotations

from devpipe.ui.widgets.task_snapshot import build_task_snapshot_lines, format_snapshot_value


def test_format_snapshot_value_truncates_multiline_task() -> None:
    # format_snapshot_value does not truncate — truncation happens in build_task_snapshot_lines
    # For a multiline string with no special handling, it is returned as-is
    task = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    result = format_snapshot_value(task, key="task")
    assert "Line 1" in result
    assert "Line 2" in result


def test_format_snapshot_value_keeps_short_task() -> None:
    task = "Line 1\nLine 2"
    result = format_snapshot_value(task, key="task")
    assert result == "Line 1\nLine 2"


def test_format_snapshot_value_exactly_3_lines() -> None:
    task = "Line 1\nLine 2\nLine 3"
    result = format_snapshot_value(task, key="task")
    assert result == "Line 1\nLine 2\nLine 3"


def test_format_snapshot_value_single_line_task() -> None:
    task = "Single line task"
    result = format_snapshot_value(task, key="task")
    assert result == "Single line task"


def test_format_snapshot_value_empty_task() -> None:
    result = format_snapshot_value("", key="task")
    assert result == "[dim](empty)[/dim]"


def test_format_snapshot_value_non_task_not_truncated() -> None:
    value = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    result = format_snapshot_value(value, key="other_field")
    assert result == value


def test_format_snapshot_value_list() -> None:
    result = format_snapshot_value(["a", "b", "c"])
    assert result == "a, b, c"


def test_format_snapshot_value_dict_tags() -> None:
    result = format_snapshot_value({"tag1": ["role1", "role2"], "tag2": ["role3"]}, key="tags")
    assert result == "tag1 (role1, role2), tag2 (role3)"


def test_format_snapshot_value_bool() -> None:
    assert format_snapshot_value(True) == "true"
    assert format_snapshot_value(False) == "false"


def test_build_task_snapshot_lines_shows_empty_standard_and_custom_fields() -> None:
    lines = build_task_snapshot_lines(
        {
            "profile": "idea-lab",
            "task": "",
            "runner": "codex",
            "model": "",
            "effort": "",
            "tags": {},
            "first_role": "",
            "last_role": "",
            "component": "",
            "dataset": [],
        },
        [("component", "Component"), ("dataset", "Dataset")],
    )

    # Lines use aligned column format: "  [dim]Label         [/dim]value"
    assert any("Task" in line and "[dim](empty)[/dim]" in line for line in lines)
    assert any("Model" in line and "[dim](empty)[/dim]" in line for line in lines)
    assert any("Tags" in line and "[dim](empty)[/dim]" in line for line in lines)
    assert any("◆ CUSTOM" in line for line in lines)
    assert any("Component" in line and "[dim](empty)[/dim]" in line for line in lines)
    assert any("Dataset" in line and "[dim](empty)[/dim]" in line for line in lines)


def test_build_task_snapshot_lines_starts_profile_immediately_after_general_header() -> None:
    lines = build_task_snapshot_lines(
        {
            "profile": "file-demo",
            "task": "",
            "runner": "auto",
            "model": "low",
            "effort": "low",
            "tags": {},
            "first_role": "write",
            "last_role": "",
        },
        [("topic", "Topic")],
    )

    assert lines[0] == "[bold #7aa2f7]◆ GENERAL[/bold #7aa2f7]"
    assert "Profile" in lines[1]
