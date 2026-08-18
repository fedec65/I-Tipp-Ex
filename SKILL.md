---
name: i-tipp-ex
description: Audit text, files, directories, and websites for AI-provenance signals: invisible/zero-width Unicode, bidi overrides, C2PA content credentials, EXIF/XMP/document AI metadata, and generator markers. Use when the user wants to inspect, check, scan, or audit a file, text, folder, or site (via sitemap) for hidden characters, watermark carriers, content credentials, or AI-generation metadata; for editors verifying submissions, compliance checks, publisher site sweeps, or security review of suspicious files. Optionally strips metadata/invisible characters on explicit request, writing new files only.
---

# I-Tipp-Ex

Inspection-first audit tool for AI-provenance signals: invisible and
zero-width Unicode, bidi overrides, C2PA content credentials, EXIF/XMP and
office-document AI metadata, and AI-generator markers — in pasted text,
single files, whole directories, or a website via its sitemap. It is
audit/transparency/security infrastructure: it reveals what is invisible so
a human can decide what it means. It is **not** a watermark-evasion tool;
removal mode exists, is separate, opt-in, and confirmation-gated. Legitimate
uses: editors reviewing submissions, compliance checks that transparency
marking survived a pipeline, security review of suspicious documents
(trojan-source-style tricks), publisher site sweeps of sites you operate,
forensics research.

The name: like Tipp-Ex, it corrects — but it **reveals** what's invisible
before it corrects anything. The audit core never alters input; correction
(removal mode) is a separate set of entry points, run only on explicit
request.

## Routing

| Input | Run |
|---|---|
| Pasted text or a single text-ish file | `python3 scripts/audit_text.py <file>` (omitted file / `-` reads stdin) |
| Single file of any kind (binary or text container) | `python3 scripts/audit_file.py <file>` (routes by magic bytes) |
| A directory / folder | `python3 scripts/audit_dir.py <dir> [--include-hidden]` |
| A URL, host, or "audit my website" | `python3 scripts/audit_site.py <url> --i-am-authorized [flags]` |
| "Is this text watermarked?" (statistical) | `python3 scripts/detect_vendor.py <file> --backend gemini|markllm|all` — opt-in; text leaves the machine for the gemini backend |

For site audits, confirm ownership/authorization with the user FIRST; the
script itself refuses to run (exit 2) without `--i-am-authorized`, because
crawling makes requests against third-party-visible infrastructure.

## Workflow

1. Determine the input type and route per the table above. For text where
   the user cannot provide a file, pipe it: `printf '%s' "$TEXT" |
   python3 scripts/audit_text.py -`.
2. Run the audit. **Never modify the input.** Audits are read-only.
3. Render the human-readable summary in chat (default output). When
   findings exist, or the user asks, save the full report to a file with
   `-o report.md` (or `--json -o report.json`). Site audits ALWAYS save a
   report file.
4. Explain findings in plain language. For "what does this mean?"
   questions, consult `references/provenance-background.md`; for detection
   detail, `references/unicode-catalog.md` and `references/format-notes.md`.
5. Removal mode ONLY if the user explicitly asks to remove/strip/clean.
   Never propose it as the default next step; a neutral "want me to strip
   these?" after reporting findings is acceptable.

## Usage

All audit scripts share: `--json` (machine-readable output), `-o/--output
PATH` (write the report to a file), `--max-bytes N` (default 268435456;
inputs over the cap are truncated and noted).

    # Text layer
    python3 scripts/audit_text.py notes.md --json -o report.json
    printf '%s' "$PASTED" | python3 scripts/audit_text.py -

    # One file (any format; routed by magic bytes)
    python3 scripts/audit_file.py image.png --json
    python3 scripts/audit_file.py document.docx -o findings.md

    # A directory tree (skips dotfiles unless --include-hidden)
    python3 scripts/audit_dir.py ./manuscripts --json -o audit.json

    # A site you own (mandatory authorization flag)
    python3 scripts/audit_site.py https://example.com --i-am-authorized \
        --max-pages 200 --include-assets --delay 0.5 -o site-audit.md

    # Removal mode (opt-in; never in-place; writes <name>.cleaned.<ext>)
    python3 scripts/clean_text.py notes.md --yes
    python3 scripts/clean_file.py image.png -o image.cleaned.png --yes

`audit_site.py` flags: `--i-am-authorized` (required), `--max-pages N`
(default 200), `--max-assets N` (default 100), `--include-assets`
(download and audit linked image/document assets), `--delay SECONDS`
(between requests, default 0.5), `--timeout SECONDS` (per request,
default 20), `--max-resource-bytes N` (per-resource cap, default 50 MiB).

`clean_text.py` / `clean_file.py` flags: `-o/--output PATH`,
`--force` (overwrite existing output), `--yes` (skip interactive
confirmation), `--json`, `--max-bytes N`. Cleaning refuses inputs over
`--max-bytes` rather than truncating.

## Removal mode

Run only on explicit request, only on content the user owns or is
authorized to process. Constraints enforced in code: never in-place
(output defaults to `<name>.cleaned.<ext>`; in-place and symlink
destinations refused), per-run confirmation plan (audit findings, what will
be removed, removal mode, caveat) unless `--yes`, ownership/legal reminder
printed every run, post-clean re-audit of the written file, atomic writes.

Every removal is labelled **verifiable** (post-clean re-audit confirms),
**best-effort** (bytes neutralized; recoverable traces may remain — TIFF
zeroing, PDF without qpdf+exiftool), or **not addressable**. EPUB is
audit-only in v1. Full table: `references/removal-matrix.md`.

Verbatim caveat, always in effect:

> Pixel-domain watermarks and statistical (token-choice) watermarks are NOT
> addressable by any metadata strip; this tool does not rewrite content.

## Honesty rules

- **Findings, not verdicts.** Never state or imply "clean", "safe",
  "AI-free", "pass", or "fail". Report what was found, with severity,
  confidence, and evidence; say "no findings" at most.
- Absence of findings is not proof of anything — statistical watermarks
  cannot be detected without vendor keys, and every text scan carries that
  note.
- **Coverage honesty** for site audits: report audited/discovered counts,
  capping, timeouts, robots-skipped URLs, and cross-host sitemap entries
  dropped (only same-host URLs are audited) from the coverage line.
- **Vendor detector output is advisory** — verdicts are never findings:
  they are excluded from summary counts and always carry scope notes; see
  `references/vendor-verdicts.md`.
- **Optional tools**: `c2patool` (claim generator/assertions/signer
  detail; errors mean absence, findings removed), `exiftool`+`qpdf` (a
  verifiable PDF strip; without them PDF cleaning is labelled best-effort).
  When absent, say what they would have added; the reports note this too.

## References

- `references/unicode-catalog.md` — every detected codepoint/range,
  severities, and false-positive rules (emoji ZWJ/ZWNJ adjacency, Indic/
  Arabic shaping, VS15/VS16 skip, document-initial BOM exemption,
  soft-hyphen ceiling).
- `references/format-notes.md` — per-format parsing notes and gotchas
  (PDF incremental-update caveat, compressed-stream exclusion, DOCX
  metadata-parts-only rule, CMS informational rule, c2patool
  error-means-absence).
- `references/removal-matrix.md` — target/method/label table for removal
  mode.
- `references/vendor-verdicts.md` — opt-in statistical-watermark
  detection (Gemini and MarkLLM backends), setup, and the fixed caveats.
- `references/provenance-background.md` — C2PA, SynthID, EU AI Act
  transparency context, trojan-source background, legitimate use cases.

## Operational notes

- Python 3.10+, standard library only. Network I/O exists only in
  `audit_site.py` and `detect_vendor.py` (both opt-in; stdlib urllib);
  everything else is fully offline.
- Tests: `make test` (42 unittest cases). Fixtures regenerate with
  `make fixtures` (deterministic; committed outputs are the source of
  truth).
