# CleanMarks —— 水印清理 Web 界面

[English](README.md) · **简体中文**

把 **[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**
的清洗引擎套上一个自托管网页界面：剥离 C2PA / EXIF / XMP / 生成器标记，清除文本里的零宽字符、
双向控制符与同形字，图片、文档、音视频都能处理——全程跑在本机 Docker 里。

> 不是 fork。本仓库是引擎官方镜像 `ghcr.io/guillaumemeyer/watermarks-remover`（MIT）之上的一层
> 界面 + 转发 + 编排；引擎源码不在仓库里，也没有密钥、没有遥测——但 Docker Hub 上发布的镜像
> 已经内置引擎，一条 `docker run` 就能用。

![界面](ui-final.png)

*界面中英双语（右上角语言按钮切换），截图是英文界面。*

[![Docker Hub](https://img.shields.io/badge/docker Hub-2560EB?logo=docker&logoColor=white)](https://hub.docker.com/r/indexmobius/cleanmarks)  
[![Publish image](https://github.com/MobiusIndex/cleanmarks/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/MobiusIndex/cleanmarks/actions/workflows/docker-publish.yml)  

```sh
git clone https://github.com/MobiusIndex/cleanmarks && cd cleanmarks
docker compose up -d --build      # 首次会拉取引擎镜像（约 1 GB）
```

浏览器打开 <http://127.0.0.1:8770>。需要 Docker 24+ / Compose v2，磁盘约 3 GB。

不想本地构建？镜像已经放到 Docker Hub（自带引擎，一个容器搞定）：

```sh
docker run -d --name cleanmarks -p 127.0.0.1:8770:8770   --tmpfs /tmp:rw,size=512m indexmobius/cleanmarks:latest
```

只想跑一个容器：`docker compose -f compose.allinone.yaml up -d --build`（引擎与界面同容器）。
端口、绑定地址、限额写在 `.env`（`cp .env.example .env`）。

## 功能

- 拖拽、点击、粘贴、选文件夹；批量处理可随时取消
- 先检测（只读报告）再清理，清理完自动复检
- 图片前后对比，浏览器内直接打包 ZIP
- 剥离 C2PA / EXIF / XMP / 生成器标记；清理零宽字符、双向控制符、同形字
- 可选：大模型文本改写（Layer B）· 可选：音频破坏性重编码
- 深浅色、中英文切换，选项记在本地

**不做**（界面上如实标注，不假装）：像素级隐形水印（SynthID、Tree-Ring）、文本水印检测
（MarkLLM / Gumbel / Claude）、任何「绕过合规」的用途。

**格式** — 图片 `png jpg webp avif heic gif bmp tiff`；文档 `pdf docx xlsx pptx odt epub svg html md`；
文本 59 种（`txt json yaml py js ts go rs` 等）；音视频 `mp4 mov m4a wav mp3 flac`。
没有扩展名的文件按文件头识别。

## 文档

- [选项与配置](docs/details.zh-CN.md#选项) — 每个开关、每个环境变量
- [架构与 HTTP 端点](docs/details.zh-CN.md#架构)
- [AI 接口（Layer B）](docs/details.zh-CN.md#ai-接口layer-b-文本改写) — 16 家服务商预设
- [移植与适配](docs/details.zh-CN.md#移植与适配) · [离线安装](docs/details.zh-CN.md#离线安装)
- [开发与自测](docs/details.zh-CN.md#开发与自测) — 116 项断言
- [常见问题](docs/details.zh-CN.md#常见问题) · [局域网共享](docs/details.zh-CN.md#局域网共享)

## 许可

引擎 © [guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)（MIT）；
本仓库自己的代码以 **MIT** 发布，见 [LICENSE](LICENSE)。只适用于清理你自己拥有或有权处理的内容。
