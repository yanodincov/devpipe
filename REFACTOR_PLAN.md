# План рефакторинга: переход на profiles + agents + tags + YAML история

## Цель
Полностью убрать `roles/`, заменить на новую систему:
- `profiles/` с routing-based pipeline.yml
- `agents/` внутри профилей (вместо roles)
- `tags/` как доп. контекст для этапов
- Хранение истории запусков в `.devpipe.yml` файлах

---

## 1. Удаление `roles/` и переход на agents

### 1.1 Удалить папку `roles/`
```bash
rm -rf roles
```

### 1.2 Обновить ядро приложения (`src/devpipe/app.py`)
**Текущее:**
- Использует `RoleDefinition` из `roles/loader.py`
- Загружает роли из `roles/` папки

**Новое:**
- Роли заменяются на этапы (stages) из активного профиля
- Каждый `StageSpec` содержит:
  - `name`
  - `runner`, `model`, `effort`, `retry_limit`
  - `in` (binding из context/data)
  - `out` (output fields)
  - `agent` (опционально: prompt + output_schema)

**Изменения:**
- Убрать импорт `RoleDefinition, load_roles`
- Убрать `self.roles = roles` из `OrchestratorApp.__init__`
- В `run_pipeline`:
  - Получать `profile = load_profile(config.profile)`
  - Получать `stage_spec = profile.stages[state.current_stage]`
  - Использовать `stage_spec.runner` (или `config.runner` если `auto`)
  - Создавать envelope на основе `stage_spec`, а не `RoleDefinition`
- `build_default_app`:
  - Убрать `load_roles(base / "roles")`
  - Профили и stage specs загружаются динамически через `load_profile()`

### 1.3 Переименовать `src/devpipe/roles/envelope.py` → `src/devpipe/profiles/agent.py`
**Новый модуль отвечает за:**
- `build_stage_envelope(stage_spec, state, config, tag_prompts)` → `TaskEnvelope`
- `compose_instructions(base_prompt, stage_name, project_root, tag_prompts)`
- Tag-промпты подгружаются из `.devpipe/tags/` и `~/.devpipe/tags/`

---

## 2. Добавить tags поддержку в профилях

### 2.1 Расширить `StageSpec` (`src/devpipe/profiles/stages.py`)
```python
class StageSpec(BaseModel):
    ...
    tags: list[str] = Field(default_factory=list)  # список tag-контекстов для этапа
```

### 2.2 Обновить парсер `loader.py`
При парсинге stage_data извлекать `tags` (если есть) и добавлять в StageSpec.

### 2.3 Создать `src/devpipe/tags/loader.py` (или обновить существующий `tags.py`)
```python
BUILTIN_TAGS_DIR = Path(__file__).resolve().parents[2] / "tags"

def load_available_tags(project_root: Path) -> list[str]:
    """Return sorted list of tag names from local + global."""
    local = project_root / ".devpipe" / "tags"
    global_dir = Path.home() / ".devpipe" / "tags"
    tags = set()
    for base in [local, global_dir]:
        if base.exists():
            tags.update(p.name for p in base.iterdir() if p.is_dir())
    return sorted(tags)

def get_tag_prompt(tag_name: str, project_root: Path) -> str:
    """Read prompt.md for tag from local or global dir."""
    local_path = project_root / ".devpipe" / "tags" / tag_name / "prompt.md"
    global_path = Path.home() / ".devpipe" / "tags" / tag_name / "prompt.md"
    path = local_path if local_path.exists() else global_path
    return path.read_text(encoding="utf-8") if path.exists() else ""
```

### 2.4 Обновить `agent.py`
```python
def compose_stage_instructions(
    stage_spec: StageSpec,
    project_root: Path,
    tag_names: list[str] | None = None,
) -> str:
    base = stage_spec.agent.prompt if stage_spec.agent else ""
    tag_sections = []
    for tag in tag_names or []:
        prompt = get_tag_prompt(tag, project_root)
        if prompt:
            tag_sections.append(f"## Tag: {tag}\n\n{prompt}")
    return base + ("\n\n" + "\n\n".join(tag_sections) if tag_sections else "")
```

### 2.5 Обновить UI (`src/devpipe/ui/services.py`)
- В `load_profile_fields` для поля `tags` (если `InputSpec.type == "array"` и `multi=True`) задать `options = load_available_tags(project_root)`
- В `prepare_initial_state` добавить `available_tags` в возвращаемый словарь
- В состоянии формы добавить поле `tags: []` (multi-select)

---

## 3. Сохранение истории запусков в `.devpipe.yml`

### 3.1 Формат файла
Каждый запуск сохраняется как: `runs/<iso_timestamp>.devpipe.yml`

```yaml
run_id: "2026-03-29T15-30-45.123456"  # filename without extension
timestamp: "2026-03-29T15:30:45.123456Z"
profile: "current-delivery"
config:
  task: "Implement feature X"
  task_id: "PROJ-123"
  runner: "auto"
  model: "auto"
  effort: "auto"
  tags: ["security", "performance"]
  # все остальные поля из inputs (включая extra_params, target_branch и т.д.)
stages:
  - name: architect
    started_at: "2026-03-29T15:30:46Z"
    completed_at: "2026-03-29T15:35:12Z"
    status: "completed"
    output:
      architecture_plan: { ... }
  - name: developer
    started_at: "2026-03-29T15:35:13Z"
    completed_at: "2026-03-29T15:45:30Z"
    status: "completed"
    output:
      code_changes: { ... }
    attempts:
      - started_at: "2026-03-29T15:35:13Z"
        completed_at: "2026-03-29T15:42:00Z"
        status: "completed"
        output: { ... }
      - ...
summary:
  total_duration_seconds: 885.3
  stages_completed: 4
  stages_failed: 0
  final_status: "completed"
```

### 3.2 Создать `src/devpipe/history.py`
```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import yaml

@dataclass
class StageRun:
    name: str
    started_at: datetime
    completed_at: datetime | None
    status: str  # completed, failed, cancelled
    output: dict
    attempts: list[dict] = field(default_factory=list)

@dataclass
class RunHistoryEntry:
    run_id: str
    timestamp: datetime
    profile: str
    config: dict
    stages: list[StageRun]
    summary: dict

    def to_yaml_dict(self) -> dict:
        data = asdict(self)
        # serialise datetime to iso
        return data

    @classmethod
    def from_yaml_dict(cls, data: dict) -> RunHistoryEntry:
        # parse iso strings to datetime
        return cls(**data)

def save_run_history(entry: RunHistoryEntry, runs_dir: Path):
    runs_dir.mkdir(parents=True, exist_ok=True)
    file_path = runs_dir / f"{entry.run_id}.devpipe.yml"
    yaml.dump(entry.to_yaml_dict(), file_path, default_flow_style=False, sort_keys=False)

def load_run_history(runs_dir: Path) -> list[RunHistoryEntry]:
    entries = []
    if not runs_dir.exists():
        return entries
    for yaml_file in runs_dir.glob("*.devpipe.yml"):
        data = yaml.safe_load(yaml_file)
        entries.append(RunHistoryEntry.from_yaml_dict(data))
    return sorted(entries, key=lambda e: e.timestamp, reverse=True)
```

### 3.3 Интегрировать в `src/devpipe/app.py`
В `OrchestratorApp.run_pipeline`:
- В начале: `run_id = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S.%f")`
- Логировать события (stage started/completed) + собирать список `stages` с попытками
- После завершения (или в `finally`):
  - Собрать `RunHistoryEntry` из `config`, `stages_execution_data`, `summary`
  - `save_run_history(entry, self.runs_dir)`

### 3.4 Обновить UI HistoryScreen (`src/devpipe/ui/history_screen.py`)
- Загружать список записей через `load_run_history(runs_dir)`
- При выборе записи — читать файл и показывать детали (config, stage outputs)

---

## 4. Дополнительные правки

### 4.1 Обновить тесты profiles
- Добавить `tags` в примеры профилей
- Проверить валидацию `StageSpec` с `tags` и `agent`

### 4.2 Обновить `prepare_initial_state` (`src/devpipe/ui/services.py`)
- Добавить `available_tags` от `load_available_tags(project_root)`
- Возвращать в словаре состояния

### 4.3 Убедиться, что `StageSpec.agent` опционален
-允许 запуска без агента (просто runner)
- В UI не показывать agent-специфичные поля, если agent не задан

### 4.4 Конфиг runner profiles
`config/runners.yaml` оставить как есть, но убрать dependency от `profile_map` если не используется.

---

## 5. Порядок реализации (рекомендуемый)

### Этап 1: Убрать roles
1. Удалить папку `roles/`
2. Создать `src/devpipe/profiles/agent.py` (копия envelope.py + адаптация)
3. Переделать `src/devpipe/app.py` на использование `StageSpec` и `build_stage_envelope`
4. Протестировать на simplest `test-simple` профиле (без agent)
5. Добавить `agent` в `current-delivery` профиль (копируя промпты из старых roles)

### Этап 2: Tags поддержка
1. Добавить `tags` в `StageSpec`
2. Создать/обновить `tags/loader.py`
3. Обновить `agent.py` для включения tag prompts
4. Обновить `prepare_initial_state` и `load_profile_fields` в UI
5. Добавить tags в `current-delivery` профиль для этапов, которые нуждаются в контексте тегов

### Этап 3: История в YAML
1. Создать `src/devpipe/history.py`
2. Интегрировать в `app.py` (сбор данных при run, сохранение)
3. Обновить `history_screen.py` для отображения записей из `.devpipe.yml` файлов
4. Добавить кнопку "Export" в UI для сохранения текущего конфига как `.devpipe.yml`

### Этап 4: Очистка и тесты
1. Удалить `src/devpipe/profiles/test-feedback` и `test-simple` из `src/` (они уже в `.devpipe/profiles/`)
2. Обновить все тесты под новую логику
3. Проверить, что все 194+ теста проходят
4. Обновить `pyproject.toml` если нужно

---

## 6. Вопросы для утверждения

1. **История:** хранить в `runs/<timestamp>.devpipe.yml` — согласны?
2. **Tags applicability:** tag применяется ко всем stages, на которые указан в StageSpec.tags — верно?
3. **Agent опционален:** stage без agent запускается с пустым prompt (только системный)? Или agent обязателен?
4. **Конфиг импорт:** UI должен уметь читать `.devpipe.yml` и populate форму — нужно?

---

## 7. Файлы для изменения

### Core
- `src/devpipe/app.py` — убрать roles, использовать profile.stages
- `src/devpipe/profiles/__init__.py` (существует)
- `src/devpipe/profiles/loader.py` (существует)
- `src/devpipe/profiles/stages.py` — добавить `tags`, `agent`
- `src/devpipe/profiles/agent.py` — новый (из envelope)
- `src/devpipe/tags/loader.py` — новый или обновить `tags.py`

### UI
- `src/devpipe/ui/services.py` — добавить available_tags, load_profile_fields для tags
- `src/devpipe/ui/history_screen.py` — переделать под YAML историю
- `src/devpipe/ui/app.py` — интеграция (если нужно)

### Tests
- Обновить `tests/profiles/*`
- Обновить `tests/ui/*`
- Добавить тесты на tags и историю

### Data
- Удалить `roles/`
- Удалить `docs/superpowers/plans/` (уже удалён)
- Переместить тестовые профили в `.devpipe/profiles/` (уже сделано)

---

**Готов приступить к реализации после утверждения плана.**
