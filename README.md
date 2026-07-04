# TBPR2

Локальное Python-приложение (PyQt6) для работы с T-Invest API.

## Структура

- `main.py` - точка входа приложения
- `app/` - конфиг и главное окно
- `core/` - бизнес-логика и API-слой
- `tabs/` - вкладки интерфейса
- `secrets/tinvest_token.txt` - файл токена (локально, не коммитить)

## Требования

- Python 3.11+
- pip

## Установка

```bash
python -m venv .venv