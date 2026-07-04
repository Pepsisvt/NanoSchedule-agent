FROM python:3.12-slim

RUN apt-get update && apt-get install -y nginx && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt && pip install -e .

COPY nginx.conf /etc/nginx/sites-available/default

EXPOSE 10000

COPY start_render.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
