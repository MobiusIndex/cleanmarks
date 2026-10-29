# 界面 + 转发层镜像。
#
# 直接以 wr-core 的官方镜像为基础：那里面已经装好 exiftool / qpdf /
# ghostscript / ffmpeg / c2patool，也带了 /app/scripts 下的清洗实现
# （纯文本 Layer A 直接复用其中的 text_unicode）。
# 本镜像只多四样东西：页面、样式、页面脚本、转发层。
#
#   docker compose up -d --build

FROM ghcr.io/guillaumemeyer/watermarks-remover:latest

WORKDIR /app

COPY server.py index.html app.js styles.css /app/

# 界面服务不需要 root，也不需要写文件系统（临时文件走 /tmp tmpfs）。
USER 10001

ENV WATERMARKS_UPSTREAM=http://wr-core:8765 \
    WATERMARKS_SCRIPTS=/app/scripts \
    WATERMARKS_WEB_PORT=8770 \
    PYTHONUNBUFFERED=1

EXPOSE 8770

ENTRYPOINT ["python3", "/app/server.py"]
