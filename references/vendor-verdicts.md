# Vendor verdicts — statistical-watermark detection (opt-in)

`scripts/detect_vendor.py` asks an external detector whether a text
carries a statistical (token-choice) watermark such as SynthID-Text. It
is opt-in and explicitly-invoked, and it is one of two network-capable
components in the skill (the other is `audit_site.py`). What it returns
are Verdicts — advisory statements from an external detector — never
Findings.

## Why verdicts are not findings

Audit findings are reproducible from the bytes you handed in: same input,
same tool, same result. A vendor verdict is not — the detector is
operated by someone else, under a key you do not hold, and its answer
cannot be re-derived or independently verified. Verdicts therefore:

- are excluded from the summary counts (never counted as findings),
- never appear in audit-script output — only `detect_vendor.py` emits
  them, and only when explicitly run,
- always carry a scope note stating the limits of the check.

The three fixed caveats, printed with every run:

> Vendor verdicts come from a vendor-operated detector; the key stays with the vendor and the result is not independently verifiable.

> MarkLLM checks one scheme under one configuration; a negative result does not rule out other schemes or configs.

> Absence of a verdict proves nothing either way.

## Usage

    python3 scripts/detect_vendor.py <file> --backend gemini|markllm|all
    printf '%s' "$TEXT" | python3 scripts/detect_vendor.py - --backend all

`<file>` is positional; `-` or an omitted file reads stdin. Flags:
`--scheme kgw|synthid` (MarkLLM scheme; default kgw), `--timeout SECONDS`
(per backend, default 30), `--allow-large` (inputs over 1 MiB are
refused otherwise), plus the shared `--json`, `-o/--output PATH`, and
`--max-bytes N`.

## Backend: gemini (vendor oracle)

What it establishes: whether Google's own detector says the text carries
a SynthID-Text watermark — the vendor's answer for Gemini-era output.
The detector key stays with Google; the result is not independently
verifiable.

- Setup: export `ITIPPEX_GEMINI_API_KEY` (required for this backend;
  env-only, never a flag). `ITIPPEX_GEMINI_MODEL` selects the model
  (default `gemini-2.5-flash`).
- How it works: POST to
  `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
  with `generationConfig.taskType: DETECT_TEXT_WATERMARK`; the key
  travels in the `x-goog-api-key` header, never the URL.
- Endpoint caveat: this taskType follows the
  `guillaumemeyer/watermarks-remover` reference implementation; Google
  does not currently document it, so the endpoint shape may drift. The
  backend fails soft (reports the verdict as unavailable) on anything
  unrecognized — it never guesses.
- **Egress**: text leaves the machine when this backend actually fires,
  and an egress notice is printed to stderr at that point. No key → the
  backend reports unavailable and nothing is sent.

## Backend: markllm (research harness)

What it establishes: whether the text scores above threshold for one
specific scheme under one specific configuration — nothing more. A
negative result does not rule out other schemes or other
configurations. Everything runs locally in MarkLLM's own venv; the only
network use is the one-time model download (see `--offline` below).

- Schemes: `kgw` (Kirchenbauer et al.; z-threshold 4.0) and `synthid`
  (SynthID-Text; threshold 0.52). The thresholds live in MarkLLM's own
  config, not in this skill.
- Setup: MarkLLM is never vendored and never auto-installed. Clone
  `THU-BPM/MarkLLM`, create a venv inside the checkout, install
  MarkLLM's dependencies into it, then point the skill at the checkout:

      git clone https://github.com/THU-BPM/MarkLLM.git
      cd MarkLLM
      python3 -m venv .venv
      .venv/bin/pip install -r requirements.txt
      export ITIPPEX_MARKLLM_DIR=/path/to/MarkLLM

  The skill runs `scripts/markllm_adapter.py` with
  `$ITIPPEX_MARKLLM_DIR/.venv/bin/python` as a subprocess and reads one
  JSON object back.
- Offline repeats: run the adapter directly inside the venv with
  `--offline` (sets `HF_HUB_OFFLINE=1`) to use cached models only.
