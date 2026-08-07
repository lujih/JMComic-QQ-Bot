FROM mlikiowa/napcat-docker:v4.18.7

# 一次性装齐：python/ffmpeg/git/tzdata + playwright chromium 系统依赖（来自 install-deps --dry-run），
# 避免构建时跑两次 apt（第二次 install-deps 会重复下载 ubuntu 源，HF 构建器访问该源极慢 ~530KB/s）
RUN apt-get update && apt-get --fix-broken install -y && \
    apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ffmpeg git tzdata \
    libatk-bridge2.0-0 libatk1.0-0 libatspi2.0-0 libcairo2 libcups2 libdbus-1-3 \
    libdrm2 libfontconfig1 libgbm1 libglib2.0-0 libnspr4 libnss3 libpango-1.0-0 \
    libx11-6 libxcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxkbcommon0 \
    libxrandr2 libasound2 xvfb fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/* && \
    python3 -c "import sys; assert sys.version_info >= (3,10), f'Python 3.10+ required, got {sys.version_info}'" && \
    ln -sf /usr/bin/python3 /usr/bin/python

ENV TZ=Asia/Shanghai
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 浏览器层先于 requirements 安装（只依赖 venv 层，代码/requirements 变更不触发 Chromium 重下）
# playwright/patchright 钉版与 scrapling[fetchers] 的传递依赖一致（0.4.12 → playwright==1.61.0, patchright==1.61.2）
# PLAYWRIGHT_BROWSERS_PATH 固定到运行期路径（gosu napcat 的 HOME=/app），避免构建/运行路径错位
# patchright 与 playwright 的 chromium revision 可能不同，两个 install 都跑（共用路径，revision 相同则幂等）
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.cache/ms-playwright
RUN pip install --no-cache-dir "playwright==1.61.0" "patchright==1.61.2" && \
    mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" && \
    python -m playwright install chromium && \
    python -m patchright install chromium

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir \
    -r /tmp/requirements.txt && \
    pip install --no-cache-dir --force-reinstall --no-deps \
    "jmcomic @ git+https://github.com/lujih/JMComic-Crawler-Python.git@e3c7e40" && \
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

RUN chmod +x /app/bot/start.sh

ENV FFMPEG_PATH=/usr/bin/ffmpeg

EXPOSE 7860

HEALTHCHECK --interval=120s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860', timeout=5)"

CMD ["bash", "/app/bot/start.sh"]
