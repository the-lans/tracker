Create a separate git worktree for task $1: a new branch from origin/main (this repo's base branch) named feature/$1 (not an existing branch name), in a directory next to the main repo (e.g. ../repo-$1).
If branch feature/$1 already exists, reuse it instead of creating a new one.
Make all further changes for this task in that worktree only; do not touch the main checkout.
Copy .env from the main project folder into the worktree.
Afterwards show `git worktree list` to confirm the worktree exists and is on the right branch.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
