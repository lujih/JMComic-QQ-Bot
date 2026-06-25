FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libcurl4-openssl-dev \
    libssl-dev \
    wget \
    ca-certificates \
    file \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r requirements.txt

COPY . .

ENV ENVIRONMENT=prod
EXPOSE 7860

CMD ["bash", "start.sh"]
