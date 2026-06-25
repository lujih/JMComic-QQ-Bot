FROM mlikiowa/napcat-docker:v4.18.7

RUN apt-get update && apt-get --fix-broken install -y && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* && \
    ln -sf /usr/bin/python3 /usr/bin/python

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

COPY . /app/bot
WORKDIR /app/bot

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV WEBUI_TOKEN=jmcomic
ENV FFMPEG_PATH=/usr/bin/ffmpeg

EXPOSE 7860

CMD ["bash", "/app/start.sh"]
