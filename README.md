# devpipe

AI-агент оркестратор для автоматизации цикла разработки. Запускает шесть ролей последовательно, каждую выполняет Codex или Claude по заданным промптам и правилам.

```
architect → developer → test_developer → qa_local → release → qa_stand
```

---

## Установка

```bash
mise install        # устанавливает python 3.13
mise run install    # создаёт .venv и устанавливает зависимости
```

Без mise:
```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

---

## Запуск

```bash
devpipe          # интерактивное TUI — основной и единственный режим
mise run         # то же самое, если настроен mise
```

**Примечание:** devpipe можно запускать в любой директории. При отсутствии локальной конфигурации `.devpipe/` в проекте, приложение будет использовать глобальные профили из `~/.devpipe/profiles/`.

### Глобальные профили

Чтобы использовать devpipe без привязки к конкретному проекту, создайте профили в `~/.devpipe/profiles/`:

```bash
mkdir -p ~/.devpipe/profiles/<profile_name>/
# Скопируйте pipeline.yaml/yml и опционально agents/ из существующего проекта
```

Можно также задать глобальный профиль по умолчанию через `~/.devpipe/config.yaml`:

```yaml
defaults:
  profile: my-global-profile
```

---

## Интерактивное меню

```
┌─ devpipe ─────────────────────────────────────┐
│  task          ← required                     │
│  task-id       MRC-123        (из ветки git)  │
│  runner        codex                          │
│  target-branch u1                             │
│  service       acquiring                      │
│  namespace     auto                           │
│  tags          acquiring-service, go          │
│    dataset     s4-3ds                         │
│  roles         architect → qa_stand           │
└───────────────────────────────────────────────┘
```

- **task-id** — подставляется автоматически из ветки (`MRC-123-my-feature` → `MRC-123`). Если указан — загружается контекст из Jira. Можно очистить чтобы пропустить Jira.
- **target-branch** — стенд для деплоя. Если не указан — пайплайн останавливается на `qa_local`.
- **tags** — список с множественным выбором. Параметры активных тегов появляются отдельными пунктами меню.
- **first role / last role** — диапазон ограничен, невалидный выбрать нельзя.
- **▶ Run** — появляется только когда `task` заполнен.

---


## Настройка проекта (.devpipe/)

Создай `.devpipe/` в корне **рабочего репозитория** (не в devpipe). Именно оттуда devpipe читает конфигурацию при запуске.

### config.yaml

```yaml
defaults:
  runner: codex
  service: my-service
  tags:
    - my-service          # проектный тег
    - go                  # builtin тег

available:
  target_branch:          # список для выбора в TUI
    - u1
    - u1-1
  namespace:
    - my-service-u1
    - my-service-u1-1
```

- `defaults` — начальные значения в TUI
- `available` — если список заполнен, в TUI будет выпадашка; если пуст — свободный ввод

### tags/

Кастомные теги проекта. Та же структура что и builtin `tags/` в этом репозитории.

```
.devpipe/
  config.yaml
  tags/
    my-service/
      architect/
        rules.md
      developer/
        rules.md
      test_developer/
        rules.md
      qa_local/
        rules.md
      release/
        rules.md
      qa_stand/
        rules.md
        params.yaml       # параметры нужные qa_stand (опционально)
```

Каждый файл `rules.md` дописывается к промпту соответствующей роли когда тег активен.

---

## Теги

### Как работают

При запуске роли devpipe собирает промпт так:

```
<базовый промпт роли>

## Tag Rules: my-service
<содержимое .devpipe/tags/my-service/<role>/rules.md>

## Tag Rules: go
<содержимое tags/go/<role>/rules.md>
```

Порядок поиска `rules.md` для тега:
1. `.devpipe/tags/<tag>/<role>/rules.md` — кастомные теги проекта
2. `tags/<tag>/<role>/rules.md` — builtin теги devpipe

### params.yaml — параметры для роли

Если роли нужны входные данные (например `dataset` для qa_stand), объяви их в `params.yaml` рядом с `rules.md`:

```yaml
# .devpipe/tags/my-service/qa_stand/params.yaml
params:
  - key: dataset
    description: Test dataset
    required: true
    available:
      - s4-3ds
      - s4-no3ds
```

При запуске:
- TUI покажет `Set dataset` как отдельный пункт меню
- Выбранное значение попадёт в `release_context` который AI видит в промпте
- В `rules.md` можно ссылаться на него: `{release_context.dataset}`

### Builtin теги

| Тег | Роли |
|-----|------|
| `go` | `developer`, `test_developer` |

### Управление тегами (новый интерфейс)

В Textual интерфейсе поле **Tags** теперь позволяет выбирать теги и настраивать, на каких этапах пайплайна они активны:

1. Выберите **Tags** в меню и нажмите Enter.
2. Вы увидите список всех доступных тегов.
   - **○** — тег не выбран.
   - **●** — тег выбран и активен на одной или нескольких ролях.
   - Нажмите **Space**, чтобы выбрать/снять тег.
   - Нажмите **Enter** на теге, чтобы открыть настройку ролей, на которых тег будет применён.
3. В экране ролей:
   - **↑↓** — навигация.
   - **Enter** — включить/выключить роль для этого тега.
   - **Esc** — вернуться к списку тегов.
4. После настройки всех тегов нажмите **Esc** в основном списке тегов, чтобы применить изменения и выйти.

При изменении диапазона этапов (Start Stage / Finish Stage) или выборе тегов, система автоматически пересчитывает параметры, специфичные для тегов (например, `dataset`), и добавляет соответствующие поля в форму.

---

## Пример: acquiring

```
acquiring-repo/
  .devpipe/
    config.yaml
    tags/
      acquiring-service/
        architect/rules.md
        developer/rules.md
        test_developer/rules.md
        qa_local/rules.md
        release/rules.md
        qa_stand/
          rules.md        ← инструкции по pw-exchange-buy
          params.yaml     ← dataset param
```

`config.yaml`:
```yaml
defaults:
  runner: codex
  service: acquiring
  tags:
    - acquiring-service
    - go

available:
  target_branch:
    - u1
    - u1-1
    - u1-4
  namespace:
    - acquiring-u1
    - acquiring-u1-1
    - acquiring-u1-4
```

---

## Структура репозитория

```
devpipe/
├── roles/              # базовые промпты и схемы вывода для каждой роли
│   └── <role>/
│       ├── prompt.md
│       ├── role.yaml
│       └── output.schema.json
├── tags/               # builtin теги (универсальные, не проектные)
│   └── go/
│       ├── developer/rules.md
│       └── test_developer/rules.md
├── config/
│   └── runners.yaml        # настройки runners: команда, timeout, model/effort mapping
└── src/devpipe/
    ├── cli.py
    ├── tui.py              # интерактивное меню
    ├── app.py              # RunConfig, OrchestratorApp
    ├── tags.py             # загрузка тегов и params.yaml
    ├── project_config.py   # загрузка .devpipe/config.yaml
    ├── runtime/            # state machine, события, retry
    ├── roles/              # загрузка ролей, сборка промптов
    ├── runners/            # Codex и Claude адаптеры
    ├── integrations/       # Jira, GitHub, Kubernetes, Git
    └── storage/            # логи и артефакты запусков
```
