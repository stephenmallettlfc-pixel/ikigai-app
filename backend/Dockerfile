FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD gunicorn --chdir backend main:app --bind 0.0.0.0:$PORT --workers 1
