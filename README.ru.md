# KimoDer — Kimodo+Cascadeur Portable

Портативный установщик в один клик для модели диффузии движения [Kimodo](https://github.com/NVlabs/kimodo) с интеграцией Cascadeur. **Без Docker, без WSL, без облака.** Весь рантайм внутри одной папки.

## Быстрый старт

```powershell
# Первый запуск — полная установка (~12 ГБ загрузок)
.\Install_KimoDer-UV.ps1 -Install

# Ежедневное использование — панель управления (GUI)
.\Run_KimoDer.ps1
```

## Панель управления (GUI)

Две секции с индикаторами состояния для каждого сервиса:

- **Cascadeur BackEnd** (порт 9552) — цветной индикатор-круг (серый=выключен, жёлтый=прогрев, зелёный=готов, синий=занят, красный=ошибка), кнопки Start/Stop для LLAMA NF4 и LLAMA OFF, отображение связи с Cascadeur
- **Kimodo Viser** — цветной индикатор-круг (серый=остановлен, жёлтый=загрузка, зелёный=готов), кнопки Start/Stop Viser, Log Folder
- **Живой лог** — консоль + лог-область GUI с переносом по словам, теги `[Cascadeur BackEnd]`, `[Kimodo Viser]`, `[GUI]` и символы типов (`!` ошибка, `*` предупр., `+` ок, `.` статус, `>` действие). Лог динамически перестраивается при изменении размеров окна.
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
2. Из GUI или CLI: `-InstallCascadeurCommand` (запросит путь к Cascadeur)
3. Запустите бэкенд (кнопка в GUI или `-StartBackend`)
4. В Cascadeur: **Animation Scripts → Kimodo Roundtrip**

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
