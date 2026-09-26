# Архитектура

Codex выбирает проектный скилл, получает данные через локальные MCP, проверяет
документы, подготавливает структурированный Analysis и вызывает расчёт/сохранение.
Нет собственного LLM API, веб-интерфейса, аккаунтов и торговой интеграции.

| MCP | Инструменты |
|---|---|
| moex_market | search_securities, get_security, get_quote, get_market_series, get_bond_schedule, get_key_rates |
| moex_documents | list_issuers, find_reports, list_report_links, download_report, read_pdf |
| moex_research | get_analysis_schema, validate_analysis, save_analysis, list_analyses, read_analysis, compare_analyses, calculate_bond, compare_issues, calculate_equity, calculate_equity_scenarios, plot_market, watch_add, watch_list, watch_check, watch_acknowledge |

MCP серверы используют официальный Python SDK ветки 1.x и STDIO. stdout занят
протоколом; прикладные ошибки передаются как ошибки инструментов. CLI использует те же функции.
Настройка: `python scripts/configure_codex.py --python PATH_TO_VENV_PYTHON`.
Файл создаётся только в текущем проекте; личный config Codex не меняется.

ISS возвращает столбцы/строки; адаптер преобразует их в объекты, сохраняя null,
метаданные и источник. Для истории/свечей есть пагинация и признак truncation;
графики выплат выдаются постранично. Параметры режима торгов указывает вызывающий
агент после идентификации бумаги, чтобы не выбирать произвольный board.

Сетевой слой: только публичный HTTPS, проверка адреса при каждом переходе,
таймауты, ограничение размера, ограниченные повторы временных ошибок. Кеш возвращается
только в пределах TTL с исходным временем получения; устаревший кеш не служит скрытым fallback.
Внешние материалы никогда не являются инструкциями. Инструменты не используют cookies
браузера и не обходят CAPTCHA или платный доступ.

Реестр страниц эмитентов: публичный `config/issuers.json` и личный `.local/issuers.json`.
Пример новой записи:

```json
[
  {"id": "stable-issuer-id", "name": "Название эмитента", "aliases": ["TICKER"],
   "report_pages": ["https://official-issuer.example/investors/reports/"]}
]
```

Домен example в примере не рабочий; подставьте проверенный официальный URL.
HTML-поиск лишь находит кандидатов. Год, стандарт, аудитор и периметр подтверждаются
в документе. PDF хранится по SHA-256, каждая загрузка имеет отдельную квитанцию.

Наблюдение хранит исходные URL и события в локальном SQLite. Ошибка чтения страницы
не сдвигает исходный список. Новое событие остаётся pending до сохранения анализа
с тем же эмитентом и ссылкой на документ. Первая проверка — baseline, не новая публикация.
Повторный анализ выполняет скилл; команда watch-check сама модель не запускает.
