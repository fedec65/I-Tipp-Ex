# Removal matrix (clean_text.py / clean_file.py)

Removal mode is **opt-in only** — audit scripts never import or call the
cleaning code. Every result is labelled one of:

- **verifiable** — a post-clean re-audit of the written output confirms the
  target findings are gone.
- **best-effort** — bytes are neutralized, but container quirks may leave
  recoverable traces; said so plainly.
- **not addressable** — no metadata strip can touch it; stated, never
  offered as a rewrite.

## Matrix

| Target | Method | Label |
|---|---|---|
| Invisible Unicode (Layer A): U+200B, format controls, bidi controls, tag chars, PUA, non-initial U+FEFF | Dropped from the text; exact same detection tables and false-positive function as audit_text, so audit and clean can never disagree | **verifiable** |
| Legitimate joiners: emoji-adjacent ZWJ/ZWNJ, Indic/Arabic-shaping ZWNJ/ZWJ, variation selectors, document-initial BOM | Preserved (kept because audit_text downgrades them to informational) | preserved (not removal targets) |
| Space homoglyphs (U+00A0 etc.) | **Replaced with U+0020**, not deleted | **verifiable** |
| PNG metadata: caBX/c2pa chunks; tEXt/zTXt/iTXt with keywords parameters, prompt, software, comment, xml:com.adobe.xmp, or AI-marker values | Chunks dropped whole; kept chunks copied byte-for-byte (no CRC issues) | **verifiable** |
| JPEG metadata: APP1 (Exif/XMP), APP11 (JUMBF/C2PA), APP13 (Photoshop/IPTC), COM segments | Segments dropped; everything from SOS (entropy data) on copied verbatim | **verifiable** |
| WebP metadata: C2PA, XMP , EXIF chunks | Chunks dropped, RIFF size recomputed | **verifiable** |
| GIF metadata: comment extensions, XMP application extensions | Extensions dropped; image data copied verbatim | **verifiable** |
| TIFF/BigTIFF metadata: tags 0x0131 Software, 0x010E ImageDescription, 0x02BC XMP, 0x8769 EXIF IFD, 0x8825 GPS IFD | Same-length in-place **zeroing** of tag values (and the data they point at); structure and all other tags intact | **best-effort** (in-place tag-value zeroing; full IFD rewriting is deliberately avoided as fragile) |
| SVG: `<metadata>` blocks, `generator` attributes | Targeted string surgery; visible content byte-identical | **verifiable** |
| DOCX: docProps/core.xml, docProps/app.xml (neutralized), docProps/custom.xml, customXml/* (dropped); rest of the zip byte-for-byte | Zip repack | **verifiable** |
| ODT: meta.xml generator/initial-creator/creator/creation-date/printed-by elements | Element removal + zip repack | **verifiable** |
| HTML: `<meta name="generator">` tags, `data-ai*` attributes | Targeted string surgery; visible bytes preserved | **verifiable** |
| Markdown: frontmatter keys generator, model, ai*, claude*, gpt*, llm* (body byte-for-byte) | Line-based frontmatter surgery | **verifiable** |
| PDF — with **both** `exiftool` and `qpdf` on PATH | `exiftool -all=` + `qpdf --linearize` (full rewrite drops orphaned incremental-update bytes) | **verifiable** |
| PDF — without exiftool+qpdf | Same-length in-place blanking of `/Info` literal-string values and XMP packet payloads; report adds the loud note to install qpdf+exiftool for a verifiable strip | **best-effort** |
| EPUB | **Refused** — audit-only format in v1 (container rewriting judged fragile) | refused |
| Unknown binary | **Refused** — no blind byte surgery on an unrecognized container | refused |
| Mixed-script confusable words | **Not addressable** — this tool never rewrites wording | not addressable |
| Statistical (token-choice) text watermarks (e.g. SynthID-Text) | **Not addressable** — see caveat below | not addressable |
| Pixel-domain / perceptual watermarks (e.g. SynthID media watermark embedded in pixels) | **Not addressable** — any removal requires rewriting content, which this tool never does | not addressable |

Advisory *detection* of statistical (token-choice) watermarks is
available via the opt-in `scripts/detect_vendor.py` (see
`references/vendor-verdicts.md`); this does not change the removal
status — they remain not addressable.

## Verbatim caveat (always printed)

> Statistical (token-choice) watermarks such as SynthID-Text cannot be
> detected or verifiably removed; this tool does not rewrite content.

and in clean_file.py:

> Pixel-domain watermarks and statistical (token-choice) watermarks are NOT
> addressable by any metadata strip; this tool does not rewrite content.

## Safety contract (spec §10, enforced by clean_common.py)

- **Never in-place**: output defaults to `<name>.cleaned.<ext>`; a path
  that resolves to the input is refused; symlink destinations are refused;
  existing outputs require `--force`.
- **Per-run confirmation**: the plan (audit findings, what will be removed,
  removal mode, caveat) is printed and a `y/yes` confirmation required;
  non-interactive stdin without `--yes` aborts with guidance.
- **Ownership reminder** printed to stderr on every run: "Intended for
  content you own or are authorized to process; stripping required
  transparency marking may have legal implications in some jurisdictions
  (e.g. EU AI Act deployer obligations)."
- **Atomic writes**: temp file in the destination directory + `os.replace`
  + fsync; temp files cleaned up on failure.
- **Input-size guard**: an input over `--max-bytes` is refused outright for
  cleaning (truncating would be lossy or corrupt the container) — unlike
  audits, which truncate and note it.
- **Post-clean re-audit**: the written output is re-audited; remaining
  findings are reported, and the removed/remaining/not-addressable counts
  appear in the report.
