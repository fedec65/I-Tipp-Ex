# Installing I-Tipp-Ex

I-Tipp-Ex is a portable agent skill: a folder with a minimal `SKILL.md`
(frontmatter: `name` + `description` only) plus standalone Python 3.10+
stdlib-only CLIs under `scripts/`. There is nothing to compile and no
dependencies to install — "installation" means putting the folder where
your agent host looks for skills, or uploading the zip.

## Get the files

```bash
git clone https://github.com/fedec65/I-Tipp-Ex.git
```

Or download the ready-made runtime bundle (`i-tipp-ex.skill`, a zip with
only `SKILL.md`, `scripts/`, `references/`, `assets/` — no tests, no git
history) directly:
[i-tipp-ex.skill (latest release)](https://github.com/fedec65/I-Tipp-Ex/releases/latest/download/i-tipp-ex.skill)
— the easiest option for Claude Code / Claude app users. Older versions
are on the [Releases
page](https://github.com/fedec65/I-Tipp-Ex/releases). You can also
rebuild it yourself:

```bash
make dist        # produces dist/i-tipp-ex.skill (a zip)
```

## Claude Code (CLI)

Copy the folder into a skills directory and start a new session:

```bash
# personal — available in all projects:
cp -r I-Tipp-Ex ~/.claude/skills/i-tipp-ex

# or project-scoped:
cp -r I-Tipp-Ex /path/to/project/.claude/skills/i-tipp-ex
```

Claude Code reads the `description` frontmatter to decide when to trigger
the skill. No further configuration is needed.

## Claude apps (web / desktop / Cowork)

Skills in the Claude apps are uploaded as a zip:

1. Build the bundle: `make dist` (or download the release artifact).
2. Rename `dist/i-tipp-ex.skill` to `i-tipp-ex.zip` if the file picker
   requires a `.zip` extension.
3. In the app: **Settings → Capabilities → Skills → Upload skill** and
   select the zip.

The same bundle works in any Claude surface that supports Agent Skills.

## Kimi Code / Kimi Work

Copy the folder into one of the skills directories:

```bash
# user scope:
cp -r I-Tipp-Ex ~/.kimi-code/skills/i-tipp-ex
# or:
cp -r I-Tipp-Ex ~/.agents/skills/i-tipp-ex

# project scope:
cp -r I-Tipp-Ex /path/to/project/.agents/skills/i-tipp-ex
```

All internal references in `SKILL.md` are relative to the skill root, so
the folder works unchanged at any of these locations.

## DeepSeek (DeepSeek Harness)

DeepSeek's official open-source agent harness
([deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness),
developer preview) supports `SKILL.md` skill bundles natively:

```bash
# user scope (dshHome defaults to ~/.dsh):
cp -r I-Tipp-Ex ~/.dsh/skills/i-tipp-ex

# project scope — either of:
cp -r I-Tipp-Ex /path/to/project/.dsh/skills/i-tipp-ex
cp -r I-Tipp-Ex /path/to/project/.agents/skills/i-tipp-ex
```

The deepseek-chat app and the raw API have no skill mechanism; for those,
run DeepSeek models through a harness (DSH, Claude Code, etc.) and install
the skill there.

## Mistral (Mistral Vibe)

[Mistral Vibe](https://github.com/mistralai/mistral-vibe) (`pip install
mistral-vibe`) implements the Agent Skills specification:

```bash
# user scope:
cp -r I-Tipp-Ex ~/.vibe/skills/i-tipp-ex
# or:
cp -r I-Tipp-Ex ~/.agents/skills/i-tipp-ex

# project scope — either of:
cp -r I-Tipp-Ex /path/to/project/.vibe/skills/i-tipp-ex
cp -r I-Tipp-Ex /path/to/project/.agents/skills/i-tipp-ex
```

Le Chat has no skill format; it supports MCP connectors instead — the
i-tipp-ex scripts can be wrapped in an MCP server if needed, but that is
out of scope for this repo.

## MiniMax

MiniMax has no own-CLI skill format. The official path is the Token Plan
with Claude Code pointed at MiniMax's Anthropic-compatible endpoint
(`ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic` in
`~/.claude/settings.json` — see the [MiniMax
docs](https://platform.minimax.io/docs/token-plan/claude-code)). In that
setup, install the skill exactly as described under **Claude Code** above.

## Z.ai (GLM)

The GLM Coding Plan officially supports Claude Code via an
Anthropic-compatible endpoint (`https://api.z.ai/api/anthropic` — see the
[Z.ai quick start](https://docs.z.ai/devpack/quick-start)); install the
skill as described under **Claude Code**. Z.ai's own desktop IDE, ZCode,
reportedly supports reusable skills, but its skill format/location is not
documented officially at the time of writing — treat it as unverified.

### One copy, several hosts

`~/.agents/skills/i-tipp-ex/` is scanned by Kimi Code, DeepSeek Harness,
and Mistral Vibe alike — a single copy serves all three.

## OpenAI Codex CLI / ChatGPT code interpreter

These hosts have no native skill packaging. Use the scripts directly as
CLIs — they are fully standalone:

```bash
python3 scripts/audit_file.py report.pdf
python3 scripts/audit_site.py https://example.com --i-am-authorized
```

For Codex CLI, you can point the agent at the skill from your `AGENTS.md`:

```markdown
## Provenance audits
The i-tipp-ex audit scripts live in `./I-Tipp-Ex/scripts/`. To audit a
file run `python3 I-Tipp-Ex/scripts/audit_file.py <file>`; read
`I-Tipp-Ex/SKILL.md` for routing and flags.
```

## Any other agent host

The contract is deliberately minimal: a `SKILL.md` with `name` +
`description` frontmatter at the folder root, and every internal reference
relative to that root. Copy the folder into whatever directory your host
scans for skills. If your host has no skill concept, the `scripts/` CLIs
are the whole product.

## Plain terminal (no agent)

Everything works without any agent:

```bash
python3 scripts/audit_text.py suspicious.md
python3 scripts/audit_dir.py ./incoming --json -o report.json
```

## Optional: vendor-verdict detection

`scripts/detect_vendor.py` is opt-in and needs no setup until you
actually use it. It is configured entirely through environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `ITIPPEX_GEMINI_API_KEY` | API key for the gemini backend (Google's SynthID-Text detector); when set and used, the text is sent to Google's API | unset (backend reports unavailable) |
| `ITIPPEX_GEMINI_MODEL` | Gemini model used for the detection request | `gemini-2.5-flash` |
| `ITIPPEX_MARKLLM_DIR` | Path to an external MarkLLM checkout containing `.venv/bin/python`; MarkLLM is never vendored or auto-installed | unset (backend reports unavailable) |

MarkLLM setup sketch: clone `THU-BPM/MarkLLM`, run `python3 -m venv
.venv` inside the checkout, install MarkLLM's dependencies into that
venv, then export `ITIPPEX_MARKLLM_DIR=/path/to/checkout`. Full detail:
`references/vendor-verdicts.md`.

`make test` never touches the network, the Gemini API, or MarkLLM — the
suite (47 tests) is fully offline.

## Verify the install

From inside the installed folder:

```bash
python3 scripts/audit_text.py assets/fixtures/text/zero_width.md
```

Expected: findings for the seeded invisible characters, and the standing
note on statistical watermarks. (The full test suite, `make test`, only
runs from the git clone — `dist` bundles omit the tests.)

## Updating from a previous version

The skill stores no state outside its own directory, so updating means
replacing the folder (or re-uploading the zip) — nothing migrates.

- **Git clone** — `git pull` inside the clone. That is all.
- **Copied folder** (Claude Code, Kimi Code / Kimi Work, project-level
  `.claude/skills/` or `.agents/skills/`) — delete the old folder, then
  copy the new one to the same location (see the per-host sections
  above).
- **Claude apps (zip upload)** — download the latest
  [`i-tipp-ex.skill`](https://github.com/fedec65/I-Tipp-Ex/releases/latest/download/i-tipp-ex.skill),
  then re-upload it via **Settings → Capabilities → Skills**, replacing
  the previous upload.

No configuration changes are needed when updating from 1.0.0: the new
vendor-verdict script (`scripts/detect_vendor.py`) is opt-in and its
environment variables (`ITIPPEX_*`) only matter if you use it. The
version shown in reports (`"version"` in `--json` output) comes from the
installed folder, so an updated copy reports the new version immediately.

Check what changed in the
[CHANGELOG](https://github.com/fedec65/I-Tipp-Ex/blob/main/CHANGELOG.md).

## Uninstall

Delete the folder. The skill never writes outside its own directory
except report files you explicitly request with `-o`.
