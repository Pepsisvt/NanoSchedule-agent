FROM python:3.12-slim

RUN apt-get update && apt-get install -y nginx curl net-tools && rm -rf /var/lib/apt/lists/*
RUN rm -f /etc/nginx/sites-enabled/default

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 10000

COPY start_render.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
