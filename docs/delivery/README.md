# Пакет сдачи (ТЗ §14, §15, §19)

| Файл | Что это |
|---|---|
| `out/Сопроводительная документация.docx`, `.pdf` | 79 с.: методы обработки данных, условия и ограничения, установка и сборка, функциональная и компонентная архитектура, учебный контур, учения, вики, работа с телефона, отчёт по безопасности с чек-листом ввода в эксплуатацию, 149-ФЗ / 152-ФЗ, перечень библиотек |
| `out/Презентация.pptx`, `.pdf` | Презентация решения, 21 слайд, с заметками докладчика |
| `img/` | Скриншоты интерфейса, использованные в документах |

## Пересборка

Документация собирается из `documentation.md`. Главы-методики подключаются из `docs/*.md` директивой
`<!-- include: … -->`, поэтому текст методик существует в одном экземпляре.

```bash
cd backend && uv run python ../docs/delivery/gen_libraries.py        # перечень библиотек → libraries.md
cd .. && uv run --no-project --with python-docx --with pywin32 python docs/delivery/build.py
```

PDF документации и презентации делают Microsoft Word и PowerPoint (COM). Без Office собирается
только DOCX.

Презентация генерируется pptxgenjs (нужны пакеты `pptxgenjs` и `sharp`). Иконки берутся из
`frontend/node_modules/@tabler/icons`:

```bash
npm install --prefix /tmp/deck pptxgenjs sharp
node docs/delivery/presentation.js /tmp/deck/node_modules
```

## Проверки, на которые ссылаются документы

```bash
# 20 пользователей с паузами 1–5 с (как живые диспетчеры) и стресс без пауз
uv run --no-project --with httpx python docs/delivery/load_test.py https://localhost 20 60 5
uv run --no-project --with httpx python docs/delivery/load_test.py https://localhost 20 60

# демо-сценарии на настоящих эпизодах
docker compose exec backend python manage.py demo_scenario alarms|fire|sensor
```
