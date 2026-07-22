# KimoDer — Kimodo+Cascadeur Portable

Портативный установщик в один клик для модели диффузии движения [Kimodo](https://github.com/NVlabs/kimodo) с интеграцией Cascadeur. **Без Docker, без WSL, без облака.** Весь рантайм внутри одной папки.

## Что такое KimoDer?

KimoDer объединяет две независимые технологии в единый портативный конвейер:

| Компонент | Что делает |
|-----------|-----------|
| **[Kimodo](https://github.com/NVlabs/kimodo)** | Диффузионная модель NVIDIA для генерации движений. Принимает текстовое описание («человек перепрыгивает препятствие») и генерирует скелетную анимацию всего тела. Работает на локальной GPU, без облака. |
| **Text encoder** | Собственный 4-битный NF4-энкодер: [`Aero-Ex/KIMODO-Meta3_llm2vec_NF4`](https://huggingface.co/Aero-Ex/KIMODO-Meta3_llm2vec_NF4) — **~3× легче** стандартной сборки LLM2Vec, помещается в **8 ГБ VRAM**. Оригинальные сборки требовали 17–20 ГБ (LLAMA полная) или до 10 ГБ (LLAMA 8-bit + CPU offload). |
| **[Cascadeur](https://cascadeur.com/)** | Профессиональный инструмент 3D-анимации персонажей с физически-ассистированным позированием и API для Python-скриптов. Индустриальный стандарт для ключевой анимации. **Не входит в пакет** — его нужно скачать отдельно. |
### Зачем их объединили?

- **Kimodo отдельно** выдаёт FBX-файл — но его нельзя увидеть в контексте или отредактировать, не выходя из инструментария.
- **Cascadeur отдельно** отличен для ручной анимации, но не имеет ИИ-генерации движений.

С KimoDer вы пишете промпт, нажимаете «Generate», и анимация появляется **прямо на таймлайне Cascadeur** на скелете SOMA-77 — готовая к правкам, ретаргетингу или экспорту.

> **Важно:** перед генерацией необходимо **выделить временной диапазон между двумя ключевыми кадрами** на таймлайне Cascadeur — иначе инференс не запустится. Скрипт заполняет выделенный интервал сгенерированным движением.

### Требования

- **Cascadeur 2026+** — совместимость скелетов между Kimodo и Cascadeur основана на риге SOMA-77, введённом в Cascadeur 2024; полная поддержка roundtrip требует версии 2026+.
- **Платная версия** — бесплатная редакция Cascadeur **не включает ретаргетинг**, поэтому скрипт Kimodo Roundtrip не будет работать. Требуется лицензия Pro или Business.

### Как используется в проектах

| Сценарий | Процесс |
|----------|---------|
| **Прототипирование игр** | Описать действие NPC («стоит, осматривается») → выделить диапазон на таймлайне → сгенерировать → подправить тайминг в Cascadeur → экспортировать FBX в движок |
| **Превиз для кино / VFX** | Сгенерировать черновой дубль из текста за секунды, затем доработать ключевыми кадрами в Cascadeur |
| **Независимая анимация** | Не нужен mocap-костюм — опишите нужное движение, получите физически правдоподобную основу, отполируйте вручную |
| **Итерационный цикл** | Сгенерировать → отредактировать в Cascadeur → подать обратно для нового прохода диффузии (с учётом ограничений) |

### Как устроен конвейер

```
Текстовый промпт ——> Диффузионная модель Kimodo ——> скелетная анимация
                         ↑                              ↓
                    LLAMA text encoder           Cascadeur BackEnd
                    (текст → embedding)          (HTTP-сервер, порт 9552)
                                                      ↓
                                                Плагин Cascadeur
                                              (Kimodo Roundtrip)
                                                      ↓
                                         [1] Выделить диапазон на таймлайне
                                         [2] Нажать Generate
                                                      ↓
                                           Редактируемая анимация в Cascadeur
```

Всё работает внутри одной портативной папки. Без Docker, без WSL, без облачного GPU. Бэкенд использует локальный LLAMA-текстовый энкодер (или облегчённый хеш-фолбек для экономии VRAM), а диффузионная модель исполняется целиком на вашей NVIDIA GPU.

## Быстрый старт

```powershell
# Первый запуск — полная установка (~12 ГБ загрузок)
.\Install_KimoDer-UV.ps1 -Install

# Ежедневное использование — панель управления (GUI)
.\Run_KimoDer.ps1
```

## Панель управления (GUI)

![GUI KimoDer с запущенными бэкендом и визером](bin/res/pintura_001.png)

Две секции с индикаторами состояния для каждого сервиса, плюс строка системной нагрузки:

- **Строка нагрузки** — `GPU <%> VRAM: X/YGb || RAM <%> X/YGb`, оранжевые метки GPU/RAM, обновление каждые 3 с
- **Cascadeur BackEnd** (порт 9552) — цветной индикатор-круг (серый=выключен, жёлтый=прогрев, зелёный=готов, синий=занят, красный=ошибка), кнопки Start/Stop для LLAMA NF4 и LLAMA OFF, отображение связи с Cascadeur
- **Kimodo Viser** — цветной индикатор-круг (серый=остановлен, жёлтый=загрузка, зелёный=готов), порт отображается в заголовке секции во время работы, кнопки Start/Stop Viser, Log Folder и **Open Viser** — разблокируется (зелёный текст) когда визер готов и открывает веб-интерфейс в браузере. Готовность определяется по строке `listening` в логе визера с HTTP-проверкой — без ложного «ready» до реальной готовности сервера (таймаут запуска до 8 мин)
- **Живой лог** — консоль + лог-область GUI с переносом по словам, теги `[Cascadeur BackEnd]`, `[Kimodo Viser]`, `[GUI]` и символы типов (`!` ошибка, `*` предупр., `+` ок, `.` статус, `>` действие). Лог динамически перестраивается при изменении размеров окна. Чекбокс **Auto-scroll** включает/выключает следование за новыми строками
- **Тултипы** — каждая кнопка объясняет своё действие при наведении
- **Дисциплина процессов** — закрытие GUI запускает graceful shutdown: останов демо, останов бэкенда, зачистка всех зомби-процессов Python из venv

## CLI-команды

```powershell
.\Install_KimoDer-UV.ps1 -Install              # Неинтерактивная полная установка
.\Install_KimoDer-UV.ps1 -Reinstall            # Полная переустановка
.\Run_KimoDer.ps1 -StartBackend llama          # Запуск бэкенда (LLAMA NF4)
.\Run_KimoDer.ps1 -StartBackend fallback       # Запуск бэкенда (LLAMA OFF)
.\Run_KimoDer.ps1 -StopBackend                 # Останов бэкенда
.\Run_KimoDer.ps1 -CheckBackend                # Проверка здоровья (JSON)
.\Run_KimoDer.ps1 -StartDemo                   # Запуск веб-демо
.\Run_KimoDer.ps1 -InstallCascadeurCommand -CascadeurRoot "путь"

# Прямое управление бэкендом:
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py start --profile llama --watch
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py start-demo --watch
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py health --json
.\kimodo_env\Scripts\python.exe scripts\backend_ctl.py stop
```

## Требования

- Windows 10/11, PowerShell 5.1+
- NVIDIA GPU с 8+ ГБ VRAM (RTX 3060+)
- Git
- [Cascadeur](https://cascadeur.com/) (опционально, для roundtrip анимации)

## Интеграция с Cascadeur

1. Установите Cascadeur отдельно
2. После установки среды установщик **предложит установить Cascadeur Command сразу** (Y/n) — согласитесь, или отложите и запустите позже через пункт 3 меню установщика (`Install Cascadeur Command`)
3. Запустите GUI (`.\Run_KimoDer.ps1`) и нажмите **Start (LLAMA NF4)**
4. В Cascadeur: **Animation Scripts → Kimodo Roundtrip**

![Roundtrip в действии из Cascadeur](bin/res/cascadeur_animationen.gif)

Если папка Repository была перемещена, перезапустите `scripts\install_cascadeur_command.ps1` для обновления путей.

## Модельный стек

- **Диффузия:** `nvidia/Kimodo-SOMA-RP-v1` (SOMA-77, Retargeting Preset), доступен SEED-вариант через выбор датасета
- **Текст-энкодер:** `Aero-Ex/KIMODO-Meta3_llm2vec_NF4` (слитая 4-битная NF4) — внутри процесса с оффлоудом через memory manager; опциональный `HashTextEncoder` (режим LLAMA OFF, ~0 VRAM)
- **Скелет:** SOMA-77 (Cascadeur SOMA rig)
- Кастомные чекпоинты поддерживаются через переменную `CHECKPOINT_DIR`

## Структура

```
Repository/
├── Install_KimoDer-UV.ps1       # AIO установщик (окружение + модели + гибрид)
├── Run_KimoDer.ps1              # Запуск GUI / CLI-рантайм
├── _hf_pycurl_download.py       # Загрузчик моделей HF (pycurl)
├── _llm2vec_wrapper_template.py
├── bin/uv.exe, bin/uvx.exe      # uv-менеджер пакетов
│   └── res/                     # Шрифты ModeSeven
├── integrations/cascadeur/      # Файлы плагина Cascadeur
├── kimodo_addons/               # Вливается в kimodo/ при установке
├── scripts/
│   ├── kimoder_gui.py           # Панель управления DearPyGui
│   ├── backend_ctl.py           # Жизненный цикл бэкенда + демо (CLI + модуль)
│   ├── install_cascadeur_command.ps1  # копирует плагин в Cascadeur
│   └── cascadeur_backend_service.py   # HTTP-бэкенд (порт 9552)
└── tools/io_scene_fbx/          # Модули Blender FBX (только Python)
```

## Авторство

- Kimodo: [NVIDIA Research](https://research.nvidia.com/labs/sil/projects/kimodo/)
- Портативный лаунчер и интеграция Cascadeur: [Soror L.'.L.'.](https://github.com/Methelina/KimoDer_portable)
- Работа вдохновлена скриптами Anoxxy и его WSL/Linux/Ubuntu гибридом: [видео](https://youtu.be/yu2X-zS840A)
