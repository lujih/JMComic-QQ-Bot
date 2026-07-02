FROM mlikiowa/napcat-docker:v4.18.7

RUN apt-get update && apt-get --fix-broken install -y && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg \
    && rm -rf /var/lib/apt/lists/* && \
    python3 -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, got {sys.version_info}'" && \
    ln -sf /usr/bin/python3 /usr/bin/python

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir \
    -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

COPY . /app/bot
WORKDIR /app/bot

# 清掉基镜像的 ENTRYPOINT ["bash", "entrypoint.sh"]，避免合并执行
ENTRYPOINT []

# 构建时解压 NapCat Shell，避免每次启动时解压
RUN mkdir -p /app/napcat && \
    unzip -q /app/NapCat.Shell.zip -d /tmp/napcat_shell && \
    cp -rf /tmp/napcat_shell/* /app/napcat/ && \
    (cp -rf /tmp/napcat_shell/config/* /app/napcat/config/ 2>/dev/null || true) && \
    rm -f /app/NapCat.Shell.zip && \
    rm -rf /tmp/napcat_shell

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV FFMPEG_PATH=/usr/bin/ffmpeg

EXPOSE 7860 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD ps aux | grep -q "[p]ython.*bot.py"

CMD ["bash", "/app/start.sh"]
