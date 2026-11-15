#!/bin/sh
# База знаний модуля собирается из снапшота разметки один раз (README модуля, «Подготовка базы»).
set -e
if [ ! -f "$ICUST_PROCESSED_DIR/manifest.json" ]; then
  echo "Готовлю базу знаний: $ICUST_RAW_DIR -> $ICUST_PROCESSED_DIR"
  python -m icust.prepare_data "$ICUST_RAW_DIR" "$ICUST_PROCESSED_DIR"
fi
exec uvicorn icust.api:app --host 0.0.0.0 --port 8000
