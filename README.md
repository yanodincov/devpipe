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
+-- devpipe -----------------------------------------+
| task          <- required                          |
| task-id       MRC-123        (from git branch)     |
| runner        codex                                 |
| target-branch u1                                    |
| service       acquiring                             |
| namespace     auto                                  |
| tags          acquiring-service, go                |
|   dataset     s4-3ds                               |
| roles         architect -> qa_stand                 |
+----------------------------------------------------+
```

- **task-id** — подставляется автоматически из ветки (`MRC-123-my-feature` → `MRC-123`). Если указан — загружается контекст из Jira. Можно очистить чтобы пропустить Jira.
- **target-branch** — стенд для деплоя. Если не указан — пайплайн останавливается на `qa_local`.
- **tags** — список с множественным выбором. Параметры активных тегов появляются отдельными пунктами меню.
- **first role / last role** — диапазон ограничен, невалидный выбрать нельзя.
- **Run** — появляется только когда `task` заполнен.

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

## Профили (pipeline.yml)

Профили определяют структуру пайплайна: входные параметры, стадии выполнения и роутинг между ними. Профили хранятся в `.devpipe/profiles/<name>/pipeline.yml`.

### Структура профиля

```yaml
version: 1
name: my-pipeline

defaults:
  runner: auto
  model: middle
  effort: middle

inputs:
  task:
    type: string
    required: true
    default: ""
    custom: true
  count:
    type: int
    default: 1
    values: [1, 2, 3]
    custom: false

stages:
  build:
    runner: codex
    model: high
    effort: middle
    retry_limit: 2
    agent:
      folder: builder
    in:
      task: input.task
      config: context.config
    out:
      artifacts:
        type: object

routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: test
          default: true
    test:
      next_stages:
        - stage: completed
          default: true
```

---

### version

Обязательное поле. Версия формата профиля. На данный момент поддерживается только `version: 1`.

---

### name

Имя профиля. Используется для отображения и логирования.

---

### defaults

Глобальные настройки по умолчанию для всех стадий.

| Поле | Тип | Описание |
|------|-----|----------|
| `runner` | string | Раннер: `auto`, `codex`, `claude` |
| `model` | string | Модель: `auto`, `low`, `middle`, `medium`, `high` |
| `effort` | string | Усилия: `auto`, `low`, `middle`, `medium`, `high` |

---

### inputs

Входные параметры пайплайна. Определяют поля, которые пользователь заполняет в TUI перед запуском.

```yaml
inputs:
  my_field:
    type: string          # string, int, bool, object, array
    required: true        # обязательное поле
    default: ""           # значение по умолчанию
    values: [a, b, c]     # допустимые значения (опционально)
    multi: false          # множественный выбор (опционально)
    custom: true          # разрешить произвольные значения (опционально)
```

#### Типы полей

| Тип | Описание |
|-----|----------|
| `string` | Строка |
| `int` | Целое число |
| `bool` | Булево значение (`true`/`false`) |
| `object` | JSON-объект |
| `array` | Массив |

#### Валидация входных полей

- `required: true` — поле обязательно для заполнения
- `default` — если `custom: false` и есть `values`, значение должно быть из списка
- `multi: false` — `default` не может быть списком `[]`
- `multi: true` — `default` должен быть списком (пустым или с значениями из `values`)
- Имена `runner`, `profile`, `first_role`, `last_role`, `model`, `effort` зарезервированы

#### Примеры

```yaml
# Простое строковое поле с произвольным вводом
task:
  type: string
  required: true
  default: ""
  custom: true

# Выбор из списка
environment:
  type: string
  default: "dev"
  values: ["dev", "staging", "prod"]
  custom: false

# Множественный выбор
services:
  type: string
  multi: true
  default: []
  values: ["api", "web", "worker"]
  custom: true

# Целое число
count:
  type: int
  default: 1
  values: [1, 2, 3, 5]
  custom: true

# Булево значение
dry_run:
  type: bool
  default: false
```

---

### stages

Определяет стадии выполнения пайплайна. Каждая стадия — это запуск AI-агента с определённым промптом.

```yaml
stages:
  <stage_name>:
    runner: codex            # раннер (auto, codex, claude)
    model: high              # модель (auto, low, middle, medium, high)
    effort: middle           # усилия (auto, low, middle, medium, high)
    retry_limit: 2           # лимит повторных попыток (>= 0, целое число)
    tags: [go, backend]      # теги для правил (опционально)
    agent:                   # спецификация агента
      folder: builder        # имя папки в agents/ (опционально)
      # ИЛИ
      prompt: path/to/prompt.md
      schema: path/to/schema.json
    in:                      # входные данные
      task: input.task
      artifacts: stage.build.out.artifacts
    out:                     # выходные данные
      result:
        type: object
```

#### Поля стадии

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| `runner` | string | да | Раннер: `auto`, `codex`, `claude` |
| `model` | string | нет | Модель: `auto`, `low`, `middle`, `medium`, `high` |
| `effort` | string | нет | Усилия: `auto`, `low`, `middle`, `medium`, `high` |
| `retry_limit` | int | нет | Лимит повторов (>= 0, целое). По умолчанию 1 |
| `tags` | list | нет | Список тегов для правил |
| `agent` | object | нет | Спецификация агента (см. ниже) |
| `in` | dict | нет | Входные привязки |
| `out` | dict | нет | Выходные поля |

#### Спецификация агента (agent)

Агент определяет промпт и схему выходных данных. Два формата:

**Формат 1: folder** — загружает файлы из `agents/<folder>/`
```yaml
agent:
  folder: builder    # ищет agents/builder/prompt.md и agents/builder/output.schema.json
```

**Формат 2: prompt + schema** — явные пути к файлам
```yaml
agent:
  prompt: agents/builder/prompt.md
  schema: agents/builder/output.schema.json
```

Валидация:
- Обязательны либо `folder`, либо оба `prompt` и `schema`
- Файлы должны существовать
- `output.schema.json` должен быть валидным JSON

#### Входные привязки (in)

Связывают входные данные стадии с источниками:

```yaml
in:
  task: input.task                              # из inputs
  config: context.config                        # из контекста
  artifacts: stage.build.out.artifacts          # из выхода другой стадии
  branch: runtime.git.current_branch             # из runtime
```

Форматы:
- `input.<field>` — значение из inputs
- `context.<field>` — значение из контекста
- `stage.<name>.out.<field>` — выходное поле другой стадии
- `runtime.<source>.<field>` — runtime-значение
- `integration.<service>.<field>` — интеграционные данные

Условные выражения:
```yaml
plan: stage.fix.out.updated_plan if stage.fix.out.changes_made else stage.init.out.initial_plan
```

#### Выходные поля (out)

Определяют структуру выходных данных стадии:

```yaml
out:
  result:
    type: object
    properties:
      status:
        type: string
      count:
        type: int
```

Рекомендуется определять `properties` для типа `object`.

---

### routing

Определяет порядок выполнения стадий и переходы между ними.

```yaml
routing:
  start_stage: build
  by_stage:
    build:
      next_stages:
        - stage: test
          default: true
    test:
      next_stages:
        - stage: deploy
          all:
            - field: out.passed
              op: eq
              value: true
        - stage: failed
          default: true
```

#### start_stage

Обязательное поле. Имя первой стадии пайплайна.

#### by_stage

Определяет переходы для каждой стадии. Каждая стадия может иметь несколько возможных следующих стадий с условиями.

```yaml
by_stage:
  <stage_name>:
    next_stages:
      - stage: <target_stage>
        default: true      # переход по умолчанию
      - stage: <target>
        all: [...]         # переход если ALL условия истинны
      - stage: <target>
        any: [...]         # переход если ANY условие истинно
```

#### Условия перехода

Каждое условие проверяет поле выхода текущей стадии:

```yaml
all:
  - field: out.passed
    op: eq
    value: true
  - field: out.count
    op: gt
    value: 0
```

| Оператор | Описание |
|---------|----------|
| `eq` | равно |
| `ne` | не равно |
| `gt` | больше |
| `gte` | больше или равно |
| `lt` | меньше |
| `lte` | меньше или равно |
| `in` | значение в списке |
| `contains` | строка содержит значение |

В условиях можно ссылаться на:
- `out.<field>` — выходное поле текущей стадии
- `input.<field>` — входной параметр пайплайна

#### Системные стадии

- `completed` — успешное завершение пайплайна
- `failed` — ошибка выполнения

Обязательно должен быть путь от `start_stage` до `completed`.

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
