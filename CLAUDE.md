# kroger-lookup-app

## Docs

- `README.md` follows the alphagov README template. Keep it to an overview and getting-started steps.
- Longer material, such as reference or configuration details, goes in `docs/`. Link to it from the README.
- Unusual terms are defined in the README's Nomenclature section. Add new terms there when you introduce them.

## Working Rules

- Ask before changing the folder structure or renaming top-level files.
- Put project-specific instructions in `.claude/rules/project.md`, not in this file. This file comes from the template, and `copier update` rewrites it.
- This repo was created from a Copier template. Never edit `.copier-answers*.yml` files by hand; run `copier update --trust -a .copier-answers.<layer>.yml` for each layer instead.

## Public Repo Rules

- Write every tracked file for a public reader. Never put the owner's name, references to AI chats or chat archives, or details of the owner's machine, accounts or keys in a tracked file. Put them in `CLAUDE.local.md`, which `.gitignore` excludes.
- Keep `CLAUDE.md` and the template's `.claude/rules/` files tracked. `copier update` deletes template files that are gitignored.
- Keep the shared block at the top of `.gitignore` (Claude Code personal files, secrets, logs and OS files). Add project entries below it, and keep `!` exception lines such as `!.env.example` after any pattern they override.
