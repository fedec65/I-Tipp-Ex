# Unicode detection catalog (Layer A)

Everything `scripts/audit_text.py` (`scan_text`) detects, with the exact
severity, category, and false-positive handling implemented in the code.
The same tables drive `clean_text.py`, so audit and removal can never
disagree.

Findings are aggregated per (codepoint, severity, confidence, category,
note): repeated occurrences of the same codepoint collapse into one finding
whose evidence reads `U+XXXX NAME ×N` and whose note lists up to 20
`line L, col C` locations (`+M more` beyond that). Each finding carries a
~80-character context snippet in which invisible characters are rendered
visibly as `<U+XXXX>`.

## Zero-width characters (category: invisible-unicode)

| Codepoint | Name | Severity | Confidence | False-positive rules |
|---|---|---|---|---|
| U+200B | ZERO WIDTH SPACE | medium | confirmed | none — always reported |
| U+200C | ZERO WIDTH NON-JOINER | medium / informational | confirmed / informational | downgraded to **informational** when adjacent to emoji-sequence characters or Indic/Arabic script characters (see below) |
| U+200D | ZERO WIDTH JOINER | medium / informational | confirmed / informational | same downgrade rule as U+200C |
| U+FEFF | ZERO WIDTH NO-BREAK SPACE (BOM) | medium | confirmed | **exempt as the very first character** of the document (a legitimate BOM); reported otherwise with note "not at document start" |

## C1/Cf format controls (category: invisible-unicode)

| Codepoint | Name | Severity | Confidence | Notes |
|---|---|---|---|---|
| U+00AD | SOFT HYPHEN | low | confirmed | **never reported above low**; note says it may be legitimate hyphenation |
| U+180E | MONGOLIAN VOWEL SEPARATOR | medium | confirmed | |
| U+2060 | WORD JOINER | medium | confirmed | |
| U+2061 | FUNCTION APPLICATION | medium | confirmed | |
| U+2062 | INVISIBLE TIMES | medium | confirmed | |
| U+2063 | INVISIBLE SEPARATOR | medium | confirmed | |
| U+2064 | INVISIBLE PLUS | medium | confirmed | |

## Bidi controls (category: bidi-override)

All **high / confirmed**, with note "can visually reorder text; review
surrounding content":

| Codepoint | Name |
|---|---|
| U+202A | LEFT-TO-RIGHT EMBEDDING |
| U+202B | RIGHT-TO-LEFT EMBEDDING |
| U+202C | POP DIRECTIONAL FORMATTING |
| U+202D | LEFT-TO-RIGHT OVERRIDE |
| U+202E | RIGHT-TO-LEFT OVERRIDE |
| U+2066 | LEFT-TO-RIGHT ISOLATE |
| U+2067 | RIGHT-TO-LEFT ISOLATE |
| U+2068 | FIRST STRONG ISOLATE |
| U+2069 | POP DIRECTIONAL ISOLATE |

## Tag characters (category: invisible-unicode)

- Range **U+E0000–U+E007F** — **high / confirmed**, note "tag characters can
  encode hidden payloads". U+E0001 is named LANGUAGE TAG, the rest TAG
  CHARACTER.

## Private Use Area (category: invisible-unicode)

- Ranges **U+E000–U+F8FF**, **U+F0000–U+FFFFD**, **U+100000–U+10FFFD** —
  **high / confirmed**, note "private use codepoint in prose; meaning is
  font-defined".

## Space homoglyphs (category: homoglyph)

All **low / probable**, note "space-like character where a regular space is
expected; may be legitimate typography":

U+00A0 NO-BREAK SPACE, U+2000 EN QUAD, U+2001 EM QUAD, U+2002 EN SPACE,
U+2003 EM SPACE, U+2004 THREE-PER-EM SPACE, U+2005 FOUR-PER-EM SPACE,
U+2006 SIX-PER-EM SPACE, U+2007 FIGURE SPACE, U+2008 PUNCTUATION SPACE,
U+2009 THIN SPACE, U+200A HAIR SPACE, U+202F NARROW NO-BREAK SPACE,
U+205F MEDIUM MATHEMATICAL SPACE, U+3000 IDEOGRAPHIC SPACE.

## Mixed-script confusable words (category: homoglyph)

- Words matching Latin + Greek and/or Cyrillic letters where **both Latin
  and at least one of Cyrillic/Greek appear** — **medium / probable**.
- Evidence names the word and each foreign letter (`Cyrillic а U+0430`
  style); the note reminds that this can be legitimate in scientific
  notation or loanwords. Greek = U+0370–U+03FF, Cyrillic = U+0400–U+04FF,
  Latin = ASCII letters plus U+00C0–U+00FF (excluding × and ÷).

## Explicitly skipped (never findings)

- **Variation selectors** U+FE00–U+FE0F (VS1–VS16, incl. VS15/VS16 emoji
  text/emoji presentation) and U+E0100–U+E01EF are skipped before any
  classification — legitimate after emoji bases.

## ZWJ/ZWNJ false-positive rules (exact)

A ZWJ (U+200D) or ZWNJ (U+200C) is downgraded to **informational /
informational** with an explanatory note when an **immediately adjacent**
character (previous or next) is:

- in an emoji range: U+1F000–U+1FAFF, U+2600–U+27BF, U+2B00–U+2BFF,
  U+FE00–U+FE0F, U+1F1E6–U+1F1FF (regional indicators), U+E0020–U+E007F
  (subdivision-flag tags); or
- one of the emoji-adjacent singles U+200D, U+200C (chained joiners),
  U+20E3 (combining keycap), U+2640/U+2642 (female/male sign), U+2695
  (staff of aesculapius), U+2764 (heavy black heart) — "adjacent to emoji
  sequence characters; legitimate ZWJ/ZWNJ use"; or
- in an Indic/Arabic script range: Arabic U+0600–U+06FF, U+0750–U+077F,
  U+08A0–U+08FF, Arabic presentation forms U+FB50–U+FDFF and
  U+FE70–U+FEFF, Devanagari U+0900–U+097F, Bengali U+0980–U+09FF,
  Gurmukhi U+0A00–U+0A7F, Gujarati U+0A80–U+0AFF, Oriya U+0B00–U+0B7F,
  Tamil U+0B80–U+0BFF, Telugu U+0C00–U+0C7F, Kannada U+0C80–U+0CFF,
  Malayalam U+0D00–U+0D7F, Sinhala U+0D80–U+0DFF — "adjacent to
  Indic/Arabic script characters; required for shaping".

This is what keeps family/profession emoji ZWJ sequences, Devanagari
conjuncts like क्ष, and Persian ZWNJ usage out of the actionable findings.

## Standing caveat attached to every text scan

Every report that scanned text carries this note verbatim:

> Statistical (token-choice) watermarks such as SynthID-Text cannot be
> detected without the vendor's private key; their absence here proves
> nothing either way.
