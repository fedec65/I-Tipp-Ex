# Per-format parsing notes (Layers B + C)

How `scripts/audit_file.py` routes and parses each container. Routing is
**by magic bytes / structure, never by file extension** (`detect_container`).
All parsers are hand-rolled on the standard library; nothing is executed
from the input.

## Routing table

| Container | Detected by |
|---|---|
| png | `\x89PNG\r\n\x1a\n` signature |
| jpeg | `\xff\xd8\xff` (SOI) |
| webp | `RIFF` + `WEBP` at offset 8 |
| gif | `GIF8` header |
| tiff | `II*\0` / `MM\0*` (classic) or `II+\0` / `MM\0+` (BigTIFF) |
| pdf | `%PDF` |
| docx | ZIP whose namelist has `word/document.xml` |
| odt | ZIP whose `mimetype` starts `application/vnd.oasis.opendocument` |
| epub | ZIP with `META-INF/container.xml` and a `.opf` entry |
| svg | text starting with `<?xml` containing `<svg`, or `<svg` at start |
| markdown | text starting with a `---` frontmatter fence |
| html | text starting `<!doctype html` / `<html`, or a `<meta` tag in the first KB |
| text | anything textual that matched none of the above |
| unknown-binary | binary magic that matched none of the above |

Unrecognized binaries get **no metadata scan** — the report says so instead
of guessing.

## PNG

Walks chunk-by-chunk. `caBX` (or a chunk named `c2pa`) → c2pa-manifest
finding (medium). `tEXt`/`zTXt`/`iTXt` keywords `parameters` or `prompt`
whose value contains prompt-field markers (`steps:`, `sampler`,
`cfg scale`, `negative prompt`, `seed:`) → generator-meta finding
(AUTOMATIC1111-style generation parameters). Keyword
`xml:com.adobe.xmp` is scanned as XMP. Other keywords (`software`,
`comment`, `parameters`, `prompt`, `title`, `description`, `author`) go
through the shared metadata-value check (AI markers → medium ai-metadata;
otherwise informational generator-meta).

## JPEG

Walks markers until SOS (image data). APP1 `Exif\0\0` payloads are parsed
as TIFF IFD0; APP1 XAP/Adobe payloads as XMP; APP11 with `JP` header →
c2pa-manifest (JUMBF box); COM segments go through the metadata-value
check.

## WebP

Walks RIFF chunks. `C2PA` chunk → c2pa-manifest; `XMP ` chunk → XMP scan;
`EXIF` chunk → TIFF IFD0 scan.

## GIF

Comment extensions (0x21/0xFE) → metadata-value check. Application
extensions (0x21/0xFF) with `XMP` in the app id → XMP scan; other
application-extension data is checked for AI markers directly.

## TIFF / BigTIFF

Minimal IFD0 reader handling classic (magic 42, 12-byte entries) and
BigTIFF (magic 43, 20-byte entries, 8-byte offsets) in either endianness,
capped at 512 entries. Tags read: 0x010F Make, 0x0110 Model, 0x0131
Software, 0x010E ImageDescription (ASCII/byte/undefined types only),
0x02BC XMP → XMP scan. IFD1/EXIF sub-IFDs are not parsed.

## SVG

Parsed as XML (parse failure → informational finding, scan skipped).
Root namespace attributes containing `inkscape`/`sodipodi` → informational
editor-metadata note. Any `generator` attribute → metadata-value check.
`<metadata>`, `<rdf>`, `<title>`, `<desc>` text: AI markers → medium;
`<metadata>` content is also XMP-scanned.

## PDF — byte-level scan, no full parser

- `/Producer`, `/Creator`, `/Title`, `/Author`, `/CreationDate` literal
  string values are regex-extracted (with PDF escape handling) and go
  through the metadata-value check.
- The first `<?xpacket … <?xpacket end` span is scanned as an XMP packet.
- **Compressed-stream exclusion**: whole-file AI-marker scans blank out
  `stream…endstream` spans that follow a `/FlateDecode` filter, so marker
  matches come only from uncompressed structures. The finding location
  says "PDF (outside compressed streams)".
- **Incremental-update caveat**: if the file contains more than one `%%EOF`
  (i.e. it has been incrementally edited) and markers were found, the note
  adds: exiftool-style incremental edits can leave recoverable metadata
  bytes outside the live object graph — orphaned bytes from earlier
  revisions remain in the file and stay recoverable.

## DOCX — metadata parts only

Only metadata parts are inspected: `docProps/core.xml` (`creator`,
`lastmodifiedby`), `docProps/app.xml` (`Application` — with its own
informational branch when no AI markers, plus `appversion`, `company`),
`docProps/custom.xml` custom properties by name, and `customXml/*.xml`
entries (`creator`, `generator`, `tool`). **Document body text
(`word/document.xml`) is never scanned** — this is by design; use
`audit_text.py` on extracted text for the text layer.

## ODT

`meta.xml` fields `generator`, `initial-creator`, `creator`,
`creation-date`: AI markers → medium ai-metadata, otherwise informational
generator-meta.

## EPUB

`.opf` parts: `creator`, `generator`, `meta` elements via the
metadata-value check. Every `.xhtml/.html/.htm` part: `<meta
name="generator">` checks plus JSON-LD script blocks scanned for AI
markers. EPUB is **audit-only in v1** — `clean_file.py` refuses it.

## HTML

`<meta name="generator">`: AI markers → medium ai-metadata; known CMS
generator (wordpress, drupal, joomla, hugo, jekyll, wix, squarespace,
shopify, ghost, blogger, typo3) → **informational** with the note "CMS
generator tag — informational, not an AI finding"; any other non-empty
value → informational "not a known CMS, no AI markers". Any `data-ai*`
attribute → medium ai-metadata. JSON-LD script blocks scanned for AI
markers. Textual containers (html/svg/markdown/text) additionally get the
full Layer A `scan_text` pass.

## Markdown

YAML frontmatter only (line-based; no YAML dependency). Keys matching
`generator|model|ai[-_].*|claude.*|gpt.*|llm.*` (case-insensitive), or any
key whose value contains AI markers → medium ai-metadata with the
frontmatter line number. Then Layer A `scan_text` runs on the whole file.

## Layer C: c2patool enrichment (optional external tool)

When a c2pa-manifest finding exists and `c2patool` is on PATH, it is run on
the file. **Error means absence**: a nonzero exit, or "No claim found" /
"No JUMBF data found" in the output, causes the chunk-scan findings to be
**removed** and a note recorded — a stale or malformed chunk is not a
manifest. On success, the finding's note is enriched with `claim_generator`,
assertion labels, and signer identity. c2patool absent → note suggesting
installation for full claim detail; findings stand as chunk-scan results.

## Marker lists (for reference)

- **AI_MARKERS** (core, matched anywhere in metadata values): stable
  diffusion, dall-e, dall·e, midjourney, comfyui, automatic1111, novelai,
  firefly, copilot, chatgpt, gpt-3/4/5, openai, claude, anthropic, gemini,
  bard, jasper, copy.ai, writesonic, leonardo.ai, ideogram, sdxl,
  ai-generated, generated by ai, llm, llms.txt (case-insensitive).
- **PROMPT_FIELD_MARKERS** (only inside `parameters`/`prompt` fields):
  steps:, sampler, cfg scale, negative prompt, seed:.
