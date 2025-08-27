#!/bin/bash

# Устанавливаем PYTHONPATH, чтобы включить корневую директорию проекта.
# Это позволит Python находить все ваши модули (app, core, utils).
export PYTHONPATH=.

# Запускаем Gunicorn. Он теперь будет работать из правильной директории.
exec gunicorn -b 0.0.0.0:${PORT:-8080} -w 1 --threads 8 app.main:app