# Agent Instructions

## Workflow

- Run `bd prime` when starting work or after context compaction.
- Use Beads for durable task tracking and shared project memory.
- Read the closest applicable `AGENTS.md` before changing files.
- Inspect `git status` and existing diffs before modifying the worktree.
- Record complex implementation plans as Bead notes before coding.
- Keep the shared agent plugin at `plugin/fastsqla`; preserve the provider manifests in
  `.claude-plugin` and `.codex-plugin`.

## Engineering

- Prefer simple root-cause fixes and complete implementations.
- Preserve unrelated changes and avoid drive-by formatting.
- Fail clearly on invalid configuration; do not add plausible dummy defaults.
- Validate external input at trust boundaries and never expose secrets.
- Describe the current state in documentation and code comments.

## Git

- Keep one task per pull request and stay below 500 added lines.
- Work in `.worktrees/` on `feat/`, `fix/`, `chore/`, or `docs/` branches.
- Use conventional commit prefixes and do not add AI signatures.
- Use `gh` for GitHub operations.
- Scan for secrets before committing.
- Rebase on current `main` before opening a pull request.
- Do not commit or push without authority from the user or active Beads profile.

## Verification

- Run tests, linters, builds, and behavioral checks proportional to the change.
- Never claim completion without evidence from the relevant quality gates.
- Verify pushed commits on the remote branch.
- After a pull request merges, close its Bead, extract PR lessons, and remove its
  worktree and local branch.
