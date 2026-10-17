---
name: quantx-skills-maintainer
description: Use when adding, editing, splitting, or validating opencode skills under .opencode/skills/ in QuantX — frontmatter contract, router+references structure, script conventions, and SHA-256 manifest regeneration/verification with the integrity validator.
---

# QuantX Skills Maintainer

Rules for the opencode skill library itself. Source-code and repo-wide workflow rules live in `quantx-dev-workflow`; this skill governs `.opencode/skills/**`.

## Skill structure contract

- One directory per skill: `.opencode/skills/<name>/SKILL.md`. The directory name must equal the frontmatter `name` (`quantx-*`, lowercase-hyphen).
- Frontmatter: `---`-fenced, with `name:` and a single-line `description:` at column 0. Description ≤ 1024 chars, starts with "Use when", front-loads trigger keywords.
- Large skills follow the router pattern: SKILL.md keeps decisions, safety rules, and pointers (~≤100 lines); lookup-heavy detail moves to `references/*.md` linked relatively from SKILL.md.
- Executable helper scripts live in `scripts/` — stdlib-only Python, `--self-test`, PASS/FAIL/UNKNOWN fail-closed, exit codes 0/1/2/3.
- No secrets, credentials, or environment-specific values in any skill file.

## Adding or changing a skill

1. Create/edit `.opencode/skills/<name>/SKILL.md` following the frontmatter contract above.
2. Front-load trigger keywords in the description; keep it single-line.
3. Move deep tables and module inventories to `references/` when SKILL.md approaches ~120 lines.
4. Regenerate the manifest (below); commit SKILL.md, references, and `skills.lock.json` together.
5. If the skill is core to task routing, add it to the skill hierarchy in `AGENTS.md`.

## Integrity manifest

`.opencode/skills/skills.lock.json` (`quantx.skills-manifest.v1`) pins the SHA-256 of every skill file except the manifest itself.

```powershell
python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --update   # after any skill edit
python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --check    # verify
python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --self-test
```

- `--check` fails closed: unlisted, missing, or modified files; invalid frontmatter; name/directory mismatch; duplicate names; or overlong descriptions are never PASS.
- Missing or unreadable manifest → UNKNOWN (run `--update`), never PASS.
- `--update` refuses to write the manifest while frontmatter validation fails.
- Hashes are line-ending independent (CRLF normalized to LF before hashing): the repo has no `.gitattributes` and `core.autocrlf=true` on Windows checkouts.
