# Changelog

All notable changes to I-Tipp-Ex are documented here. This project
follows [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-08-18

### Added

- **Vendor-verdict detection (opt-in)** — `scripts/detect_vendor.py`
  answers "is this text statistically watermarked?" via external
  detectors, as *verdicts* (advisory, never audit findings). Two
  backends:
  - `gemini` — Google's SynthID-Text detection over the Generative
    Language API (`ITIPPEX_GEMINI_API_KEY`, optional
    `ITIPPEX_GEMINI_MODEL`; text leaves the machine with an explicit
    egress notice).
  - `markllm` — same-scheme/same-config research checks against an
    external `THU-BPM/MarkLLM` checkout (`ITIPPEX_MARKLLM_DIR`; KGW and
    SynthID schemes; the skill never vendors or installs MarkLLM —
    `scripts/markllm_adapter.py` runs inside that checkout's own venv).
- `Verdict` report model: verdicts serialize as a separate top-level
  `verdicts` array only when non-empty, so audit-report output is
  unchanged for existing users.
- Contract tests enforcing the offline boundary: network imports are
  permitted only in `audit_site.py` and `detect_vendor.py`, and audit
  scripts are asserted to never emit verdicts.
- Docs: `references/vendor-verdicts.md` (setup, caveats, semantics),
  INSTALL.md env-var table, README and SKILL.md routing.

### Notes

- The Gemini backend follows the reference harness's
  `:generateContent` + `generationConfig.taskType:
  DETECT_TEXT_WATERMARK` shape, which Google does not currently
  document; the backend fails soft (unavailable verdict) on any
  response drift — it never guesses.
- All detection is fail-soft: unconfigured backends, network errors,
  and malformed detector output yield `available: false` verdicts with
  exit code 0.
- `make test` stays fully offline (47 tests).

## [1.0.0] - 2026-08-18

### Added

- Initial public release: layered, read-only provenance audits with a
  structured report (`--json`, severity/confidence taxonomy):
  - **Layer A** — invisible/suspicious Unicode (zero-width, bidi
    overrides, tag characters, PUA, space homoglyphs) with
    false-positive rules for emoji and Indic/Arabic shaping.
  - **Layer B** — AI/generator metadata in PNG, JPEG, WebP, GIF, TIFF,
    SVG, PDF, DOCX, ODT, EPUB, HTML, and Markdown.
  - **Layer C** — C2PA content credentials, with optional `c2patool`
    deep-dive when installed.
  - **Layer D** — whole-website audits via sitemap crawl
    (`audit_site.py`; robots.txt respect, request delay, SSRF
    hardening, honest coverage reporting).
- Explicitly-invoked removal mode (`clean_file.py`, `clean_text.py`):
  never in-place, per-run confirmation, post-clean re-audit.
- Portable skill packaging (`SKILL.md` + stdlib-only CLIs), per-host
  installation docs, and a distributable zip (`dist/i-tipp-ex.skill`).

[1.1.0]: https://github.com/fedec65/I-Tipp-Ex/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/fedec65/I-Tipp-Ex/releases/tag/v1.0.0
