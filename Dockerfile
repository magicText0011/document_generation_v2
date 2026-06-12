# Используйте нужную версию Python
FROM python:3.11-slim

# рабочая папка
WORKDIR /usr/src/app

# Системные пакеты:
#   tzdata            — чтобы переменная TZ из docker-compose применялась к процессу
#                       (без неё /usr/share/zoneinfo пустой и время в логах остаётся в UTC)
#   poppler-utils     — pdf2image (convert_from_bytes) вызывает pdftoppm для OCR-fallback PDF
#   libgl1, libglib2.0-0 — нужны opencv/easyocr (libGL.so.1, libgthread) при OCR изображений
# OCR-стек (easyocr/torch) грузится лениво, но без этих библиотек он падает в рантайме.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# сначала копируем только требования для быстрого кеширования слоёв
COPY requirements.txt ./

# torch/torchvision — CPU-сборка (без CUDA). GPU в контейнере не используется (OCR идёт на CPU),
# а CUDA-стек раздувал образ до ~8 ГБ. Ставим ДО requirements.txt: тогда easyocr видит уже
# установленный torch и не подтягивает обратно nvidia-*-зависимости.
RUN pip install --no-cache-dir torch==2.9.1 torchvision==0.24.1 \
        --index-url https://download.pytorch.org/whl/cpu

# остальные зависимости
RUN pip install --no-cache-dir -r requirements.txt

# копируем остальной код
COPY . .

ENV PYTHONUNBUFFERED=1

# по умолчанию запускаем этот скрипт; можно переопределить в docker-compose через COMMAND
CMD ["python3", "app.py"]
