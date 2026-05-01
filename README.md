# Workout Tracker Bot

Telegram бот для отслеживания тренировок на базе Claude AI.

## Деплой на Railway

### 1. Загрузи код на GitHub
1. Создай новый репозиторий на github.com (New repository → название: workout-bot → Create)
2. Загрузи файлы: bot.py, requirements.txt, Procfile

### 2. Задеплой на Railway
1. Зайди на railway.app → New Project → Deploy from GitHub repo
2. Выбери репозиторий workout-bot
3. Railway сам определит что это Python проект

### 3. Добавь переменные окружения
В Railway → твой проект → Variables → добавь:

```
TELEGRAM_TOKEN=твой_токен_от_botfather
ANTHROPIC_API_KEY=sk-ant-...твой_ключ
ALLOWED_USER_ID=твой_telegram_id  (узнай у @userinfobot)
```

### 4. Готово!
Railway автоматически запустит бота.

## Команды бота

- Пришли фото программы тренировки → бот прочитает и покажет историю
- После тренировки напиши результаты текстом в любом формате
- /history — последние тренировки
- /last [упражнение] — последний результат по упражнению
- /rules — правила (что не записывать)
- /addrule [текст] — добавить правило
- /delrule [номер] — удалить правило
