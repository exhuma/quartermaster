Integrate Quartermaster into this project's agent instructions. Follow these steps:

1. Scan the project root for any of these agent-instruction files (more than one may exist): `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`, `GEMINI.md`.
2. For each file found, add the following paragraph near the top (after any existing preamble), under a `## Quartermaster` heading if the file uses headings:

   > When Quartermaster is available, treat its published trait vocabulary and bootstrap guidance as the source of truth for kit discovery; normalize user intent to supported traits before selection and retry when coverage is low.

3. If no matching file is found, offer the user a multiple-choice selection of the typical options — `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`, `GEMINI.md` — and create whichever the user picks.
4. Do not duplicate the paragraph if it is already present.
5. After writing, confirm to the user which file(s) were modified and that Quartermaster is now wired in.

The paragraph is intentionally minimal — it tells future agents to use Quartermaster without hard-coding a kit list. Do not expand or paraphrase it.
