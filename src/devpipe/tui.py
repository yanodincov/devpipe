from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import questionary
from questionary import Separator
from questionary.prompts.common import InquirerControl
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

_orig_get_choice_tokens = InquirerControl._get_choice_tokens


def _patched_get_choice_tokens(self):  # type: ignore[override]
    tokens = _orig_get_choice_tokens(self)
    result = []
    for s, t in tokens:
        if s == "class:text" and "  Description: " in t:
            t = t.replace("  Description: ", "\n  ", 1)
        elif s == "class:disabled" and t.startswith("- "):
            t = t[2:]
        result.append((s, t))
    return result


InquirerControl._get_choice_tokens = _patched_get_choice_tokens  # type: ignore[method-assign]


from devpipe.app import RunConfig
from devpipe.history import load_history
from devpipe.project_config import load_project_config
from devpipe.runtime.state import STAGE_ORDER
from devpipe.tags import load_available_tags, load_tag_definitions


def _git_branch() -> str:
    try:
        r = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _task_id_from_branch(branch: str) -> str:
    m = re.match(r"^([A-Z]+-[0-9]+)", branch)
    return m.group(1) if m else ""


def _effective_last(cfg: dict) -> str:
    if cfg["last_role"]:
        return cfg["last_role"]
    return "qa_stand" if cfg["target_branch"] else "qa_local"


def _checkbox_with_apply(
    prompt: str,
    names: list[str],
    selected: set[str],
    style,
    console: Console,
    render: Callable[[], None] | None = None,
) -> list[str] | None:
    """Tag checkbox: Enter toggles, 'Apply' confirms."""
    current = set(selected)
    cursor: str = names[0] if names else "__apply__"
    while True:
        console.clear()
        if render:
            render()
            print()
        items = []
        for name in names:
            if name in current:
                title = [("fg:black bg:cyan bold", f" {name} ")]
            else:
                title = [("", f" {name} ")]
            items.append(questionary.Choice(title=title, value=name))
        items.append(Separator(" "))
        items.append(questionary.Choice(title="Apply", value="__apply__"))

        val = questionary.select(prompt, choices=items, style=style, default=cursor, instruction=" ").ask()
        if val is None:
            return None
        if val == "__apply__":
            return [n for n in names if n in current]
        cursor = val
        if val in current:
            current.discard(val)
        else:
            current.add(val)


def _multi_param_select(
    prompt: str,
    available: list[str],
    current: list[str],
    style,
    console: Console,
    render: Callable[[], None] | None = None,
) -> list[str] | None:
    """Multi-select for params: builtin choices + custom input. Custom values disappear when deselected."""
    builtin = list(available)
    selected: set[str] = set(current)
    # custom values: those selected but not in builtin
    custom: list[str] = [v for v in current if v not in builtin]
    cursor: str = (builtin + custom)[0] if (builtin or custom) else "__apply__"

    while True:
        console.clear()
        if render:
            render()
            print()

        all_choices = builtin + custom
        items = []
        for name in all_choices:
            if name in selected:
                title = [("fg:black bg:cyan bold", f" {name} ")]
            else:
                title = [("", f" {name} ")]
            items.append(questionary.Choice(title=title, value=name))
        items.append(Separator(" "))
        items.append(questionary.Choice(title="Add custom value...", value="__custom__"))
        items.append(questionary.Choice(title="Apply", value="__apply__"))

        val = questionary.select(prompt, choices=items, style=style, default=cursor, qmark="", instruction=" ").ask()
        if val is None:
            return None
        if val == "__apply__":
            return [v for v in (builtin + custom) if v in selected]
        if val == "__custom__":
            console.clear()
            if render:
                render()
                print()
            new_val = questionary.text("Custom value:", style=style, qmark="").ask()
            if new_val and new_val.strip():
                v = new_val.strip()
                if v not in builtin and v not in custom:
                    custom.append(v)
                selected.add(v)
                cursor = v
            continue
        cursor = val
        if val in selected:
            selected.discard(val)
            # remove custom value from list when deselected
            if val not in builtin and val in custom:
                custom.remove(val)
                cursor = all_choices[0] if all_choices else "__apply__"
        else:
            selected.add(val)


def _select_or_text(prompt: str, options: list[str], default: str, style) -> str | None:
    if options:
        choices = options + ["(other...)"]
        val = questionary.select(
            prompt, choices=choices,
            default=default if default in options else choices[0],
            style=style, qmark="", instruction=" ",
        ).ask()
        if val is None:
            return None
        if val == "(other...)":
            return questionary.text(prompt, default=default, style=style, qmark="").ask()
        return val
    return questionary.text(prompt, default=default, style=style, qmark="").ask()


def _history_menu(history: list[dict], console: Console) -> dict | None:
    """Show history list with live panel preview on hover. Enter runs immediately."""
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    entries = history[:20]
    if not entries:
        return None

    idx = [0]
    result: list[dict | None] = [None]

    def _panel_tokens() -> list[tuple[str, str]]:
        h = entries[idx[0]]
        eff_first = h.get("first_role") or "architect"
        eff_last = h.get("last_role") or "qa_stand"
        extra = h.get("extra_params") or {}
        tags = h.get("tags") or []

        rows: list[tuple[str, str]] = [
            ("date", h.get("date") or ""),
            ("task", h.get("task") or "(empty)"),
            ("task-id", h.get("task_id") or "—"),
            ("runner", h.get("runner") or ""),
            ("target-branch", h.get("target_branch") or "none"),
            ("service", h.get("service") or ""),
            ("tags", ", ".join(tags) if tags else "none"),
        ]
        for k, v in extra.items():
            display = ", ".join(v) if isinstance(v, list) else str(v)
            rows.append((f"  {k}", display))
        rows.append(("roles", f"{eff_first} → {eff_last}"))

        key_w = max(len(r[0]) for r in rows) + 2
        # W = box width (chars between ╭ and ╮ inclusive = terminal - 2 space prefix)
        W = shutil.get_terminal_size().columns - 2
        # inner content between │ borders = W - 2
        # line: "  │" + "  " + kstr + " " + vstr + " "*pad + " " + "│"
        # so: 2 + key_w + 1 + len(vstr) + pad + 1 = W - 2  →  pad = W - 6 - key_w - len(vstr)
        max_v_base = W - 6 - key_w

        B = "fg:#4488cc"
        toks: list[tuple[str, str]] = []
        ttl = " devpipe "
        left_d = (W - 2 - len(ttl)) // 2
        right_d = W - 2 - len(ttl) - left_d
        toks.append((B, "  ╭" + "─" * left_d))
        toks.append(("bold fg:cyan", ttl))
        toks.append((B, "─" * right_d + "╮\n"))
        toks.append((B, "  │")); toks.append(("", " " * (W - 2))); toks.append((B, "│\n"))
        for key, val in rows:
            kstr = key.ljust(key_w)
            vstr = str(val)
            if len(vstr) > max_v_base:
                vstr = vstr[:max_v_base - 1] + "…"
            pad = max(0, max_v_base - len(vstr))
            toks += [
                (B, "  │  "),
                ("bold fg:#888888", kstr),
                ("", " " + vstr + " " * pad + " "),
                (B, "│\n"),
            ]
        toks.append((B, "  │")); toks.append(("", " " * (W - 2))); toks.append((B, "│\n"))
        toks.append((B, "  ╰" + "─" * (W - 2) + "╯\n"))
        toks.append(("", "\n"))
        return toks

    def _list_tokens() -> list[tuple[str, str]]:
        toks: list[tuple[str, str]] = []
        for i, h in enumerate(entries):
            date = h.get("date", "")
            task_short = (h.get("task") or "")[:45]
            label = f"{date}  {task_short}"
            if i == idx[0]:
                toks.append(("fg:cyan", f"  »  {label}\n"))
            else:
                toks.append(("fg:#888888", f"     {label}\n"))
        toks.append(("", "\n"))
        toks.append(("fg:#555555", "  Enter — load   Esc — cancel\n"))
        return toks

    kb = KeyBindings()

    @kb.add("up")
    def _(event):  # type: ignore[misc]
        idx[0] = max(0, idx[0] - 1)

    @kb.add("down")
    def _(event):  # type: ignore[misc]
        idx[0] = min(len(entries) - 1, idx[0] + 1)

    @kb.add("enter")
    def _(event):  # type: ignore[misc]
        result[0] = entries[idx[0]]
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _(event):  # type: ignore[misc]
        event.app.exit()

    layout = Layout(
        HSplit([
            Window(
                FormattedTextControl(_panel_tokens, focusable=False, show_cursor=False),
                dont_extend_height=True,
            ),
            Window(
                FormattedTextControl(_list_tokens, focusable=True, show_cursor=False),
                dont_extend_height=True,
            ),
        ])
    )

    console.clear()
    app = Application(layout=layout, key_bindings=kb, full_screen=False, mouse_support=False)
    app.run()
    return result[0]


def _render_summary(cfg: dict, tag_params_meta: list, console: Console) -> None:
    eff_first = cfg["first_role"] or "architect"
    eff_last = _effective_last(cfg)

    table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
    table.add_column(style="bold dim", width=16)
    table.add_column()

    table.add_row("task", cfg["task"] if cfg["task"] else Text("(empty)  ← required", style="red"))
    table.add_row("task-id", cfg["task_id"] if cfg["task_id"] else Text("none — Jira skipped", style="dim"))
    table.add_row("runner", cfg["runner"])
    table.add_row(
        "target-branch",
        cfg["target_branch"] if cfg["target_branch"] else Text(f"none → last role: {eff_last}", style="dim"),
    )
    table.add_row("service", cfg["service"])
    table.add_row("namespace", cfg["namespace"] if cfg["namespace"] else Text("auto", style="dim"))
    table.add_row("tags", ", ".join(cfg["tags"]) if cfg["tags"] else Text("none", style="dim"))

    for _tag_name, param, _available, _default in tag_params_meta:
        raw = cfg["extra_params"].get(param.key, "")
        if isinstance(raw, list):
            display = ", ".join(raw) if raw else ""
        else:
            display = raw
        label = Text(display if display else "(empty)", style="dim" if not display else "default")
        table.add_row(f"  {param.key}", label)

    table.add_row("roles", f"{eff_first} → {eff_last}")

    console.print(Panel(table, title="[bold blue]devpipe[/bold blue]", border_style="blue", padding=(1, 2)))


_STYLE = questionary.Style([
    ("selected", "fg:cyan bold"),
    ("pointer", "fg:cyan bold"),
    ("highlighted", "fg:cyan noreverse"),
    ("answer", "fg:green bold"),
    ("question", "bold"),
    ("text", "fg:#888888"),
    ("disabled", "fg:#555555"),
])


def run_tui(base_dir: Path) -> RunConfig | None:
    console = Console()
    project_cfg = load_project_config()
    all_tags = load_available_tags()
    available_tag_names = list(all_tags.keys())

    default_tags = [t for t in project_cfg.default("tags", []) if t in all_tags]

    cfg: dict = {
        "task": "",
        "task_id": _task_id_from_branch(_git_branch()),
        "runner": project_cfg.default("runner", "codex"),
        "target_branch": project_cfg.default("target_branch", ""),
        "service": project_cfg.default("service", "acquiring"),
        "namespace": project_cfg.default("namespace", ""),
        "tags": default_tags,
        "extra_params": {},
        "first_role": "",
        "last_role": "",
    }


    def _load_tag_params() -> list:
        # Tag params via params.yaml are deprecated. All inputs are in pipeline.yml.
        return []

    def _init_tag_param_defaults(tag_params_meta: list) -> None:
        # No-op: tag params are deprecated
        pass

    def _input_header() -> None:
        console.clear()
        _render_summary(cfg, tag_params_meta, console)
        print()

    # Pre-populate extra_params from project_cfg.defaults (all tag params, no role filter)
    _STANDARD_KEYS = {"task", "task_id", "runner", "target_branch", "service", "namespace", "tags", "first_role", "last_role"}
    for key, val in project_cfg.defaults.items():
        if key not in _STANDARD_KEYS:
            if isinstance(val, list):
                val = [str(v) for v in val]
            elif val is not None:
                val = str(val)
            cfg["extra_params"].setdefault(key, val)

    # Init defaults from already-selected tags
    tag_params_meta = _load_tag_params()
    _init_tag_param_defaults(tag_params_meta)

    menu_cursor: str | None = None
    while True:
        tag_params_meta = _load_tag_params()
        console.clear()
        _render_summary(cfg, tag_params_meta, console)
        print()

        def _c(title: str, desc: str) -> questionary.Choice:
            return questionary.Choice(title, description="\n\n  " + desc)

        choices: list = [
            _c("Set task",          "What needs to be done — the main prompt for the AI agent"),
            _c("Set task ID",       "Jira ticket ID (e.g. MRC-123); leave empty to skip Jira context"),
            _c("Set runner",        "AI runner: codex, claude, or auto (take runner from each role)"),
            _c("Set target branch", "Deploy stand branch; if empty — pipeline stops at qa_local"),
            _c("Set service",       "Service name passed only to the release stage"),
            _c("Set namespace",     "Kubernetes namespace passed explicitly to the release stage"),
        ]
        if available_tag_names:
            choices.append(_c("Set tags", "Active tag set — each tag injects rules and params into the pipeline"))
        for _tag_name, param, _available, _default in tag_params_meta:
            desc = param.description or f"Parameter for {_tag_name} tag"
            choices.append(_c(f"Set {param.key}", desc))
        choices.append(_c("Set first role", "First pipeline stage to run (default: architect)"))
        choices.append(_c("Set last role",  "Last pipeline stage to run (default: qa_stand if target branch set, else qa_local)"))
        choices.append(Separator(" "))
        history = load_history()
        hist_desc = "\n\n  Load a previous run into the form" if history else "\n\n  No history yet — complete a run first"
        choices.append(questionary.Choice("History", description=hist_desc))
        run_desc = "\n\n  Start the pipeline with current configuration" if cfg["task"] else "\n\n  Task is required — use Set task first"
        choices.append(questionary.Choice("Run", description=run_desc))

        valid_values = [c.value if isinstance(c, questionary.Choice) else c for c in choices if not isinstance(c, Separator)]
        default_cursor = menu_cursor if menu_cursor in valid_values else None
        choice = questionary.select("", choices=choices, style=_STYLE, use_shortcuts=False, qmark="", default=default_cursor, instruction=" ").ask()
        if choice is None:
            return None
        menu_cursor = choice

        if choice == "Set task":
            _input_header()
            val = questionary.text("Task:", default=cfg["task"], style=_STYLE, qmark="").ask()
            if val is not None:
                cfg["task"] = val.strip()

        elif choice == "Set task ID":
            _input_header()
            val = questionary.text("Task ID (empty to skip Jira):", default=cfg["task_id"], style=_STYLE, qmark="").ask()
            if val is not None:
                cfg["task_id"] = val.strip()

        elif choice == "Set runner":
            _input_header()
            runner_choices = ["codex", "claude", "auto"]
            val = questionary.select("Runner:", choices=runner_choices, default=cfg["runner"] if cfg["runner"] in runner_choices else runner_choices[0], style=_STYLE, qmark="", instruction=" ").ask()
            if val is not None:
                cfg["runner"] = val

        elif choice == "Set target branch":
            _input_header()
            val = _select_or_text(
                "Target branch:",
                project_cfg.available_list("target_branch"),
                cfg["target_branch"],
                _STYLE,
            )
            if val is not None:
                cfg["target_branch"] = val.strip()

        elif choice == "Set service":
            _input_header()
            val = questionary.text("Service:", default=cfg["service"], style=_STYLE, qmark="").ask()
            if val is not None:
                cfg["service"] = val.strip()

        elif choice == "Set namespace":
            _input_header()
            val = _select_or_text(
                "Namespace:",
                project_cfg.available_list("namespace"),
                cfg["namespace"],
                _STYLE,
            )
            if val is not None:
                cfg["namespace"] = val.strip()

        elif choice == "Set tags":
            prev_tags = set(cfg["tags"])
            safe_selected = {t for t in cfg["tags"] if t in available_tag_names}
            val = _checkbox_with_apply(
                "Tags:", available_tag_names, safe_selected, _STYLE, console,
                render=lambda: _render_summary(cfg, tag_params_meta, console),
            )
            if val is not None:
                cfg["tags"] = val
                # Init defaults for newly added tags
                new_meta = _load_tag_params()
                _init_tag_param_defaults(new_meta)
                # Clean up params from removed tags
                removed = prev_tags - set(val)
                if removed:
                    removed_defs = load_tag_definitions(list(removed))
                    removed_keys = {p.key for d in removed_defs.values() for p in d.all_params}
                    for k in removed_keys:
                        cfg["extra_params"].pop(k, None)

        elif choice.startswith("Set ") and any(choice == f"Set {p.key}" for _, p, _, _ in tag_params_meta):
            param_key = choice[4:]
            meta = next(((t, p, av, df) for t, p, av, df in tag_params_meta if p.key == param_key), None)
            if meta:
                _tag_name, param, available, default = meta
                label = f"{param.key}" + (f" — {param.description}" if param.description else "") + ":"
                if param.multi:
                    raw = cfg["extra_params"].get(param.key, [])
                    cur_list = raw if isinstance(raw, list) else ([raw] if raw else [])
                    val_list = _multi_param_select(
                        label, available, cur_list, _STYLE, console,
                        render=lambda: _render_summary(cfg, tag_params_meta, console),
                    )
                    if val_list is not None:
                        cfg["extra_params"][param.key] = val_list
                else:
                    _input_header()
                    current = cfg["extra_params"].get(param.key, default)
                    val = _select_or_text(label, available, current if isinstance(current, str) else default, _STYLE)
                    if val is not None:
                        cfg["extra_params"][param.key] = val.strip()

        elif choice == "Set first role":
            _input_header()
            eff_last = _effective_last(cfg)
            last_idx = STAGE_ORDER.index(eff_last)
            allowed = STAGE_ORDER[: last_idx + 1]
            current = cfg["first_role"] or "architect"
            val = questionary.select(
                "First role:", choices=allowed,
                default=current if current in allowed else allowed[0], style=_STYLE, qmark="", instruction=" ",
            ).ask()
            if val is not None:
                cfg["first_role"] = "" if val == "architect" else val

        elif choice == "Set last role":
            _input_header()
            eff_first = cfg["first_role"] or "architect"
            first_idx = STAGE_ORDER.index(eff_first)
            allowed = STAGE_ORDER[first_idx:]
            current = cfg["last_role"] or _effective_last(cfg)
            val = questionary.select(
                "Last role:", choices=allowed,
                default=current if current in allowed else allowed[-1], style=_STYLE, qmark="", instruction=" ",
            ).ask()
            if val is not None:
                cfg["last_role"] = val

        elif choice == "History":
            if not history:
                continue
            picked = _history_menu(history, console)
            if picked:
                _valid_runners = {"codex", "claude", "auto"}
                _valid_roles = set(STAGE_ORDER)
                cfg["task"] = picked.get("task") or ""
                cfg["task_id"] = picked.get("task_id") or ""
                picked_runner = picked.get("runner") or ""
                if picked_runner in _valid_runners:
                    cfg["runner"] = picked_runner
                cfg["target_branch"] = picked.get("target_branch") or ""
                cfg["namespace"] = picked.get("namespace") or ""
                cfg["service"] = picked.get("service") or ""
                picked_tags = [t for t in (picked.get("tags") or []) if t in available_tag_names]
                cfg["tags"] = picked_tags
                cfg["extra_params"] = dict(picked.get("extra_params") or {})
                picked_first = picked.get("first_role") or ""
                if picked_first in _valid_roles or not picked_first:
                    cfg["first_role"] = picked_first
                picked_last = picked.get("last_role") or ""
                if picked_last in _valid_roles or not picked_last:
                    cfg["last_role"] = picked_last
                tag_params_meta = _load_tag_params()
                menu_cursor = "Run"

        elif choice == "Run":
            if not cfg["task"]:
                menu_cursor = "Set task"
                continue
            return RunConfig(
                task_id=cfg["task_id"] or None,
                task=cfg["task"],
                runner=cfg["runner"],
                target_branch=cfg["target_branch"] or None,
                namespace=cfg["namespace"] or None,
                service=cfg["service"] or None,
                tags=cfg["tags"] or [],
                extra_params=cfg["extra_params"] or None,
                first_role=cfg["first_role"] or None,
                last_role=_effective_last(cfg),
            )
