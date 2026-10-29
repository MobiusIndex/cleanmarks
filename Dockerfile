# 界面 + 转发层镜像。
#
# 直接以 wr-core 的官方镜像为基础：那里面已经装好 exiftool / qpdf /
# ghostscript / ffmpeg / c2patool，也带了 /app/scripts 下的清洗实现
# （纯文本 Layer A 直接复用其中的 text_unicode）。
# 本镜像只多四样东西：页面、样式、页面脚本、转发层。
#
#   docker compose up -d --build

# 引擎镜像钉在 digest 上，不用 :latest，也不用 v0.7.0 这种 tag：
#   · :latest  → 同一个 commit 每次构建可能拿到不同引擎（不可复现）
#   · v0.7.0   → 可复现，但比上游 latest 旧：v0.7.0 之后还有未发版的修复
#                （例如 DOCX 里删掉 AppVersion 会让 Word 报「内容无法读取」）
#   · digest   → 两者兼得：内容固定，且就是当前 latest 那一版
# 升级：把下面这串换成新 digest → 跑 tests/ → 发版。
# 「Engine compatibility」工作流每周用上游最新构建跑一遍全部断言，安全时自动开 issue 提醒换 digest。
ARG ENGINE_REF=ghcr.io/guillaumemeyer/watermarks-remover@sha256:5850a577c15724b02e9b0e44d3e52a9064ca983270f228c893a26b73734d07fd
FROM ${ENGINE_REF}

# ARG 在 FROM 之前只作用于 FROM 行；要在 LABEL 里引用必须重新声明一次。
ARG ENGINE_REF

WORKDIR /app

COPY server.py index.html app.js i18n.js styles.css /app/
# 基础镜像已经切到 USER 10001，构建期 chmod 会被拒（文件属主是 root），
# 所以用 `sh 脚本` 的方式调用，不依赖执行位。
COPY docker/entrypoint.sh /app/entrypoint.sh

# 上游引擎是 MIT，MIT 要求「版权声明随所有副本一起分发」；
# 镜像里还含 ffmpeg(GPL-2.0) / exiftool(Artistic) / qpdf / c2patool(Apache-2.0)，
# 所以把这些许可证原文一并发进去（THIRD_PARTY_NOTICES.md 是清单）。
COPY THIRD_PARTY_NOTICES.md /app/licenses/
COPY licenses/ /app/licenses/

# 界面服务不需要 root，也不需要写文件系统（临时文件走 /tmp tmpfs）。
USER 10001

LABEL org.opencontainers.image.title="CleanMarks" \
      org.opencontainers.image.description="Self-hosted Web UI for the watermarks-remover engine" \
      org.opencontainers.image.source="https://github.com/MobiusIndex/cleanmarks" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="ghcr.io/guillaumemeyer/watermarks-remover" \
      com.cleanmarks.engine.digest="${ENGINE_REF}"

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
