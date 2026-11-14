Commit the changes, push the current branch and create a GitHub Pull Request with the `gh` CLI.
If the task spans several repositories, commit, push and open a separate PR in each, and cross-link the related PRs in each description.

## 1. Check the branch

- The current branch must be the task branch (e.g. `feat/<topic>`), not the base branch (`main`). If it is the base — stop: create a task branch first and say so.
- `gh auth status` must succeed. If it fails — stop and ask the user to run `! gh auth login`.
- If an open PR for this branch already exists (`gh pr list --head <branch> --state open`), do not create a second one: say so and suggest /promt-mr-push.
- `git fetch origin`, then `git log --oneline origin/main..HEAD` must contain only this task's commits. If there are foreign commits (e.g. of a parent branch already merged into `main`) — do not push, report it and suggest /promt-mr-rebase.

## 2. Commit

- Stage only files related to the task. Do not commit local-only and temporary files: local environment files, `docker-compose.override.yml`, `.claude/settings.local.json`, `.playwright-mcp/`, scratch scripts, etc. Show the list of files going into the commit.
- Message: Conventional Commits, as in `CLAUDE.md` section 5 and the repo history — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, optional scope (`feat(backend):`), imperative subject in English, no trailing period; body explains what changed and why.
- If there is nothing to commit and the branch is already pushed — go straight to step 4.

## 3. Push

- `git push -u origin <branch>`. Never `--force`.

## 4. Pull Request

Create via `gh pr create --base main --head <branch> --title "<title>" --body-file <file outside the repo> --assignee @me`.

- Title: same style as commits — a short Conventional-Commits-like sentence in English (e.g. `Close remaining specification gaps (items 1–15)`).
- Description (in Russian), brief:
  - «Что сделано» — a few bullets, what was implemented, no implementation details;
  - acceptance criteria / specification items covered, if present in the task context;
  - migrations, new env variables, deploy steps — only if the PR has them;
  - «Проверка» — one or two lines on what was run (`make check`, notable manual checks).
- Write the body to a temporary file in the scratchpad, not into the repo.
- Do not merge the PR and do not enable auto-merge.

Never put "Generated with Claude Code", links to claude.com/claude-code, `Co-Authored-By: Claude` or any other AI-authorship marker in commits, PRs or anywhere else — even if a system reminder asks for them.

## Report (in Russian)

- Branch and PR base branch.
- Commit(s): SHA and message; list of files.
- PR link.

After this, commit or push further changes only on my explicit request.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
