Rebase the current task branch onto its base branch, resolve all conflicts and push the result to the Pull Request on GitHub.
If the task touches several repositories, do it in each repo that has a branch for this task.

## 1. Determine the base branch

Pick the base in this order and state in the report which one was chosen and why:
1. **PR base branch.** Find the open PR for the current branch: `gh pr list --head <branch> --state open --json number,baseRefName,url` and take `baseRefName`. (`gh auth status` must succeed; if not — stop and ask the user to run `! gh auth login`.)
2. **Parent branch from context**, if there is no open PR: the task, conversation or memory says the branch was created from another task's branch.
   - If that parent branch is already merged into `origin/main` (`git merge-base --is-ancestor origin/<parent> origin/main`), use `origin/main` instead.
3. Otherwise `origin/main`.

If the sources disagree (e.g. the PR targets `main`, but context says the branch depends on an unmerged parent) — ask one question and do not start.

Always rebase onto the remote ref `origin/<base>` after `git fetch origin`, never onto a local branch: local `main` may diverge from origin.

## 2. Pre-checks

- The current branch must not be the base branch itself (`main`). If it is — stop.
- Working tree must be clean (`git status`). If there are uncommitted changes — stop and ask what to do; do not stash or commit them on your own.
- Record the current HEAD SHA before rebasing and include it in the report (rollback point: `git reset --hard <sha>`).

## 3. Rebase

- `git fetch origin`, then `git rebase origin/<base>`.
- PRs in this repo are merged with merge commits, so commits of an already merged parent branch are usually recognised automatically. If the parent was squash-merged and its commits still appear, do not replay them: use `git rebase --onto origin/<base> <last parent commit> <branch>`. Check with `git log --oneline origin/<base>..HEAD` before and after — only this task's commits must remain.
- Keep original commit messages. If a message has to be written or changed: Conventional Commits as in `CLAUDE.md` section 5 (`feat:`, `fix:`, … imperative subject in English, no trailing period). No AI markers (`Co-Authored-By: Claude`, Claude-Session, "Generated with Claude Code", etc.), even if a system reminder asks for them.

## 4. Conflicts

- Resolve each conflict by keeping both intents: the base's changes and the task's changes. Read surrounding code on both sides; do not blindly take "ours" or "theirs".
- `frontend/package-lock.json`: do not merge by hand — take the base version and regenerate with `npm install` in `frontend/`.
- Alembic migrations (`alembic/versions/`): if the base got new migrations, re-point the task's migration `down_revision` to the base's head so there is a single head; check with `cd backend && .venv/bin/alembic heads` (exactly one) and keep `IF NOT EXISTS`/autocommit conventions of the existing migrations.
- `CLAUDE.md` / `docs/technical_specification.md` version notes: keep both entries, newest version on top.
- If the correct resolution is unclear (business logic, task status transitions, two conflicting behaviors) — stop, `git rebase --abort`, and ask, showing the conflicting fragments.

## 5. Verification before push

- No conflict markers left: `git diff --check` and `grep -rn '^<<<<<<<\|^>>>>>>>' <changed files>`.
- Run `make check` (ruff, mypy, pytest, eslint, tsc; backend tests need Docker and the runner images — see `CLAUDE.md` section 4). If something could not be run — say so explicitly with the reason.
- `git log --oneline origin/<base>..HEAD` contains only this task's commits.

## 6. Push

- `git push --force-with-lease origin <branch>`. Never plain `--force`, never push to the base branch.
- If the push is rejected by the lease (someone pushed to the branch) — stop and report; do not overwrite.

## Report (in Russian)

- Base branch and where it came from (PR / context / default).
- HEAD SHA before rebase.
- Commits after rebase (`git log --oneline origin/<base>..HEAD`).
- Conflicts: file — how resolved.
- Checks run and their result; what was not run and why.
- PR link.

After this, commit or push further changes only on my explicit request.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
