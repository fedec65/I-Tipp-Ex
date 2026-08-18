#!/usr/bin/env python3
"""Regenerate the committed test fixtures under assets/fixtures/.

Deterministic: running this twice produces byte-identical files. The
generated files are committed; this script exists so they can be rebuilt.

Fixture inventory and the seeded expectations live in tests/.
The committed site/sitemap.xml uses port 8471 as a placeholder; tests copy
the site tree and rewrite the port to their ephemeral server port.
"""

from __future__ import annotations

import os
import struct
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))


def png_chunk(ctype: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + ctype + payload +
            struct.pack(">I", zlib.crc32(ctype + payload) & 0xFFFFFFFF))


def tiny_png(extra_text: bytes | None = None, cabx: bool = False) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    out = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr)
    if extra_text:
        out += png_chunk(b"tEXt", extra_text)
    if cabx:
        out += png_chunk(b"caBX", b"JUMBF-ish synthetic manifest bytes")
    out += png_chunk(b"IDAT", idat) + png_chunk(b"IEND", b"")
    return out


def build() -> None:
    # --- text/zero_width.md -------------------------------------------------
    # Seeded (exact positions asserted in tests/test_audit_layers.py):
    #   line 2: U+200B at col 5, 11, 16          (3x, medium)
    #   line 3: U+00AD at col 5, 8               (2x, low)
    #   line 4: U+202E at col 7, U+202C at col16 (high, bidi-override)
    #   line 5: U+00A0 at col 5, 15              (2x, low, -> space when cleaned)
    #   line 6: U+FEFF at col 10                 (medium, mid-document BOM)
    lines = [
        "Zero-width audit fixture.",
        "zero\u200bwidth\u200bkeep\u200bbrook",
        "soft\u00adhy\u00adphen",
        "bidi: \u202ereversed\u202c done",
        "nbsp\u00a0here nbsp\u00a0too",
        "bom mid: \ufeffhere",
        "end of fixture.",
    ]
    with open(f"{HERE}/text/zero_width.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # --- text/legit_emoji.md -------------------------------------------------
    # Every invisible char here is legitimate (emoji ZWJ sequences, Persian
    # ZWNJ shaping, Devanagari conjunct) -> audit must yield zero findings
    # above informational.
    emoji = (
        "---\n"
        "title: legitimate typography\n"
        "---\n"
        "\n"
        "Emoji family: \U0001F468\u200d\U0001F469\u200d\U0001F467 "
        "and a profession \U0001F469\u200d\u2695\ufe0f with VS16.\n"
        "\n"
        "Persian ZWNJ shaping: \u0645\u06cc\u200c\u062a\u0648\u0627"
        "\u0646\u0633\u062a\u0646\u062f.\n"
        "\n"
        "Devanagari conjunct: \u0915\u094d\u200d\u0937 and "
        "\u0915\u094d\u200d\u0937\u092e.\n"
    )
    with open(f"{HERE}/text/legit_emoji.md", "w", encoding="utf-8") as fh:
        fh.write(emoji)

    # --- img/ ----------------------------------------------------------------
    with open(f"{HERE}/img/c2pa.png", "wb") as fh:
        fh.write(tiny_png(cabx=True))
    with open(f"{HERE}/img/clean.png", "wb") as fh:
        fh.write(tiny_png())

    # --- doc/ai_props.docx ---------------------------------------------------
    with zipfile.ZipFile(f"{HERE}/doc/ai_props.docx", "w",
                         zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/'
                   '2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.'
                   'openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType='
                   '"application/vnd.openxmlformats-officedocument.'
                   'wordprocessingml.document.main+xml"/>'
                   "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxml'
                   'formats.org/officeDocument/2006/relationships/'
                   'officeDocument" Target="word/document.xml"/>'
                   "</Relationships>")
        # The visible body. MUST never be scanned by the metadata audit.
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?>'
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                   'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello'
                   "</w:t></w:r></w:p></w:body></w:document>")
        z.writestr("docProps/core.xml",
                   '<?xml version="1.0"?>'
                   '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.'
                   'org/package/2006/metadata/core-properties" xmlns:dc='
                   '"http://purl.org/dc/elements/1.1/">'
                   "<dc:creator>Test</dc:creator></cp:coreProperties>")
        z.writestr("docProps/app.xml",
                   '<?xml version="1.0"?>'
                   '<Properties xmlns="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/extended-properties">'
                   "<Application>Microsoft Copilot</Application></Properties>")
        z.writestr("docProps/custom.xml",
                   '<?xml version="1.0"?>'
                   '<Properties xmlns="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/custom-properties" xmlns:vt="http://'
                   'schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                   '<property name="ai-model" fmtid="{D5CDD505-2EA9-101B-9397-'
                   '08002B2CF9AE}" pid="2"><vt:lpstr>gpt-4</vt:lpstr></property>'
                   "</Properties>")

    # --- web/generator.html --------------------------------------------------
    with open(f"{HERE}/web/generator.html", "w", encoding="utf-8") as fh:
        fh.write(
            "<!DOCTYPE html>\n<html><head>\n"
            '<meta name="generator" content="WordPress 6.5">\n'
            "</head><body>\n<p>Hello world</p>\n"
            '<div data-ai-generated="true">tagged</div>\n'
            "</body></html>\n")

    # --- site/ ----------------------------------------------------------------
    site = f"{HERE}/site"
    with open(f"{site}/index.html", "w", encoding="utf-8") as fh:
        fh.write(
            "<!DOCTYPE html>\n<html><body>\n"
            "<h1>Title with a zero\u200bwidth space</h1>\n"
            '<div data-ai-generated="true">x</div>\n'
            '<img src="ai.png"> <img src="clean.png">\n'
            "</body></html>\n")
    with open(f"{site}/page2.html", "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html><body><p>Nothing notable.</p>"
                 "</body></html>\n")
    with open(f"{site}/page3.html", "w", encoding="utf-8") as fh:
        fh.write('<!DOCTYPE html>\n<html><head>'
                 '<meta name="generator" content="WordPress 6.5">'
                 "</head><body><p>page3</p></body></html>\n")
    with open(f"{site}/ai.png", "wb") as fh:
        fh.write(tiny_png(extra_text=b"parameters\x00Steps: 20"))
    with open(f"{site}/clean.png", "wb") as fh:
        fh.write(tiny_png())
    # Committed robots.txt deliberately has NO Sitemap: directive (the URL
    # would hardcode a port); a test-time variant exercises that path.
    with open(f"{site}/robots.txt", "w") as fh:
        fh.write("User-agent: *\nDisallow: /private/\n")
    with open(f"{site}/sitemap.xml", "w") as fh:
        fh.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "<url><loc>http://127.0.0.1:8471/index.html</loc></url>\n"
            "<url><loc>http://127.0.0.1:8471/page2.html</loc></url>\n"
            "<url><loc>http://127.0.0.1:8471/page3.html</loc></url>\n"
            "<url><loc>http://127.0.0.1:8471/private/secret.html</loc></url>\n"
            "</urlset>\n")
    os.makedirs(f"{site}/private", exist_ok=True)
    with open(f"{site}/private/secret.html", "w", encoding="utf-8") as fh:
        # Must NEVER be fetched by the crawler (robots-disallowed). The
        # U+200B makes an accidental fetch detectable in audit findings.
        fh.write("<html><body>secretwith\u200bzero-width</body></html>\n")

    print("fixtures written under", HERE)


if __name__ == "__main__":
    build()
