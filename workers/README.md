# TBPR2

Локальное Python-приложение (PyQt6) для торговли ценными бумагами на Московской бирже через T-Invest API.

## Структура проекта

```
TBPR2/
├── main.py              # Точка входа приложения
├── requirements.txt     # Зависимости Python
├── README.md           # Этот файл
├── .gitignore          # Игнорируемые файлы
├── app/                # Модуль главного окна
│   ├── __init__.py
│   ├── config.py       # Конфигурация и токен
│   ├── main_window.py  # Главное окно с вкладками
│   └── tinvest_client.py # Клиент T-Invest
├── core/               # Бизнес-логика (без PyQt)
│   ├── __init__.py
│   ├── instruments_catalog.py  # Каталог инструментов
│   ├── trading_logic.py        # Логика торговли
│   ├── candle_storage.py       # Хранение свечей
│   ├── candle_cache.py         # Кэш свечей
│   ├── favorites_repo.py       # Избранное
│   ├── backtest_runner.py      # Запуск стратегий
│   ├── dividends_api.py        # API дивидендов
│   ├── dividends_calc.py       # Расчёт дивидендов
│   ├── strategies/     # Торговые стратегии
│   │   ├── base.py
│   │   ├── grid_basic.py
│   │   ├── grid_basic_div.py
│   │   ├── buy_hold_div.py
│   │   └── sma_cross.py
│   └── robots/         # Торговые роботы
│       ├── base.py
│       ├── grid_simple.py
│       └── repository.py
├── tabs/               # Вкладки интерфейса
│   ├── __init__.py
│   ├── trading_context.py
│   ├── instruments_controller.py
│   ├── instrument_picker_widget.py
│   ├── candles_panel_widget.py
│   ├── strategy_results_widget.py
│   ├── home_controller.py
│   ├── tab_home.py
│   ├── quotes_hub.py
│   ├── positions_hub.py
│   ├── tab_robots.py
│   ├── tab_sandbox_trading.py
│   ├── tab_history.py
│   ├── tab_journal.py
│   └── tab_events.py
├── workers.py          # Фоновые задачи
├── db/                 # База данных (заглушка)
├── data/               # Кэш данных
└── secrets/            # Секреты (токен)
```

## Установка

### Требования
- Python 3.11 или выше
- pip

### Шаги установки

1. Создайте виртуальное окружение:
```bash
python -m venv .venv
```

2. Активируйте окружение:
```bash
# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Настройте токен:

### Токен для песочницы
   - Создайте файл `secrets/tinvest_token.txt`
   - Вставьте ваш токен T-Investments

### Токен для реального счёта
   - Создайте файл `secrets/tinvest_real_token.txt`
   - Вставьте ваш токен для реального счёта

**Важно:** Файлы с токенами не должны попадать в репозиторий (добавлены в `.gitignore`)

## Запуск

```bash
python main.py
```

## Вкладки приложения

1. **Инструменты** - просмотр и выбор акций, облигаций, ETF
   - Загрузка каталога инструментов
   - Избранное
   - Загрузка свечей (интернет/CSV/кэш)
   - Расчёт стратегий на исторических данных
   - Дивиденды

2. **Торговля** - песочница для торговли (в разработке)

3. **Роботы** - управление торговыми роботами (в разработке)

4. **История** - история сделок (в разработке)

5. **Журнал** - журнал событий (в разработке)

6. **События** - стрим событий (в разработке)

7. **Реальный счёт** - информация по реальному счёту
   - Баланс портфеля (общая стоимость, акции, облигации, ETF, валюта)
   - Список позиций с реального счёта (бумаги, количество, средняя цена, текущая цена)
   - Таблица избранного с позициями реального счёта

## Стратегии

В приложении реализованы следующие стратегии для бэктестинга:

- **Grid Basic** - базовая сетка
- **Grid Basic + Дивиденды** - сетка с учётом дивидендов
- **Buy & Hold + Дивиденды** - покупка и удержание с дивидендами
- **SMA Cross** - пересечение скользящих средних

## Примечания

- Файл с токеном `secrets/tinvest_token.txt` не должен попадать в репозиторий
- Кэш данных в папке `data/` не коммитится
- Приложение работает с T-Invest API через библиотеку `t-tech-investments`
