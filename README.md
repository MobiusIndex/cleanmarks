# Watermarks Remover — Web UI

**English** · [简体中文](README.zh-CN.md)

A self-hosted web interface for the **[watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**
cleaning engine. It strips C2PA / Content Credentials, EXIF / XMP, generator metadata and
invisible Unicode characters from images, documents, audio and video — entirely on your own
machine, in Docker.

> **What this repository is**
>
> This is **not** a fork of the engine. It is a **front-end + orchestration layer** built on top of
> the official image [`ghcr.io/guillaumemeyer/watermarks-remover`](https://github.com/guillaumemeyer/watermarks-remover):
>
> | | |
> | --- | --- |
> | Upstream engine (source) | <https://github.com/guillaumemeyer/watermarks-remover> (MIT) |
> | Upstream engine (image) | `ghcr.io/guillaumemeyer/watermarks-remover:latest` |
> | What this repo adds | a browser UI, a binary-passthrough proxy, Docker Compose wiring, and an optional LLM text-rewrite interface |
> | What it does **not** ship | the engine itself, model weights, or any API keys |

![Web UI](ui-final.png)

*The interface is available in Chinese and English — the button next to the theme toggle switches
language at runtime. Screenshots in this document show the English UI.*

**What it does**

- Removes C2PA / Content Credentials manifests
- Removes EXIF / XMP / generator metadata (Midjourney, Stable Diffusion, ComfyUI, …)
- Cleans invisible Unicode from text: zero-width characters, bidi controls, homoglyphs, odd spaces
- Optional: **Layer B text rewriting** through an LLM of your choice (the "AI" button)
- Optional: destructive audio re-encode (tempo + pitch), for audio watermarks

**What it does not do** (and says so in the UI instead of pretending)

- Pixel-level invisible watermarks (SynthID, Tree-Ring …) — these need extra ML models that the
  upstream project does not ship for licensing reasons
- Text-watermark *detection* (MarkLLM / Gumbel / Claude) — not installed by default
- Anything that would help you dodge compliance rules — use it only on content you own or are
  allowed to process

---

## Quick start

```sh
docker compose up -d --build      # first run pulls the engine image (~1 GB)
```

Open <http://127.0.0.1:8770>.

Linux / macOS also get a helper script:

```sh
./start.sh up       # build + start (opens the browser)
./start.sh logs     # follow logs
./start.sh status   # container status
./start.sh stop     # stop
./start.sh rebuild  # rebuild after the upstream image updates
```

**Requirements**

| Item | Requirement |
| --- | --- |
| Docker | 24.0+ or Docker Desktop |
| Compose | v2 (`docker compose`, not the legacy `docker-compose`) |
| Disk | ~3 GB (the engine image alone is 1.05 GB) |
| Network | `ghcr.io` reachable on first build (offline install is covered below) |
| Memory | the container `/tmp` is a tmpfs; peak usage is a few hundred MB per large file |

### Two ways to run it

| Mode | Command | Good for |
| --- | --- | --- |
| Two containers (default) | `docker compose up -d --build` | long-running: the engine gets its own container, a UI problem can't take it down |
| Single container | `docker compose -f compose.allinone.yaml up -d --build` | "one command and go": engine and UI live in the same container |

Without compose:

```sh
docker build -t watermarks-remover-webui .
docker run -d --name wr-web -p 127.0.0.1:8770:8770   -e WATERMARKS_EMBEDDED=1 -e WATERMARKS_UPSTREAM=http://127.0.0.1:8765   --read-only --tmpfs /tmp --init watermarks-remover-webui
```

Port, bind address, size limits and concurrency all live in `.env` (`cp .env.example .env`),
read by both `start.sh` and compose. `./start.sh allinone` is the single-container mode.

---

## Features

- **Ingest**: drag & drop, click to pick, paste a screenshot, or pick a whole folder.
  Duplicates are skipped, unknown extensions are rejected up front.
- **Inspect**: read-only; returns a per-item list of C2PA / AI metadata / invisible characters.
- **Clean**: runs a verification pass afterwards and flags any residue on the card.
- **Download all**: builds the ZIP **in the browser** (stored entries, CRC32 verified) — files are
  never uploaded a second time.
- **Cancel**: any batch can be aborted; finished items keep their results.
- **Compare**: drag a splitter to compare before/after for images.
- **Light/dark**: follows the system theme, toggle in the header, remembered in `localStorage`.
- **Bilingual UI**: Chinese / English toggle in the header; the first visit follows the browser
  language and the choice is remembered. (The screenshots here show the English UI.)
- Per-item actions: **inspect / clean / download / compare / re-clean / remove**.
  Up to 200 files at once; 2 concurrent cleans, 4 concurrent inspections.

The optional **AI** button lets text-like files go through an extra LLM rewrite pass:

![AI interface](ui-ai-api.png)

---

## Supported formats

| Kind | Extensions |
| --- | --- |
| Images | png jpg jpeg webp avif heic heif bmp gif tiff tif |
| Documents | pdf docx xlsx pptx odt epub svg html htm md markdown mdx |
| Text | txt text csv tsv json yaml yml toml css js ts tsx jsx mjs cjs py rs go java c h cpp cs kt swift rb php lua pl r sh bash ps1 sql vue svelte astro … (59 types) |
| Audio / video | mp4 mov m4v m4a wav mp3 flac |

The extension table comes from the engine (`GET /api/meta` returns the full list). Files **without**
an extension (screenshots, clipboard dumps, `Dockerfile`, `Makefile`, `.gitignore`, `LICENSE`) are
sniffed by magic bytes first; if that fails but the content really is text (no NUL bytes, <1 %
control characters, ≤32 MB) it is treated as plain text. A file with an extension we do not know
(`.bin`, `.xyz`) is rejected rather than guessed at.

---

## Options

| Option | Effect | Applies to | Default |
| --- | --- | --- | --- |
| Metadata: all / AI-only | keep camera parameters and device data, or strip everything | images, A/V | strip all |
| Destructive audio re-encode | tempo 1.08× + pitch +2 semitones + EQ, output M4A | audio only | off |
| Space homoglyphs → ASCII space | NBSP, thin space, … | text, documents | on |
| NFKC normalisation | full-width → half-width | text, md/html/svg | off |
| Homoglyph folding | Cyrillic / Greek → ASCII | text, md/html/svg | off |
| Strip carrier invisible chars | joiners, variation selectors | text, md/html/svg | off |
| Strip bidi controls | RLO/LRO/PDF … | text, md/html/svg | off |
| Deep-clean embedded images | re-distil images inside PDF/Office | documents | auto |
| Clean text inside documents | off = strip metadata only, leave the body untouched | documents | on |

"Text-like containers" (Markdown / HTML / SVG) go through the engine's container pipeline first
(strip AI keys from frontmatter, embedded data URIs), then the Layer A switches above are applied
again on the text — the report lists both stages separately.

---

## Optional: AI interface (Layer B text rewriting)

The **AI** button in the header is **optional**. Without it, everything above still works. With it,
plain text / Markdown / HTML / SVG get one extra model pass, which is the only way to remove
statistical text watermarks.

16 provider presets fill in the base URL and a model name; "Custom" accepts any OpenAI-compatible
endpoint:

| Provider | Base URL | Example model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com` | gpt-4o-mini |
| DeepSeek | `https://api.deepseek.com` | deepseek-chat |
| Moonshot Kimi | `https://api.moonshot.cn` | kimi-k2-turbo-preview |
| Zhipu GLM | `https://open.bigmodel.cn/api/paas/v4` | glm-4-flash |
| Alibaba DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen-plus |
| Tencent Hunyuan | `https://api.hunyuan.cloud.tencent.com/v1` | hunyuan-turbos |
| iFlytek Spark | `https://spark-api-open.xf-yun.com/v1` | generalv3.5 |
| Baidu Qianfan | `https://qianfan.baidubce.com/v2` | ernie-4.0-8k |
| SiliconFlow | `https://api.siliconflow.cn/v1` | Qwen/Qwen2.5-72B-Instruct |
| OpenRouter | `https://openrouter.ai/api/v1` | deepseek/deepseek-chat |
| Groq | `https://api.groq.com/openai/v1` | llama-3.3-70b-versatile |
| xAI Grok | `https://api.x.ai/v1` | grok-4 |
| Anthropic Claude | `https://api.anthropic.com/v1` | claude-sonnet-4-5 |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | gemini-2.5-flash |
| Ollama (local, in WSL) | `http://host.docker.internal:11434` | qwen3:8b |
| LM Studio (Windows host) | `http://host.docker.internal:1234` | local-model |

Base URLs are completed automatically: paths ending in `/v1`, `/v2`, `/v3`, `/v4` or `/openai` get
`/chat/completions` appended, everything else gets `/v1/chat/completions`. Protocol can be
OpenAI-compatible or native Ollama.

**Rewrite strategies** use the upstream grammar `tactic@strength`, comma separated (strength 0–1):
`paraphrase` (token-level rewording), `humanize` (drop LLM tone), `structural` (outline → rewrite),
`backtranslate` (most thorough, slowest, costliest), `code` (comments/identifiers only), and `mlm`
(needs transformers — not installed, returns an error).

**Keys and privacy**

- The API key lives **only in your browser's localStorage**. It is never written into the container
  or onto the server; each request carries it in an `X-Wm-Llm` header and it is redacted (`***`)
  from any error text.
- With a cloud provider, **the rewritten text is sent to that provider**. Point the base URL at a
  local model if that matters to you.
- "Test connection" sends a minimal request and reports latency, model name and the endpoint that
  was actually used.

---

## Architecture

```
browser
  ↓ http://127.0.0.1:8770
wm-web            UI + proxy layer (Python stdlib, no third-party deps)
  ↓ http://wr-core:8765 (container network only, never published)
wr-core           the official cleaning engine
                  exiftool / qpdf / ghostscript / ffmpeg / c2patool
```

The proxy layer does three things the engine does not:

1. **Binary passthrough.** The page posts the file as the request body; the server streams it to
   disk and chunk-encodes it into the base64 JSON envelope the engine expects. Responses are
   decoded the same way, so the browser only ever sees a `Blob` plus an `X-Wm-Report` header.
   A 49 MB image round-trips in ~8.6 s with a memory peak in the tens of MB.
2. **Per-type routing.** The engine's `/clean` refuses plain text unless a Layer B backend is
   configured, so those files go through the engine's own `text_unicode` for Layer A and the rest
   goes to the engine. Extension-less files are identified by magic bytes.
3. **Capability discovery.** `/api/meta` reports engine version, tool availability, the option
   whitelist and size limits in one call, so the UI can disable what is not available instead of
   letting the user hit an error.

Both containers use `restart: unless-stopped`; `wr-core` publishes no host port and is reachable
only through `wm-web`, which binds `127.0.0.1`.

### HTTP endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/`, `/index.html`, `/app.js`, `/styles.css` | static assets |
| GET | `/api/ping` | **web process only** — used by the container healthcheck so an engine outage doesn't mark the UI dead |
| GET | `/api/health`, `/api/capabilities` | passed through to the engine |
| GET | `/api/meta` | capabilities, option whitelist, limits (cached 60 s) |
| POST | `/api/raw/inspect` | body = raw file, returns inspection JSON |
| POST | `/api/raw/clean` | body = raw file, returns cleaned bytes + `X-Wm-Report` |
| POST | `/api/llm/test` | minimal chat request against the configured AI endpoint |
| POST | `/api/text-clean` | legacy JSON (base64 in/out), kept for scripts |
| POST | `/api/clean`, `/api/inspect`, `/api/clean/batch` … | passed through to the engine |

`/api/raw/*` carries the filename and options in headers — `X-Wm-Name`, `X-Wm-Options` (base64url
JSON, which avoids issues with non-ASCII filenames and long query strings) — plus optional
`X-Wm-Llm` when an AI endpoint is configured (text-like files only).

Response headers: `X-Wm-Report` (base64 report JSON), `X-Wm-Out-Name` (suggested download name),
`X-Wm-Kind`, `X-Wm-Bytes-Out`.

---

## Configuration

**This project (`wm-web`)**

| Variable | Default | Purpose |
| --- | --- | --- |
| `WATERMARKS_UPSTREAM` | `http://wr-core:8765` | engine address |
| `WATERMARKS_SCRIPTS` | `/app/scripts` | engine scripts (reuses `text_unicode` / `rewrite_text`) |
| `WATERMARKS_WEB_PORT` | `8770` | listen port (or `--port`) |
| `WATERMARKS_MAX_INPUT_BYTES` | `268435456` (256 MB) | per-file limit |
| `WATERMARKS_MAX_BATCH_FILES` | `50` | batch limit |
| `WATERMARKS_WEB_TIMEOUT` | `1800` | proxy timeout (seconds) |
| `WATERMARKS_WEB_CONCURRENCY` | `2` | concurrent cleans |

**Engine (`wr-core`, optional)**

| Variable | Purpose |
| --- | --- |
| `WATERMARKS_SERVER_API_KEY` | engine-side auth (empty = none) |
| `WATERMARKS_REWRITE_BACKEND` / `_MODEL` / `_BASE_URL` / `_API_KEY` | engine-side Layer B backend (configuring it in the UI is usually easier) |
| `WATERMARKS_CLEAN_STRATEGY_FILE` | default strategy file (`config/clean_strategy.json`) |
| `WATERMARKS_GUMBEL_KEY` | enable Gumbel text-watermark detection (model-free) |
| `MARKLLM_DIR` / `MARKDIFFUSION_DIR` / `NOAI_WATERMARK_DIR` / `REVERSE_SYNTHID_DIR` | external model backends |

---

## Repository layout

| File | Purpose |
| --- | --- |
| `compose.yaml` | two services, tmpfs, healthcheck, read-only rootfs |
| `compose.allinone.yaml` | single-container mode (engine and UI in one container) |
| `docker/entrypoint.sh` | container entrypoint: optionally starts the embedded engine first |
| `Dockerfile` | UI image based on the official engine image, adds four files |
| `server.py` | UI server + proxy layer (text Layer A, AI interface, Layer B) |
| `index.html` | page skeleton, no framework |
| `styles.css` | theme variables, components, dark mode |
| `app.js` | batching, cancel, re-check, compare, ZIP, preferences, AI settings |
| `llm-relay.py` | optional: bridge a `127.0.0.1`-only model server to the container |
| `start.sh` | Linux/macOS/WSL launcher (`up` / `allinone` / `logs` / `stop` / `status` / `rebuild`) |
| `.env.example` | template for port, bind address, limits and concurrency (copy to `.env`) |
| `LICENSE` | MIT |
| `tools/push-via-api.py` | push a commit through the GitHub Data API (see below) |
| `.ref/` | end-to-end and edge-case tests, plus an OpenAI-compatible mock |

Nothing is written to the host at runtime: the container rootfs is read-only and temporary files
live in `/tmp` (tmpfs), deleted together with the per-request directory.

---

## Development and tests

The regression suites live in `.ref/`:

| Script | Coverage |
| --- | --- |
| `e2e.py` | 39 checks: text / Markdown frontmatter / image / DOCX / audio chain / video / error paths / legacy API |
| `e2e_llm.py` | 18 checks: AI probing, Layer B actually applied, unchanged behaviour when unconfigured, key never leaked |
| `test_split.py` | 11 checks: upstream response parsing edges |
| `test_edges.py` | 9 checks: empty files, extension-less text, long filenames, 8-way concurrency |
| `test_proto.py` | 11 checks: short bodies, `Connection: close` on errors, cross-origin, option semantics, `/api/ping` |
| `test_units.py` | 28 checks: report-header trimming, host fallback rules, filename sanitising, format detection |
| `mock_openai.py` | fake OpenAI-compatible server used by the two `e2e_*.py` suites |

```sh
cd .ref && python e2e.py && python e2e_llm.py && python test_split.py \
  && python test_edges.py && python test_proto.py && python test_units.py
```

116 assertions in total: 39 + 18 + 11 + 9 + 11 + 28. `e2e_llm.py` needs `mock_openai.py` running
(`python mock_openai.py 8791`).

### Security and robustness

- **Origin check** — `POST` with an `Origin` that does not match `Host` gets 403. The service binds
  loopback only, but any web page can `fetch` it (CORS simple requests skip preflight).
- **Short bodies rejected** — a body shorter than its `Content-Length` returns 400 instead of
  cleaning half a file.
- **Errors close the connection** — every 4xx/5xx carries `Connection: close`; error paths usually
  leave unread upload bytes in the socket, which would otherwise be parsed as the next request.
- **Concurrency cap** — 2 concurrent cleans (`WATERMARKS_WEB_CONCURRENCY`); each request uses about
  3.3–3.7× the file size in `/tmp` (tmpfs = RAM). Inspections run 4 at a time.
- **Keys never leave the LAN** — the host-fallback path (when DNS fails) only applies to
  `localhost`, `host.docker.internal`, bare hostnames and private IPs; a cloud hostname that fails
  to resolve just errors out instead of resending `Authorization` elsewhere.
- **120 s I/O timeout** so slow clients cannot hold a worker forever.
- **`X-Wm-Report` capped** — trimmed to 12 KB with `truncated: true` so proxies don't drop the header.
- **ZIP is capped at 4 GB** — the writer is a hand-rolled stored-mode writer with 32-bit offsets
  (no zip64), so oversized batches are refused rather than silently corrupted.

---

## FAQ

| Symptom | Cause / fix |
| --- | --- |
| "engine not connected" | `wm-web` can't reach `wr-core`: check `docker compose logs wr-core` |
| "file too large" | over the 256 MB limit — raise `WATERMARKS_MAX_INPUT_BYTES` (and container memory) |
| AI interface "cannot connect" | press **Test connection** to see the endpoint used; inside the container `host.docker.internal` is resolved via the default gateway |
| AI interface 401/403 | wrong key, or the provider wants a different auth scheme |
| local model unreachable | the model server must listen on `0.0.0.0`; if it only binds `127.0.0.1`, use `llm-relay.py` |
| port 8770 already in use | change the `ports` mapping in `compose.yaml` |

## Sharing on a LAN

Change

```yaml
ports:
  - "127.0.0.1:8770:8770"
```

to

```yaml
ports:
  - "8770:8770"
```

**There is no authentication** — anyone who can reach the port can upload files and read the
results. Only do this on a trusted network, and never expose it to the internet.

## Portability notes

Things to know if you are running this on your own machine:

- **Platform**: the engine image is `linux/amd64` only. On Apple Silicon use
  `DOCKER_DEFAULT_PLATFORM=linux/amd64 docker compose up -d --build` — it works, but under emulation.
- **Docker flavour**: Docker Desktop and a plain dockerd inside WSL both work. The only difference is
  how the container reaches host services: Docker Desktop resolves `host.docker.internal`, WSL's
  dockerd does not, and the proxy layer falls back to the container's default gateway.
- **Port / bind**: change `WM_PORT` and `WM_BIND` in `.env`, not the literals in `compose.yaml`.
- **Memory**: the container's `/tmp` is a tmpfs (i.e. RAM). One clean request uses roughly 3.3–3.7×
  the file size; if RAM is tight use `--tmpfs /tmp:size=512m` or set
  `WATERMARKS_WEB_CONCURRENCY=1`.
- **Read-only rootfs, non-root user**: the container runs as uid 10001 with a read-only filesystem
  and only writes to `/tmp`. Mounting an NFS/SMB share into it breaks that assumption.
- **Windows**: Docker Desktop with the WSL2 backend is enough; `start.sh` runs in Git Bash or WSL,
  or just call `docker compose` directly. The host's system proxy is *not* inherited by containers —
  outbound calls (e.g. to a cloud LLM endpoint) use Docker's own network.
- **No GPU, no model weights required**: pixel-level watermark removal is out of scope anyway.

---

## Offline install

On a machine with network access:

```sh
docker compose build
docker save \
  ghcr.io/guillaumemeyer/watermarks-remover:latest \
  watermark-cleaner-web:local \
  -o images.tar
gzip -9 images.tar        # 1.05 GB → ~400 MB
```

Copy `images.tar.gz` and this repository to the target machine, then:

```sh
gunzip -c images.tar.gz | docker load
docker compose up -d --no-build
```

---

## Out of scope

- **Pixel-level watermarks** (SynthID, Tree-Ring …) need extra ML models that upstream does not ship
  for licensing reasons; the UI shows them as "not deployed".
- **Statistical watermarks in AI text** need a Layer B rewrite backend. The engine ships no default
  strategy file, so plain text gets Layer A only — configure a provider in the AI panel to enable
  Layer B.
- **Text-watermark detectors** (MarkLLM / Gumbel / Claude) are not installed. Gumbel only needs a
  key (`WATERMARKS_GUMBEL_KEY`) and no model; Anthropic's detection API is not public yet.

---

## Credits and licence

- Engine: **[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)** — MIT.
  Image: `ghcr.io/guillaumemeyer/watermarks-remover`.
- Bundled tools inside the engine image: ExifTool, qpdf, Ghostscript, FFmpeg, c2patool.
- The UI, proxy layer and compose wiring in this repository are built on top of that engine and use
  nothing but its public HTTP API.

The code in this repository (`server.py`, `index.html`, `app.js`, `styles.css`, `compose*.yaml`,
`Dockerfile`, `docker/entrypoint.sh`, `start.sh`, `llm-relay.py`, `tools/`) is released under the
**MIT licence** — see [LICENSE](LICENSE). The engine itself is not part of this repository and is
used under its own MIT licence.

Use this only on content **you own or are allowed to process**. Do not use it to dodge compliance
requirements.

## Maintainer notes

`git push` through this machine's HTTP proxy stalls (`CONNECT` takes 20–30 s and the POST phase never
returns), while `api.github.com` on the same proxy is fast. Updates therefore go through the GitHub
Data API:

```sh
git add -A && git commit -m "…"
python tools/push-via-api.py
```
