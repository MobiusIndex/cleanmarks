# Third-party notices

CleanMarks is a UI + proxy + compose layer. It does not implement any cleaning logic itself — the
engine, and most of the file-processing tools it calls, come from third parties and are redistributed
unmodified inside the published container image.

This file lists what the image contains, under which license, and where the license text and the
corresponding source can be obtained. The license texts themselves are shipped in the image at
`/app/licenses/` and in this repository under [`licenses/`](licenses/).

## Bundled in the image

| Component | Version | License | Upstream |
| --- | --- | --- | --- |
| watermarks-remover (engine + scripts) | 0.7.0 | MIT | <https://github.com/guillaumemeyer/watermarks-remover> |
| FFmpeg (`ffmpeg`, `ffprobe`) | 7.1.5 (Debian) | GPL-2.0-or-later (`--enable-gpl` build) | <https://ffmpeg.org> · Debian package `ffmpeg` |
| ExifTool | 13.25 | Same terms as Perl: Artistic-1.0 or GPL-1.0-or-later | <https://exiftool.org> |
| qpdf | 12.2.0 | Apache-2.0 | <https://qpdf.readthedocs.io> |
| c2patool | 0.27.15 | Apache-2.0 or MIT (dual) | <https://github.com/contentauth/c2pa-rs> |
| Debian GNU/Linux base (bookworm/trixie) | — | Mixed, per package | <https://www.debian.org/legal/licenses/> · `debian/copyright` in each package |
| Python standard library | 3.14 | PSF-2.0 | <https://docs.python.org/3/license.html> |

## Source availability

Nothing in the table above has been modified by this project. The image is built `FROM` the
maintainer-published engine image (`ghcr.io/guillaumemeyer/watermarks-remover`), so the binaries are
the ones that project distributes.

- Engine source: <https://github.com/guillaumemeyer/watermarks-remover>
- FFmpeg, ExifTool, qpdf, c2patool and every Debian package: the exact source of each binary can be
  obtained from the Debian archive (`https://deb.debian.org/debian/`) or from the projects linked
  above; Debian additionally ships the complete corresponding source for its packages at
  <https://deb.debian.org/debian/README.source> and per-package pages on
  <https://sources.debian.org/>.
- If you need a specific source corresponding to a binary in a released image, open an issue at
  <https://github.com/MobiusIndex/cleanmarks/issues> and it will be provided.

## License texts

| License | File |
| --- | --- |
| MIT (watermarks-remover, © 2026 Guillaume Meyer and contributors) | [`licenses/watermarks-remover-MIT.txt`](licenses/watermarks-remover-MIT.txt) |
| GNU GPL v2 | [`licenses/gpl-2.0.txt`](licenses/gpl-2.0.txt) |
| Apache License 2.0 | [`licenses/apache-2.0.txt`](licenses/apache-2.0.txt) |
| Artistic License | [`licenses/artistic.txt`](licenses/artistic.txt) |

## This project's own license

CleanMarks' own code (`server.py`, `index.html`, `app.js`, `i18n.js`, `styles.css`, the compose files,
the entrypoint and the workflows) is MIT — see [LICENSE](LICENSE).
