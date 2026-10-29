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

COPY server.py index.html app.js i18n.js styles.css /app/
# 基础镜像已经切到 USER 10001，构建期 chmod 会被拒（文件属主是 root），
# 所以用 `sh 脚本` 的方式调用，不依赖执行位。
COPY docker/entrypoint.sh /app/entrypoint.sh

# 界面服务不需要 root，也不需要写文件系统（临时文件走 /tmp tmpfs）。
USER 10001

# 默认按「单容器」跑：入口脚本在本容器里拉起引擎，界面连 127.0.0.1。
# 这样 `docker run` 一条命令就能用；compose.yaml 会把它改回两容器模式
# （WATERMARKS_EMBEDDED=0 + 上游指向 wr-core 容器）。
ENV WATERMARKS_EMBEDDED=1 \
    WATERMARKS_UPSTREAM=http://127.0.0.1:8765 \
    WATERMARKS_SCRIPTS=/app/scripts \
    WATERMARKS_WEB_PORT=8770 \
    PYTHONUNBUFFERED=1

EXPOSE 8770

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
