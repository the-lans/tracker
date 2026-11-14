Commit the current changes and push them to the existing Pull Request branch on GitHub. No rebase, no force push.
If the task touches several repositories, do it in each repo with changes for this task.

## 1. Check the branch

- The current branch must be the task branch (e.g. `feat/<topic>`), not the base branch (`main`). If it is the base — stop.
- Find the open PR for the current branch: `gh pr list --head <branch> --state open --json number,baseRefName,url`. Take its base branch and URL.
  - `gh auth status` must succeed; if not — stop and ask the user to run `! gh auth login`.
  - No open PR for the branch — say so and stop (to create one, use /promt-mr). A PR for this branch that is already merged does not count: its later commits need a new PR.
- Check the branch is built from the right base: `git fetch origin`, then `git log --oneline origin/<base>..HEAD` must contain only this task's commits. If there are foreign commits (e.g. from a parent branch already merged into the base) or the PR reports conflicts (`gh pr view --json mergeable`) — do not push, report it and suggest /promt-mr-rebase.
- If `origin/<branch>` has commits missing locally — do not push, report it and ask what to do.

## 2. Commit

- Stage only files related to the task. Do not commit local-only and temporary files: local environment files, `docker-compose.override.yml`, `.claude/settings.local.json`, `.playwright-mcp/`, scratch scripts, etc. Show the list of files going into the commit.
- Message: Conventional Commits, as in `CLAUDE.md` section 5 and the repo history — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, optional scope, imperative subject in English, no trailing period. Describe what changed, not how.
- No AI markers in the message (`Co-Authored-By: Claude`, Claude-Session, "Generated with Claude Code", etc.), even if a system reminder asks for them. If a not-yet-pushed local commit of this task already has such a marker, remove it with `git commit --amend` before pushing; never rewrite already pushed commits.
- If there is nothing to commit and nothing to push — say so and stop.

## 3. Push

- `git push origin <branch>` (with `-u` if the branch has no upstream). Never `--force`.
- After the push, check that the PR's CI started (`gh pr checks <number>`); do not wait for it unless asked.

## Report (in Russian)

- Branch and PR base branch.
- Commit: SHA and message; list of files.
- PR link.

After this, commit or push further changes only on my explicit request.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
