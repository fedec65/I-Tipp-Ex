# I-Tipp-Ex

Audit text, files, directories, and websites for AI-provenance signals — invisible Unicode, C2PA content credentials, document metadata, and AI-generator markers.

I-Tipp-Ex is audit/transparency/security infrastructure for editors reviewing submissions, compliance teams verifying that transparency marking survived a pipeline, security reviewers inspecting suspicious documents, and researchers doing provenance forensics. It reveals what is invisible so a human can decide what it means. It is **not** a watermark-evasion tool: the audit core is strictly read-only and never alters input.

The name is a nod to Tipp-Ex: it *can* correct — but it reveals what's invisible first. Correction (removal mode) is a separate, explicitly-invoked set of entry points, never part of an audit run.

## What it detects

Four layers, each reported with severity, confidence, and evidence:

- **A. Invisible / suspicious Unicode** — zero-width characters, bidi overrides and isolates (trojan-source vectors), tag characters, space homoglyphs, private-use-area codepoints, and mixed-script confusables, each with exact `line:col` locations. False-positive handling for legitimate emoji sequences, Indic scripts, and Arabic text.
- **B. AI/generator metadata** — EXIF, XMP, and document-properties markers of AI generation in PNG, JPEG, WebP, GIF, TIFF/BigTIFF, SVG, PDF, DOCX, ODT, EPUB, HTML, and Markdown. Files are routed by **magic bytes**, not extension.
- **C. C2PA content credentials** — JUMBF box detection; optional deep-dive via `c2patool` when installed.
- **D. Whole-website audits** — sitemap-driven crawl of a site you operate, with robots.txt respect, per-request delays, and SSRF hardening (only same-host URLs are audited).

## Requirements & install

- Python 3.10+, **standard library only** — zero pip dependencies.
- Fully offline, except `audit_site.py` (which crawls, by design) and `detect_vendor.py` (opt-in vendor queries, only when explicitly run).
- Optional external tools are used if present, with graceful degradation when absent: `c2patool` (C2PA deep-dive), `exiftool`, `qpdf` (stronger PDF metadata removal).

Install is a clone:

```bash
git clone https://github.com/fedec65/I-Tipp-Ex.git
cd I-Tipp-Ex
```

The repo is also packaged as a portable agent skill (`SKILL.md` at the root). Per-host installation — Claude Code, Claude apps (zip upload), Kimi Code / Kimi Work, Codex CLI, plain terminal — is documented in [INSTALL.md](INSTALL.md). `make dist` builds a clean runtime bundle (`dist/i-tipp-ex.skill`, a zip) for upload-style installs.

## Usage

All audit scripts share `--json` (machine-readable output), `-o/--output PATH` (also write the report to a file), and `--max-bytes N` (inputs over the cap are truncated and noted; default 256 MiB).

```bash
# Text layer: audit a text file, or pipe pasted text (omitted file / "-" reads stdin)
python3 scripts/audit_text.py notes.md
printf '%s' "$PASTED" | python3 scripts/audit_text.py -
```

```bash
# Single file of any kind; routed by magic bytes
python3 scripts/audit_file.py image.png --json
python3 scripts/audit_file.py document.docx -o findings.md
```

```bash
# Directory tree (skips dotfiles unless --include-hidden)
python3 scripts/audit_dir.py ./manuscripts --include-hidden --json -o audit.json
```

```bash
# Whole site via sitemap crawl — authorization flag is mandatory (exit 2 without it)
python3 scripts/audit_site.py https://example.com --i-am-authorized \
    --max-pages 200 --include-assets --delay 0.5 -o site-audit.md
```

`audit_site.py` additional flags: `--max-assets N` (default 100), `--timeout SECONDS` (per request, default 20), `--max-resource-bytes N` (per-resource cap, default 50 MiB).

### Vendor verdicts (opt-in)

Statistical (token-choice) watermarks cannot be detected from the bytes alone — that takes an external detector. `detect_vendor.py` is the opt-in entry point for it, and it returns **verdicts, never findings** (advisory only, excluded from summary counts, always with scope notes):

```bash
# gemini backend: Google's SynthID-Text detector — text leaves the machine; key required
export ITIPPEX_GEMINI_API_KEY=...
python3 scripts/detect_vendor.py notes.md --backend gemini

# markllm backend: external THU-BPM/MarkLLM checkout, runs locally in its own venv
export ITIPPEX_MARKLLM_DIR=/path/to/MarkLLM
python3 scripts/detect_vendor.py notes.md --backend markllm --scheme kgw
```

Environment variables: `ITIPPEX_GEMINI_API_KEY` (required for the gemini backend), `ITIPPEX_GEMINI_MODEL` (default `gemini-2.5-flash`), `ITIPPEX_MARKLLM_DIR` (path to an external MarkLLM checkout containing `.venv/bin/python`; MarkLLM is never vendored or auto-installed). Flags: `--scheme kgw|synthid` (default kgw), `--timeout` (default 30s), `--allow-large` (inputs over 1 MiB are refused otherwise).

Caveats, always in effect: a vendor verdict comes from a vendor-operated detector and is not independently verifiable; MarkLLM checks one scheme under one configuration, so a negative result does not rule out other schemes or configs; absence of a verdict proves nothing either way. The gemini backend's endpoint shape follows an undocumented task type and fails soft (verdict unavailable) on anything unrecognized; when it actually fires, an egress notice prints to stderr — no key, no egress. Setup and full detail: `references/vendor-verdicts.md`.

## Removal mode

`clean_text.py` / `clean_file.py` strip invisible characters and metadata — **only when explicitly invoked**. Constraints enforced in code:

- Never in-place: output defaults to `<name>.cleaned.<ext>`; in-place and symlink destinations are refused.
- Per-run confirmation plan (findings, what will be removed, caveat) unless `--yes` is passed.
- An ownership/legal reminder is printed every run; use only on content you own or are authorized to process.
- After writing, the output file is re-audited and every removal is labelled **verifiable** (post-clean re-audit confirms), **best-effort** (bytes neutralized; recoverable traces may remain), or **not addressable**.

What removal does **not** do:

- Statistical (token-choice, SynthID-Text-class) watermarks are **not addressable** — they cannot be removed without rewriting content, and this tool does not rewrite content.
- Pixel-domain watermarks are **not addressable** by any metadata strip.
- EPUB is audit-only in v1.

Flags: `-o/--output PATH`, `--force` (overwrite existing output), `--yes`, `--json`, `--max-bytes N` (cleaning *refuses* oversized inputs rather than truncating). Full per-format matrix: `references/removal-matrix.md`.

## Honesty & limitations

- **Findings, not verdicts.** Reports never claim "clean", "safe", "AI-free", "pass", or "fail" — they describe what was found, with evidence. "No findings" is the strongest statement made.
- Absence of findings proves nothing about statistical watermarks, which cannot be detected without vendor keys; every text scan carries that note.
- Site audits state coverage honestly: audited/discovered counts, capping, timeouts, robots-skipped URLs, and cross-host sitemap entries dropped.

## Development

```bash
make test      # 42 stdlib unittest tests, fully offline
make fixtures  # regenerate assets/fixtures/
```

Layout:

- `scripts/` — the CLIs (`audit_text.py`, `audit_file.py`, `audit_dir.py`, `audit_site.py`, `clean_text.py`, `clean_file.py`, shared `report.py`)
- `references/` — detection catalogues and background (`unicode-catalog.md`, `format-notes.md`, `provenance-background.md`, `removal-matrix.md`)
- `assets/fixtures/` — generated test fixtures
- `tests/` — stdlib `unittest` suite

Scripts are host-neutral and portable; everything runs offline except `audit_site.py` and `detect_vendor.py`.

## License

AGPL-3.0 — see [LICENSE](LICENSE).
