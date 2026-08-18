# Provenance background — what these signals mean

Neutral, factual background for interpreting audit findings. None of this
is legal advice.

## C2PA / Content Credentials

C2PA (Coalition for Content Provenance and Authenticity) is a
specification for cryptographically signed provenance information attached
to media — who/what created or edited a file, with what tools, and when.
The consumer-facing brand is **Content Credentials**. A C2PA *manifest* is
a signed set of assertions stored inside the file itself, typically in a
JUMBF container: a `caBX` chunk in PNG, APP11 in JPEG, a `C2PA` chunk in
WebP, or embedded in an XMP packet.

Finding one means: this file carries (or claims to carry) content
credentials. It does **not** mean the content is AI-generated — C2PA
assertions also cover camera capture and conventional editing. The audit
reports the manifest's presence; when the optional `c2patool` is
installed, it also surfaces the claim generator, assertion labels, and
signer. Signatures are not cryptographically validated here — c2patool's
own output is the reference for that.

## SynthID and statistical watermarks

SynthID is Google DeepMind's family of watermarking techniques:

- **Text (SynthID-Text)**: a *statistical* or token-choice watermark. The
  generator subtly biases which of several near-equivalent tokens it emits;
  detection requires the vendor's private key to score the sequence. This
  is why the audit always states: absence of a detectable watermark proves
  nothing — you cannot rule one in or out without the key, and neither can
  any removal claim about it.
- **Images/audio/video**: pixel- (or sample-) domain watermarks embedded in
  the content itself, designed to survive resizing, compression, and
  edits. They are likewise detectable only with the vendor's detector, and
  removing them would require rewriting the content — which this tool
  never does.

## EU AI Act transparency context

The EU AI Act (Regulation (EU) 2024/1689) imposes transparency obligations
on providers and deployers of AI systems — including Article 50's
requirements to mark AI-generated or manipulated output (in a
machine-readable format where feasible) and to disclose deep fakes.
Deployers of generative systems can therefore carry obligations to keep
marking attached to content they publish.

That makes *verifying that transparency marking survived a publishing
pipeline* a legitimate, even necessary, audit: a newsroom or agency that
must mark AI-generated imagery can use this tool to check that the marks
(stripped by some CMS resizing step, say) are still present on the live
site. The same capability can be used to strip marks — which is why
removal mode is separate, opt-in, confirmation-gated, and preceded by an
ownership/legal reminder every run.

## Trojan Source and homoglyph attacks

"Trojan Source" (Boucher & Anderson, Cambridge, 2021;
CVE-2021-42574/42694) showed that Unicode bidi-override characters and
Cyrillic/Greek homoglyphs can make source code — and by extension any
reviewed text — **read differently to humans than it behaves to
compilers/interpreters**. A reviewer sees one thing; the machine parses
another. The same trick works in contracts, changelogs, and any document
where a human's visual read is the control. This is why the audit flags
bidi controls at high severity and mixed-script words as probable
homoglyphs, while acknowledging legitimate uses (scientific notation,
loanwords, right-to-left typesetting).

## Invisible-Unicode watermarks and hidden payloads

Zero-width characters (U+200B/200C/200D/FEFF), tag characters, and PUA
codepoints are invisible in virtually every renderer but survive
copy-paste. Known uses include **steganographic watermarks** (encoding an
ID in which invisible characters appear where), hidden prompt-injection
payloads, and tracker beacons. They also occur innocently: BOMs at
document start, emoji ZWJ sequences, Indic/Arabic shaping joiners. The
false-positive rules in `unicode-catalog.md` exist precisely because
flagging legitimate typography would make the audit useless.

## Legitimate use cases

- **Editors reviewing submissions** — checking manuscripts/articles for
  hidden characters or undisclosed generator metadata before publishing.
- **Compliance** — verifying required transparency marking is present (or
  documenting that it was) across published content.
- **Security review** — inspecting suspicious documents/code for
  trojan-source-style tricks before a human relies on their visual read.
- **Publisher site sweeps** — auditing a site you operate (via sitemap)
  for invisible-character injections or generator markers across pages.
- **Forensics research** — documenting what provenance signals a corpus
  does or does not carry.

If a user's goal is to evade disclosure obligations they are subject to,
say so and decline the removal step; the tool's own reminders already
frame this.
