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

Or download a clean runtime bundle (only `SKILL.md`, `scripts/`,
`references/`, `assets/` — no tests, no git history):

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

## Verify the install

From inside the installed folder:

```bash
python3 scripts/audit_text.py assets/fixtures/text/zero_width.md
```

Expected: findings for the seeded invisible characters, and the standing
note on statistical watermarks. (The full test suite, `make test`, only
runs from the git clone — `dist` bundles omit the tests.)

## Uninstall

Delete the folder. The skill never writes outside its own directory
except report files you explicitly request with `-o`.
