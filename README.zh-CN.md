# 水印清理工具 — WebUI

[English](README.md) · **简体中文**

本地运行的元数据 + 隐形字符清理器，界面套在
**[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**
的官方引擎之上：剥离 C2PA / EXIF / XMP / 生成器标记，清除文本里的零宽字符、双向控制符与同形字。

> **这不是引擎的 fork。** 本项目是在官方镜像 `ghcr.io/guillaumemeyer/watermarks-remover`（MIT）
> 之上做的一层界面 + 转发层 + 容器编排；引擎本体、模型权重、API 密钥都不在本仓库里，也不联网上报。

![界面](ui-final.png)

*界面中英双语，右上角 `EN` 按钮随时切换，首次访问跟随浏览器语言。截图是英文界面。*

---

## 快速开始

```sh
git clone https://github.com/MobiusIndex/watermarks-remover-webui && cd watermarks-remover-webui
docker compose up -d --build      # 首次会拉取引擎镜像（约 1 GB）
```

浏览器打开 <http://127.0.0.1:8770>。需要 Docker 24+ / Compose v2，磁盘约 3 GB。

两种跑法：

| 模式 | 命令 | 适合 |
| --- | --- | --- |
| 两容器（默认） | `docker compose up -d --build` | 长期运行；界面出问题不影响引擎 |
| 单容器 | `docker compose -f compose.allinone.yaml up -d --build` | 一条命令跑起来，引擎与界面同容器 |

端口、绑定地址、限额、并发都写在 `.env`（`cp .env.example .env`），compose 与 `start.sh` 读同一份；
`./start.sh up|allinone|logs|stop|status|rebuild` 是常用命令的快捷方式。

---

## 它能做什么

- 剥离 C2PA / Content Credentials 凭证
- 剥离 EXIF / XMP / 生成器标记（Midjourney、Stable Diffusion、ComfyUI 等）
- 清除零宽字符、双向控制符、同形字、异体空格
- 可选：调用大模型做 **Layer B 文本改写**
- 可选：音频破坏性重编码（变速 + 变调）

**它不做什么**（界面上如实标注，不假装）：

- 像素级隐形水印（SynthID、Tree-Ring）——上游因许可证不发布模型
- 文本水印**检测**（MarkLLM / Gumbel / Claude）——默认没装
- 任何「绕过合规」的用途——只适用于你自己拥有或有权处理的内容

---

## 支持的格式

| 类型 | 扩展名 |
| --- | --- |
| 图片 | png jpg jpeg webp avif heic heif bmp gif tiff tif |
| 文档 | pdf docx xlsx pptx odt epub svg html htm md markdown mdx |
| 文本 | txt json yaml csv py js ts go rs java c cpp … 共 59 种 |
| 音视频 | mp4 mov m4v m4a wav mp3 flac |

没有扩展名的文件（截图、`Dockerfile`、`.gitignore`）先按文件头识别，认不出且内容确实是文本就按
纯文本处理；带扩展名却认不出的（`.bin`、`.xyz`）直接拒绝，不猜。

---

## 选项

| 选项 | 作用 | 默认 |
| --- | --- | --- |
| 元数据：全部 / 仅 AI 标记 | 全部剥离，或保留相机参数 | 全部剥离 |
| 音频破坏性重编码 | 变速 1.08× + 升调 2 半音，输出 M4A | 关 |
| 异体空格 → 普通空格 | NBSP、窄空格转普通空格 | 开 |
| NFKC 归一化 | 全角转半角（会改正文） | 关 |
| 同形字归正 | 西里尔/希腊字母转 ASCII | 关 |
| 剥离承载型不可见字符 | 连写符、变体选择符 | 关 |
| 剥离双向控制符 | RLO/LRO/PDF 等 | 关 |
| 内嵌图片深度清理 | PDF/Office 里的图片重蒸馏 | 自动 |
| 文档内文本也清理 | 关闭则只剥元数据 | 开 |

---

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WATERMARKS_UPSTREAM` | `http://wr-core:8765` | 引擎地址 |
| `WATERMARKS_WEB_PORT` | `8770` | 监听端口 |
| `WATERMARKS_MAX_INPUT_BYTES` | `268435456`（256 MB） | 单文件上限 |
| `WATERMARKS_MAX_BATCH_FILES` | `50` | 批量上限 |
| `WATERMARKS_WEB_CONCURRENCY` | `2` | 并发清理数 |
| `WATERMARKS_WEB_TIMEOUT` | `1800` | 转发超时（秒） |

引擎侧变量（Layer B 后端、检测器、外部模型目录）：见
[docs/details.zh-CN.md › 配置](docs/details.zh-CN.md#配置)。

---

## 可选：AI 文本改写

纯文本 / Markdown / HTML / SVG 可以额外走一次模型改写（Layer B），这是唯一能去掉文本统计水印的
路径。默认关闭。在右上角「AI」面板里配一个服务商即可：内置 16 家预设，也支持任意 OpenAI 兼容
端点。密钥只存在浏览器 localStorage，随请求头传递，不落服务端、不写进容器。

服务商清单、改写策略、本地模型网络拓扑：
[docs/details.zh-CN.md › AI 接口](docs/details.zh-CN.md#ai-接口layer-b-文本改写)。

---

## 文档

- [架构与 HTTP 端点](docs/details.zh-CN.md#架构)
- [目录与文件](docs/details.zh-CN.md#目录与文件) · [移植与适配](docs/details.zh-CN.md#移植与适配)
- [开发与自测](docs/details.zh-CN.md#开发与自测) — 116 项断言
- [离线安装](docs/details.zh-CN.md#离线安装) · [常见问题](docs/details.zh-CN.md#常见问题) · [局域网共享](docs/details.zh-CN.md#局域网共享)

## 许可与来源

引擎来自 **[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**（MIT），
镜像 `ghcr.io/guillaumemeyer/watermarks-remover`。本仓库自己的代码（`server.py`、`index.html`、
`app.js`、`i18n.js`、`styles.css`、`compose*.yaml`、`Dockerfile`、`docker/`、`start.sh`、
`llm-relay.py`、`tools/`）以 **MIT** 发布，见 [LICENSE](LICENSE)。

只适用于清理你自己拥有或有权处理的内容。
