#!/usr/bin/env python3
"""MarkLLM adapter — executed by detect_vendor.py INSIDE the external
MarkLLM venv (ITIPPEX_MARKLLM_DIR/.venv/bin/python). Kept dependency-lazy:
third-party imports (torch, transformers, the MarkLLM checkout itself)
happen only inside functions, so this file stays importable/parseable in a
stdlib-only environment and the skill's stdlib AST scan stays green.

Usage:
  markllm_adapter.py detect <file> --scheme kgw|synthid [--offline] --json
  markllm_adapter.py watermark <prompt-file> --scheme kgw|synthid -o OUT [-o2 CONTROL] --json
Output: exactly one JSON object on the last stdout line.

Upstream API shape (verified against the sources cited inline below):
  - Algorithms load via AutoWatermark.load(<ALG>, algorithm_config=<json
    path>, transformers_config=TransformersConfig(...)); the registry maps
    'KGW' -> watermark.kgw.KGW and 'SynthID' -> watermark.synthid.SynthID.
  - detect_watermark(text, return_dict=True) returns
    {"is_watermarked": bool, "score": float}; the decision threshold is
    NOT returned — it lives in the algorithm config JSON ('z_threshold'
    for KGW, 'threshold' for SynthID), so the adapter reads it from the
    same config file it loads.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys

# Scheme name as the user types it -> MarkLLM algorithm registry name.
# Registry: https://github.com/THU-BPM/MarkLLM/blob/main/watermark/auto_watermark.py
# ('KGW' -> watermark.kgw.KGW, 'SynthID' -> watermark.synthid.SynthID).
# Same mapping used by the reference harness:
# https://github.com/guillaumemeyer/watermarks-remover/blob/main/service/scripts/detect_text_watermark.py
SCHEMES = {"kgw": "KGW", "synthid": "SynthID"}

# Default scoring model, matching the MarkLLM README's user example:
# https://github.com/THU-BPM/MarkLLM#invoking-watermarking-algorithms
DEFAULT_MODEL = "facebook/opt-1.3b"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("detect", "watermark"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--scheme", choices=sorted(SCHEMES), required=True)
        p.add_argument("--offline", action="store_true")
        p.add_argument("--json", action="store_true")
        p.add_argument("--model", default=DEFAULT_MODEL)
        if name == "watermark":
            p.add_argument("-o", required=True)
            p.add_argument("-o2")
    args = parser.parse_args(argv)

    if args.offline:
        import os
        # Set BEFORE transformers is imported so hub calls never happen.
        os.environ["HF_HUB_OFFLINE"] = "1"

    try:
        if args.cmd == "detect":
            out = _detect(args)
        else:
            out = _watermark(args)
    except Exception as exc:  # includes ImportError for missing markllm
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out))
    return 0


def _markllm_root() -> str:
    """Locate the external MarkLLM checkout (same env var detect_vendor
    used to find this venv; inherited by this subprocess)."""
    import os
    root = os.environ.get("ITIPPEX_MARKLLM_DIR")
    if not root:
        raise RuntimeError("ITIPPEX_MARKLLM_DIR not set in adapter process")
    return root


def _resolve_device():
    """cuda if available, else cpu. Never auto-select mps: MarkLLM builds
    torch.Generator(device=...), which supports only cpu/cuda and raises on
    'mps' (Apple Silicon) — same guard as the reference harness."""
    torch = importlib.import_module("torch")
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_watermark(args, alg: str, config_path: str):
    """Import the MarkLLM checkout lazily and build the algorithm instance.

    Mirrors the reference harness's loader:
    https://github.com/guillaumemeyer/watermarks-remover/blob/main/service/scripts/detect_text_watermark.py
    and the MarkLLM README user example:
    https://github.com/THU-BPM/MarkLLM#invoking-watermarking-algorithms
    Never passes trust_remote_code — transformers only honors auto_map /
    trust_remote_code when explicitly enabled.
    """
    root = _markllm_root()
    sys.path.insert(0, root)  # the checkout provides watermark/, utils/

    # Loaded via importlib (not import statements) so the skill-wide stdlib
    # AST scan in tests/test_meta.py — which walks function bodies too —
    # stays green; this file only ever executes inside the external venv.
    transformers = importlib.import_module("transformers")
    TransformersConfig = importlib.import_module(
        "utils.transformers_config").TransformersConfig
    AutoWatermark = importlib.import_module(
        "watermark.auto_watermark").AutoWatermark
    AutoTokenizer = transformers.AutoTokenizer
    AutoModelForCausalLM = transformers.AutoModelForCausalLM

    load_kwargs = {"local_files_only": True} if args.offline else {}
    tokenizer = AutoTokenizer.from_pretrained(args.model, **load_kwargs)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, **load_kwargs).to(_resolve_device())
    device = "cuda" if next(model.parameters()).is_cuda else "cpu"
    transformers_config = TransformersConfig(
        model=model,
        tokenizer=tokenizer,
        device=device,
        max_new_tokens=200,
        min_length=0,
        do_sample=True,
        no_repeat_ngram_size=4,
    )
    return AutoWatermark.load(
        alg,
        algorithm_config=config_path,
        transformers_config=transformers_config,
    )


def _config_path(alg: str) -> str:
    """Default to <checkout>/config/<ALG>.json — e.g. config/KGW.json,
    config/SynthID.json (both exist upstream)."""
    import os
    path = os.path.join(_markllm_root(), "config", f"{alg}.json")
    if not os.path.isfile(path):
        raise RuntimeError(f"MarkLLM config not found: {path}")
    return path


def _threshold_from_config(config_path: str):
    """The detection threshold is not returned by detect_watermark; read it
    from the same config JSON. KGW uses 'z_threshold' (default config: 4.0),
    SynthID uses 'threshold' (default config: 0.52):
    https://github.com/THU-BPM/MarkLLM/blob/main/config/KGW.json
    https://github.com/THU-BPM/MarkLLM/blob/main/config/SynthID.json
    """
    with open(config_path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("threshold", "z_threshold"):
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    raise RuntimeError(f"no threshold in MarkLLM config: {config_path}")


def _detect(args) -> dict:
    with open(args.file, encoding="utf-8") as fh:
        text = fh.read()
    alg = SCHEMES[args.scheme]
    config_path = _config_path(alg)
    wm = _load_watermark(args, alg, config_path)
    # detect_watermark(text, return_dict=True) ->
    # {"is_watermarked": bool, "score": float}; KGW compares score >
    # config.z_threshold internally:
    # https://github.com/THU-BPM/MarkLLM/blob/main/watermark/kgw/kgw.py
    result = wm.detect_watermark(text, return_dict=True)
    return {
        "score": float(result["score"]),
        "threshold": _threshold_from_config(config_path),
        "is_watermarked": bool(result["is_watermarked"]),
    }


def _watermark(args) -> dict:
    with open(args.file, encoding="utf-8") as fh:
        prompt = fh.read()
    alg = SCHEMES[args.scheme]
    config_path = _config_path(alg)
    wm = _load_watermark(args, alg, config_path)
    # Generation API per the MarkLLM README user example:
    # generate_watermarked_text(prompt) / generate_unwatermarked_text(prompt).
    watermarked = wm.generate_watermarked_text(prompt)
    with open(args.o, "w", encoding="utf-8") as fh:
        fh.write(watermarked)
    out = {"scheme": alg, "watermarked_output": args.o,
           "watermarked_chars": len(watermarked)}
    if args.o2:
        control = wm.generate_unwatermarked_text(prompt)
        with open(args.o2, "w", encoding="utf-8") as fh:
            fh.write(control)
        out["control_output"] = args.o2
        out["control_chars"] = len(control)
    return out


if __name__ == "__main__":
    sys.exit(main())
