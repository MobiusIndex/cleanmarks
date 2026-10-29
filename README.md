# Watermarks Remover — Web UI

**English** · [简体中文](README.zh-CN.md)

A self-hosted web UI for the **[watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**
cleaning engine — strips C2PA / EXIF / XMP / generator metadata and invisible Unicode from images,
documents, audio and video, entirely on your own machine.

> **Not a fork.** This is a front-end + orchestration layer on top of the official image
> `ghcr.io/guillaumemeyer/watermarks-remover` (MIT). The engine is not bundled here — no model
> weights, no API keys, no telemetry.

![Web UI](ui-final.png)

*Bilingual UI (the `EN` button in the header switches at runtime); screenshots show English.*

---

## Quick start

```sh
git clone https://github.com/MobiusIndex/watermarks-remover-webui && cd watermarks-remover-webui
docker compose up -d --build      # first run pulls the engine image (~1 GB)
```

Open <http://127.0.0.1:8770>. Needs Docker 24+ with Compose v2 and ~3 GB of disk.

Two ways to run it:

| Mode | Command | Good for |
| --- | --- | --- |
| Two containers (default) | `docker compose up -d --build` | long-running; a UI crash can't take the engine down |
| Single container | `docker compose -f compose.allinone.yaml up -d --build` | one command, engine + UI in one container |

Port, bind address, size limits and concurrency live in `.env` (`cp .env.example .env`); both
`compose*.yaml` and `start.sh` read it. `./start.sh up|allinone|logs|stop|status|rebuild` wraps the
common commands.

---

## What it does

- Removes C2PA / Content Credentials manifests
- Removes EXIF / XMP / generator metadata (Midjourney, Stable Diffusion, ComfyUI …)
- Cleans invisible Unicode: zero-width characters, bidi controls, homoglyphs, odd spaces
- Optional: **Layer B text rewriting** through an LLM you configure
- Optional: destructive audio re-encode (tempo + pitch)

**What it does not do** — and says so in the UI instead of pretending:

- Pixel-level watermarks (SynthID, Tree-Ring …) — upstream ships no models for licensing reasons
- Text-watermark *detection* (MarkLLM / Gumbel / Claude) — not installed
- Anything that helps you dodge compliance rules — use it only on content you own or may process

---

## Supported formats

| Kind | Extensions |
| --- | --- |
| Images | png jpg jpeg webp avif heic heif bmp gif tiff tif |
| Documents | pdf docx xlsx pptx odt epub svg html htm md markdown mdx |
| Text | txt json yaml csv py js ts go rs java c cpp … (59 types) |
| Audio / video | mp4 mov m4v m4a wav mp3 flac |

Extension-less files (screenshots, `Dockerfile`, `.gitignore`) are sniffed by magic bytes, then
treated as text if that fails; an unknown *extension* (`.bin`, `.xyz`) is rejected rather than guessed.

---

## Options

| Option | Effect | Default |
| --- | --- | --- |
| Metadata: all / AI-only | strip everything, or keep camera data | strip all |
| Destructive audio re-encode | 1.08× tempo + 2 semitones, output M4A | off |
| Space homoglyphs → ASCII space | NBSP, thin space → plain space | on |
| NFKC normalisation | full-width → half-width (alters the text) | off |
| Homoglyph folding | Cyrillic / Greek → ASCII | off |
| Strip carrier invisible chars | joiners, variation selectors | off |
| Strip bidi controls | RLO/LRO/PDF … | off |
| Deep-clean embedded images | re-distil images inside PDF/Office | auto |
| Clean text inside documents | off = metadata only, body untouched | on |

---

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `WATERMARKS_UPSTREAM` | `http://wr-core:8765` | engine address |
| `WATERMARKS_WEB_PORT` | `8770` | listen port |
| `WATERMARKS_MAX_INPUT_BYTES` | `268435456` (256 MB) | per-file limit |
| `WATERMARKS_MAX_BATCH_FILES` | `50` | batch limit |
| `WATERMARKS_WEB_CONCURRENCY` | `2` | concurrent cleans |
| `WATERMARKS_WEB_TIMEOUT` | `1800` | upstream timeout (s) |

Engine-side variables (Layer B backend, detectors, external model dirs): see
[docs/details.md › Configuration](docs/details.md#configuration).

---

## Optional: AI text rewriting

Text files can get one extra model pass (Layer B) — the only way to remove statistical text
watermarks. Off by default. Configure a provider in the **AI** panel: 16 presets plus any
OpenAI-compatible endpoint. The key stays in your browser (`localStorage`) and travels in a request
header — never written to the container or the server.

Provider list, rewrite strategies and the local-model network setup:
[docs/details.md › AI interface](docs/details.md#ai-interface-layer-b-text-rewriting).

---

## Documentation

- [Architecture & HTTP endpoints](docs/details.md#architecture)
- [Repository layout](docs/details.md#repository-layout) · [Portability notes](docs/details.md#portability-notes)
- [Development & tests](docs/details.md#development-and-tests) — 116 assertions
- [Offline install](docs/details.md#offline-install) · [FAQ](docs/details.md#faq) · [LAN sharing](docs/details.md#sharing-on-a-lan)

## Credits and licence

Engine: **[guillaumemeyer/watermarks-remover](https://github.com/guillaumemeyer/watermarks-remover)**
(MIT), image `ghcr.io/guillaumemeyer/watermarks-remover`. This repository's own code (`server.py`,
`index.html`, `app.js`, `i18n.js`, `styles.css`, `compose*.yaml`, `Dockerfile`, `docker/`, `start.sh`,
`llm-relay.py`, `tools/`) is **MIT** — see [LICENSE](LICENSE).

Use it only on content you own or are allowed to process.
