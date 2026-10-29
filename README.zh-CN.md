# 水印清理工具 — WebUI

[English](README.md) · **简体中文**

> **这个仓库是什么**
>
> 它**不是**引擎的 fork。清洗引擎来自
> **[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**（MIT），
> 本项目是在它的官方镜像之上做的一层**展示用界面 + 转发层 + 容器编排**：
>
> | | |
> | --- | --- |
> | 上游引擎（源码） | <https://github.com/guillaumemeyer/watermarks-remover>（MIT） |
> | 上游引擎（镜像） | `ghcr.io/guillaumemeyer/watermarks-remover:latest` |
> | 本仓库新增 | 浏览器界面、二进制直传的转发层、Docker Compose 编排、可选的 AI 文本改写入口 |
> | 本仓库不含 | 引擎本体、模型权重、任何 API 密钥 |

本地运行的「元数据 + 隐形字符」清理器。整套跑在 Docker 里，宿主机不留运行时文件；
浏览器不直连引擎，所有请求经一层自写的转发。

**它做什么**

- 剥离 C2PA / Content Credentials 凭证
- 剥离 EXIF / XMP / 生成器标记（Midjourney、Stable Diffusion、ComfyUI 等）
- 清除文本里的隐形 Unicode：零宽字符、双向控制符、同形字、全角与异体空格
- 可选：调用大模型做 **Layer B 文本改写**（界面右上角「AI 接口」）
- 可选：音频**破坏性重编码**（变速 + 变调），用于对付音频水印

**它不做什么**（界面上如实标注「未部署」，不藏着）

- 像素级隐形水印（SynthID、Tree-Ring 等）——需要额外 ML 模型，上游因许可证原因不发布
- 文本水印**检测**器（MarkLLM / Gumbel / Claude）——默认没装
- 任何"绕过合规"的用途——只适用于你自己拥有或有权处理的内容

---

## 快速开始

```sh
docker compose up -d --build     # 首次会拉取并构建镜像（约 1GB 下载）
```

浏览器打开 <http://127.0.0.1:8770>。

Linux / macOS 也可以用附带脚本：

```sh
./start.sh up       # 构建并启动（会自动打开浏览器）
./start.sh logs     # 跟踪日志
./start.sh status   # 查看状态
./start.sh stop     # 停止
./start.sh rebuild  # 上游镜像更新后重建
```

**环境要求**

| 项 | 要求 |
| --- | --- |
| Docker | 24.0+ 或 Docker Desktop |
| Compose | V2（`docker compose` 子命令，不是旧的 `docker-compose`） |
| 磁盘 | 约 3GB（引擎镜像本身 1.05GB） |
| 网络 | 首次构建需要能访问 `ghcr.io`；离线安装见文末 |
| 内存 | 容器 `/tmp` 是 tmpfs（占内存），处理大文件时峰值几百 MB |

### 两种运行模式

| 模式 | 命令 | 适合 |
| --- | --- | --- |
| 两容器（默认） | `docker compose up -d --build` | 长期运行：引擎单独一个容器，界面出问题不影响它 |
| 单容器 | `docker compose -f compose.allinone.yaml up -d --build` | 只想一条命令跑起来：引擎和界面在同一个容器里 |

不想用 compose 也可以：

```sh
docker build -t watermarks-remover-webui .
docker run -d --name wr-web -p 127.0.0.1:8770:8770   -e WATERMARKS_EMBEDDED=1 -e WATERMARKS_UPSTREAM=http://127.0.0.1:8765   --read-only --tmpfs /tmp --init watermarks-remover-webui
```

端口、监听地址、单文件上限、并发数都写在 `.env` 里（`cp .env.example .env` 再改），
`start.sh` 与 compose 读同一份配置。`./start.sh allinone` 就是单容器模式。

---

## 界面

```
┌ 水印清理工具                        ● 引擎 0.7.0   AI 接口 ●  ☀ ┐
├───────────────────────────────────┬──────────────────────────┤
│  拖入 / 点击 / 粘贴 / 选文件夹      │ 图片 · 音视频             │
│  支持格式一览                       │ 文本 · 文档               │
│  [检测] [清理] [打包下载] [清空]    │ 文档（PDF / Office）      │
│  进度条 + 取消                      │ 服务能力 · 恢复默认        │
│  文件卡片：状态 · 详情 · 操作        │                          │
└───────────────────────────────────┴──────────────────────────┘
```

- **入队**：拖拽、点击选择、粘贴（截图）、选文件夹都支持；重复文件自动跳过，扩展名不认识的文件会被拒。
- **检测**：只查不改，返回 C2PA / AI 元数据 / 隐形字符的逐项清单。
- **清理**：清理完自动**复检**一次，残留直接标在卡片上。
- **打包下载**：浏览器内直接生成 ZIP（存储模式，CRC32 校验），不用把文件再传一遍服务端。
- **取消**：任何批量任务都能中断，已完成的保留。
- **对比**：图片清理前后左右拖动对比。
- **深浅色**：跟随系统，右上角可手动切换；选项记在浏览器本地。

每张卡片可单独操作：**检测 / 清理 / 下载 / 对比 / 重新清理 / 移除**。
一次最多 200 个文件；清理并发 2、检测并发 4。

![界面](ui-final.png)

右上角的「AI 接口」是可选功能，配置后文本类文件会额外走一次模型改写：

![AI 接口设置](ui-ai-api.png)

---

## 支持的格式

| 类型 | 扩展名 |
| --- | --- |
| 图片 | png jpg jpeg webp avif heic heif bmp gif tiff tif |
| 文档 | pdf docx xlsx pptx odt epub svg html htm md markdown mdx |
| 文本 | txt text csv tsv json yaml yml toml css js ts tsx jsx mjs cjs py rs go java c h cpp cs kt swift rb php lua pl r sh bash ps1 sql vue svelte astro 等 59 种 |
| 音视频 | mp4 mov m4v m4a wav mp3 flac |

扩展名以引擎的分类表为准（`GET /api/meta` 返回完整清单）。**没有扩展名**的文件
（截图、剪贴板、临时导出、`Dockerfile`、`Makefile`、`.gitignore`、`LICENSE`）先按文件头
识别 PNG/JPEG/GIF/WebP/BMP/TIFF/AVIF/HEIC/PDF/MP4/MOV/M4A/WAV/FLAC/MP3；认不出但内容
确实是文本（无 NUL、控制字符低于 1%、≤32MB）就按纯文本处理。带扩展名却不认识的
（`.bin`、`.xyz`）直接拒绝，不会拿二进制去当文本改写。

---

## 选项

| 选项 | 作用 | 适用 | 说明 |
| --- | --- | --- | --- |
| 元数据剥离：全部 / 仅 AI 标记 | 是否保留相机参数、机型等非 AI 元数据 | 图片、音视频 | 默认「全部剥离」 |
| 音频水印破坏性重编码 | 变速 1.08× + 升调 2 半音 + EQ，再转 M4A | 纯音频 | 损音质；有视频轨的文件自动跳过 |
| 异体空格转普通空格 | 不换行空格、窄空格 → 普通空格 | 文本、文档 | 默认开 |
| NFKC 兼容归一化 | 全角字母数字 → 半角 | 文本、Markdown/HTML/SVG | 会改正文，默认关 |
| 同形字归正 | 西里尔/希腊字母 → ASCII | 文本、Markdown/HTML/SVG | 可能误伤俄语正文 |
| 剥离承载型不可见字符 | 连写、变体选择符 | 文本、Markdown/HTML/SVG | 会破坏 emoji、国旗 |
| 剥离双向控制符 | RLO/LRO/PDF 等 | 文本、Markdown/HTML/SVG | 会破坏阿语/希语排版 |
| 内嵌图片深度清理 | PDF/Office 里的图片是否重蒸馏 | 文档 | auto / always / lossless / never |
| 文档内文本也做隐形字符清理 | 关掉就只剥元数据，正文原样保留 | 文档 | 默认开 |

Markdown / HTML / SVG 这类「文本型容器」先走引擎的容器管线（剥 frontmatter 里的 AI
字段、内嵌 data URI），再按上面的开关补一遍 Layer A 归一化——两段处理，报告会分别列出。

---

## 可选：接入 AI 接口（Layer B 文本改写）

右上角「AI 接口」是**可选功能**。不配置的话，上面所有功能照常工作；配置之后，
纯文本 / Markdown / HTML / SVG 会额外做一次模型改写，用来抹掉 AI 文本的统计水印
（这是唯一能真正移除文本水印的路径）。

### 服务商预设

选服务商会自动填好 Base URL 与模型名，也可以选「自定义」填任意 OpenAI 兼容端点。

| 服务商 | Base URL | 模型示例 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com` | gpt-4o-mini / gpt-4.1-mini |
| DeepSeek | `https://api.deepseek.com` | deepseek-chat / deepseek-reasoner |
| 月之暗面 Kimi | `https://api.moonshot.cn` | kimi-k2-turbo-preview |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | glm-4-flash / glm-4-plus |
| 阿里云百炼 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus / qwen-max |
| 腾讯混元 | `https://api.hunyuan.cloud.tencent.com/v1` | hunyuan-turbos |
| 讯飞星火 | `https://spark-api-open.xf-yun.com/v1` | x1.5 / 4.0Ultra |
| 百度千帆 | `https://qianfan.baidubce.com/v2` | ernie-4.0-8k |
| 硅基流动 | `https://api.siliconflow.cn/v1` | Qwen/Qwen2.5-72B-Instruct |
| OpenRouter | `https://openrouter.ai/api/v1` | deepseek/deepseek-chat |
| Groq | `https://api.groq.com/openai/v1` | llama-3.3-70b-versatile |
| xAI Grok | `https://api.x.ai/v1` | grok-4 |
| Anthropic Claude | `https://api.anthropic.com/v1` | claude-sonnet-4-5 |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | gemini-2.5-flash |
| Ollama（本地，需装在 WSL） | `http://host.docker.internal:11434` | qwen3:8b |
| LM Studio（Windows，本机够不到） | `http://host.docker.internal:1234` | local-model |

Base URL 的路径会自动补全：结尾是 `/v1`、`/v2`、`/v3`、`/v4` 或 `/openai` 的补
`/chat/completions`，其余补 `/v1/chat/completions`。协议可选 OpenAI 兼容或 Ollama 原生。

### 改写策略

策略来自上游引擎，语法 `战术@强度` 逗号分隔，强度 0–1 越大改得越多：

| 战术 | 作用 |
| --- | --- |
| `paraphrase` | 换词改写，token 级改变措辞 |
| `humanize` | 去 AI 腔（句式、套话、装饰性副词） |
| `structural` | 先抽要点再重写成完整文档 |
| `backtranslate` | 回译，抹水印最彻底，也最慢最贵 |
| `code` | 只改注释、文档串和局部变量名 |
| `mlm` | 需要 transformers，本镜像没装，会直接报错 |

界面提供「轻度 / 标准 / 彻底 / 去 AI 腔 / 改写+去 AI 腔 / 结构重排 / 回译」预设，
也可以自己写。

### 密钥与隐私

- 密钥**只存在你这台机器的浏览器**（localStorage），不写进容器、不落服务端；每次请求
  随 `X-Wm-Llm` 头带过去，服务端用完即弃，错误信息里也会把密钥替换成 `***`。
- 用云端服务商时，**被改写的正文会发送给对方**。介意隐私就把 Base URL 指向本地模型。
- 「测试连接」发一个最小请求，返回延迟、模型名和实际命中的端点。

### 本地模型的网络拓扑（本机实测）

Docker 跑在 WSL 里时：

- 容器**没有** `host.docker.internal` 这个 DNS。填它也能用——服务端会自动改用容器的
  默认网关（也就是 WSL 宿主）地址。
- WSL 里的服务只要监听全网卡（Ollama 设 `OLLAMA_HOST=0.0.0.0`），容器就能直连。
- 只监听 `127.0.0.1` 的服务（Ollama 默认配置）用 `llm-relay.py` 在 WSL 里桥一道：

  ```sh
  # WSL 里执行
  python3 llm-relay.py --listen 8788 --target 11434
  # 界面 Base URL 填 http://host.docker.internal:8788/v1
  ```

- **Windows 上的 LM Studio 容器够不到**：WSL 与 Windows 不共享 loopback，容器也到不了
  Windows 的局域网地址（实测超时）。要本地跑请把模型服务装进 WSL，或用云端 API。

---

## 架构

```
浏览器
  ↓ http://127.0.0.1:8770
wm-web            界面 + 转发层（Python 标准库，无第三方依赖）
  ↓ http://wr-core:8765（仅容器网络内，不映射宿主机端口）
wr-core           官方清洗引擎
                  exiftool / qpdf / ghostscript / ffmpeg / c2patool
```

转发层承担了三件引擎不做的事：

1. **二进制直传**：页面把文件当请求体发过来，服务端流式落盘、分块编码成引擎要的
   base64 JSON 信封；回来的 base64 也在服务端解码，浏览器只拿到 Blob + `X-Wm-Report`
   头。页面因此不做 base64，49MB 的图片全程约 8.6 秒，内存峰值在几十 MB 量级。
2. **按类型分流**：引擎对纯文本 `/clean` 强制要求 Layer B 重写后端（未配置时必然 400），
   这类文件改用引擎自带的 `text_unicode` 做 Layer A；其余交给引擎。无扩展名文件按魔数识别。
3. **能力下发**：`/api/meta` 一次给出引擎版本、工具可用性、选项白名单、大小限额，界面据此
   禁用不可用选项，而不是让用户点了才看到报错。

两个容器都设了 `restart: unless-stopped`，Docker 启动后自动拉起；`wr-core` 不映射宿主机
端口，只能经 `wm-web` 访问；`wm-web` 绑 `127.0.0.1`，外网访问不到。

### HTTP 端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/`、`/index.html`、`/app.js`、`/styles.css` | 静态页面 |
| GET | `/api/ping` | **只报 web 进程**活着（容器健康检查用它，引擎挂掉不跟着判死） |
| GET | `/api/health`、`/api/capabilities` | 透传引擎 |
| GET | `/api/meta` | 能力、选项白名单、限额（缓存 60s） |
| POST | `/api/raw/inspect` | 请求体是原始文件，返回检测 JSON |
| POST | `/api/raw/clean` | 请求体是原始文件，返回清理后的二进制 + `X-Wm-Report` 头 |
| POST | `/api/llm/test` | AI 接口探活（最小 chat 请求），返回延迟与实际端点 |
| POST | `/api/text-clean` | 旧版 JSON 接口（base64 进、base64 出），保留给脚本 |
| POST | `/api/clean`、`/api/inspect`、`/api/clean/batch` … | 透传引擎 |

`/api/raw/*` 把文件名与选项放在请求头：`X-Wm-Name`、`X-Wm-Options`（base64url JSON，
避免中文文件名与查询串长度问题）。配置了 AI 接口时再带 `X-Wm-Llm`（同样的编码），
只对文本类文件生效。

响应头：`X-Wm-Report`（base64 的报告 JSON）、`X-Wm-Out-Name`（建议的下载名）、
`X-Wm-Kind`、`X-Wm-Bytes-Out`。

---

## 配置

### 本项目（wm-web）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `WATERMARKS_UPSTREAM` | `http://wr-core:8765` | 引擎地址 |
| `WATERMARKS_SCRIPTS` | `/app/scripts` | 引擎脚本目录（复用其中的 text_unicode / rewrite_text） |
| `WATERMARKS_WEB_PORT` | `8770` | 监听端口（也可用 `--port`） |
| `WATERMARKS_MAX_INPUT_BYTES` | `268435456`（256MB） | 单文件上限 |
| `WATERMARKS_MAX_BATCH_FILES` | `50` | 批量上限 |
| `WATERMARKS_WEB_TIMEOUT` | `1800` | 转发引擎的超时（秒） |

### 引擎（wr-core，按需开启）

| 变量 | 作用 |
| --- | --- |
| `WATERMARKS_SERVER_API_KEY` | 引擎自身鉴权（留空即不鉴权） |
| `WATERMARKS_REWRITE_BACKEND` / `_MODEL` / `_BASE_URL` / `_API_KEY` | 引擎侧 Layer B 后端（用界面配置更方便，二选一） |
| `WATERMARKS_CLEAN_STRATEGY_FILE` | 默认策略文件（默认 `config/clean_strategy.json`） |
| `WATERMARKS_GUMBEL_KEY` | 启用 Gumbel 文本水印检测（免模型） |
| `MARKLLM_DIR` / `MARKDIFFUSION_DIR` / `NOAI_WATERMARK_DIR` / `REVERSE_SYNTHID_DIR` | 外部模型后端的检出目录 |

---

## 目录与文件

| 文件 | 作用 |
| --- | --- |
| `compose.yaml` | 编排定义：两个服务、tmpfs、健康检查、只读 rootfs |
| `compose.allinone.yaml` | 单容器模式的编排（引擎与界面同容器） |
| `docker/entrypoint.sh` | 容器入口：需要时先拉起嵌入式引擎，再启动界面 |
| `Dockerfile` | 界面镜像，基于官方镜像，只加四个文件 |
| `server.py` | 界面服务 + 转发层（纯文本 Layer A、AI 接口、Layer B） |
| `index.html` | 页面骨架（无框架） |
| `styles.css` | 主题变量与组件样式（含深色模式） |
| `app.js` | 页面逻辑：批量并发、取消、复检、对比、ZIP、偏好、AI 接口配置 |
| `llm-relay.py` | 可选：把只监听 127.0.0.1 的本地模型服务桥给容器（在 WSL 里跑） |
| `start.sh` | Linux/macOS/WSL 启动脚本（`up` / `allinone` / `logs` / `stop` / `status` / `rebuild`） |
| `.env.example` | 端口、绑定地址、限额、并发的配置模板（复制成 `.env` 即可） |
| `LICENSE` | MIT |

运行时不会在宿主机写任何文件：容器 rootfs 只读，临时文件走 `/tmp`（tmpfs），随请求目录
一起删除。

---

## 开发与自测

Docker 跑在 WSL 里时，常见的做法是把编辑副本放 Windows、运行副本放 WSL。改完同步并重建：

```sh
wsl sh -c 'cd /mnt/f/<你的路径>/watermarks-remover-webui \
  && cp server.py index.html app.js styles.css README.md /root/watermark-cleaner/ \
  && cd /root/watermark-cleaner && docker compose build web && docker compose up -d'
```

只在一个目录里工作的话，直接 `docker compose up -d --build` 就够了。

回归脚本放在 `.ref/`：

| 脚本 | 覆盖 |
| --- | --- |
| `e2e.py` | 39 项：文本 / Markdown frontmatter / 图片 / DOCX / 音频链 / 视频 / 错误路径 / 旧接口兼容 |
| `e2e_llm.py` | 18 项：AI 接口探活、Layer B 生效、未配置时行为不变、密钥不外泄、非法配置报错 |
| `test_split.py` | 11 项：上游响应解析的边界（空内容、字段顺序变化、含引号的报告） |
| `test_edges.py` | 9 项：空文件、无扩展名文本、超长文件名、8 路并发一致性、并发下 /api/meta |
| `test_proto.py` | 11 项：短包被拒、错误响应的 Connection 语义、跨站 Origin、选项语义、存活探针、坏 LLM 头 |
| `test_units.py` | 28 项：报告头裁剪、主机回退判定、文件名清洗、文本兜底、格式判定（直接 import server.py） |
| `mock_openai.py` | 假 OpenAI 兼容服务端，供上面两个脚本使用 |

```sh
cd .ref && python e2e.py && python e2e_llm.py && python test_split.py \n  && python test_edges.py && python test_proto.py && python test_units.py
```

共 116 项断言：39（基础链路）+ 18（AI 接口）+ 11（响应解析）+ 9（边界并发）
+ 11（协议层）+ 28（纯函数单测）。

### 安全与健壮性边界

- **同源校验**：`POST` 带 `Origin` 且与 `Host` 不一致时回 403。服务只绑回环，但任意网页都能用
  `fetch` 直接打过来（CORS simple request 不需要预检），这条挡的是别的站点拿你的机器当算力。
- **短包拒绝**：`Content-Length` 声明 N 字节却少发时回 400，不会把半截文件当成完整输入清理。
- **错误即断开**：所有 4xx/5xx 响应带 `Connection: close`。错误分支通常没读完请求体，
  保持连接会让残留字节被当成下一个请求解析（日志里会出现 `"0123…GET /api/health" 501`）。
- **并发上限**：清理同时最多 2 个（`WATERMARKS_WEB_CONCURRENCY`），每个请求在 `/tmp`(tmpfs)
  上的峰值约 3.3–3.7 倍文件大小；检测 4 个。
- **密钥不出内网**：AI 接口的 host 回退（解析不到就试 docker 网关）只对 `localhost`、
  `host.docker.internal`、裸主机名、私网 IP 生效；云服务商域名解析失败只报错，不换地址重发，
  避免明文 http 下把 `Authorization` 送给别人。
- **上传/下载超时**：连接 120 秒无 I/O 即断开，慢速客户端不会无限期占住线程。
- **报告头有上限**：`X-Wm-Report` 打包后超过 12KB 会裁掉明细并带 `truncated: true`，
  免得代理把整条响应头丢掉。
- **ZIP 上限 4GB**：打包是手写的 store 模式 + 32 位偏移（没有 zip64），超过 4GB 会写出
  中央目录错位的坏包，所以直接拒绝并提示分批下载。
- **Layer B 探测定长缓存**：引擎配了重写后端时 `/api/meta` 的探测本身是一次真实 LLM 调用，
  结果缓存 30 分钟（未配置时 5 分钟）。

---

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 页面显示「引擎未连接」 | `wm-web` 连不上 `wr-core`：`docker compose logs wr-core` 看是否启动失败 |
| 提示「文件过大」 | 超过 256MB 上限，调 `WATERMARKS_MAX_INPUT_BYTES`（同时调大容器内存） |
| AI 接口「连不上」 | 先点「测试连接」看命中的端点；容器里没有 `host.docker.internal` 时会自动改用网关地址 |
| AI 接口 401/403 | 密钥不对，或该服务商需要别的鉴权方式（先换同协议的其它服务商验证） |
| 本地模型连不上 | 模型服务要监听 `0.0.0.0`；只听 `127.0.0.1` 就用 `llm-relay.py` |
| 端口 8770 被占 | 改 `compose.yaml` 里的 `ports` 映射，或停掉占用进程 |
| Windows 上的 LM Studio 用不了 | 见上文「本地模型的网络拓扑」 |

---

## 局域网共享

编辑 `compose.yaml`，把

```yaml
ports:
  - "127.0.0.1:8770:8770"
```

改成

```yaml
ports:
  - "8770:8770"
```

**服务无鉴权，任何能访问该端口的人都能上传文件并拿到清洗结果。**
只在可信网络里这么做，且不要映射到公网。

## 移植与适配

别人拿到这份仓库时，需要注意的就这几条：

- **平台**：引擎镜像只有 `linux/amd64`。Apple Silicon 上要走模拟，
  用 `DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --build`（能跑，但慢）。
- **Docker 类型**：Docker Desktop 和 WSL 里的 dockerd 都行。差别只在「容器怎么找到本机服务」：
  Docker Desktop 有 `host.docker.internal`，WSL dockerd 没有，服务端会自动回退到容器默认网关
  （见上文「本地模型的网络拓扑」）。
- **端口 / 地址**：改 `.env` 里的 `WM_PORT`、`WM_BIND`，不要改 compose 里的字面量。
- **内存**：容器 `/tmp` 是 tmpfs（占内存）。一个清理请求约占文件大小的 3.3–3.7 倍；
  内存紧就把 `--tmpfs /tmp:size=512m` 调小，或把 `WATERMARKS_WEB_CONCURRENCY` 降到 1。
- **只读 rootfs + 非 root**：容器以 uid 10001 运行、根文件系统只读，只在 `/tmp` 写东西。
  把 NFS/SMB 共享目录挂进来会破坏这个前提，不建议。
- **Windows 用户**：装 Docker Desktop（WSL2 后端）就行，`start.sh` 在 Git Bash 或 WSL 里都能跑，
  也可以直接用 `docker compose` 命令。注意宿主机的系统代理不会自动传给容器，
  容器要访问云端 AI 接口得靠 Docker 自己的网络（WSL2 里通常能直连）。
- **不需要 GPU、不需要模型权重**：像素级去水印本来就不在本项目范围内。

---

## 离线安装

目标机器访问不了 `ghcr.io` 时，在有网络的机器上导出镜像：

```sh
docker compose build
docker save \
  ghcr.io/guillaumemeyer/watermarks-remover:latest \
  watermark-cleaner-web:local \
  -o images.tar
gzip -9 images.tar        # 1.05GB → 约 400MB
```

拷贝 `images.tar.gz` 和本目录到目标机器，然后：

```sh
gunzip -c images.tar.gz | docker load
docker compose up -d --no-build
```

---

## 不在处理范围内

- **像素级隐形水印**（SynthID、Tree-Ring 等）需要额外的 ML 模型，上游因许可证原因
  不发布。界面「服务能力」里显示为「未部署」。
- **AI 文本的统计水印**（token 采样类）需要大模型重写后端（Layer B）。引擎侧没有默认
  策略文件，所以纯文本默认只做 Layer A；不过界面右上角的「AI 接口」里配好服务商就能
  直接启用 Layer B（见上文），`/api/meta` 的 `text_layer_b` 字段则反映引擎自身是否
  配了策略。
- **文本水印检测器**（MarkLLM / Gumbel / Claude）同样未部署；其中 Gumbel 只需要一个 key
  （`WATERMARKS_GUMBEL_KEY`）且无需模型，Claude 的检测 API 官方尚未公开。

---

## 许可与来源

清洗引擎来自 [guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)（MIT）。
本目录的 `server.py`、`index.html`、`app.js`、`styles.css`、`compose.yaml`、
`Dockerfile`、`start.sh`、`llm-relay.py` 是在其之上做的界面与编排层。

本仓库的代码（`server.py`、`index.html`、`app.js`、`styles.css`、`compose*.yaml`、
`Dockerfile`、`docker/entrypoint.sh`、`start.sh`、`llm-relay.py`、`tools/`）以 **MIT** 许可发布，
见 [LICENSE](LICENSE)。引擎本身不在本仓库内，按它自己的 MIT 许可使用。

该工具适用于清理**你自己拥有或有权处理**的内容。请勿用于规避合规要求。

## 维护者备注：发布到 GitHub

仓库：<https://github.com/MobiusIndex/watermarks-remover-webui>

`git push` 走 HTTP 代理会卡死（CONNECT 要 20–30 秒，之后 POST 阶段无限等待），
而 `api.github.com` 走同一个代理是通的。所以更新用仓库里的脚本，它通过 Git Data API
把本地提交原样写上去（blob 内容寻址，推完两边 SHA 完全一致）：

```sh
git add -A && git commit -m "…"
python tools/push-via-api.py
```

代理换端口就用 `HTTPS_PROXY=http://127.0.0.1:7891 python tools/push-via-api.py`。
`git push` 本身在代理恢复后也能用，只是目前这条路更稳。
