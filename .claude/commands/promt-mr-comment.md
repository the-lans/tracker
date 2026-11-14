Turn each review remark above into one detailed Pull Request comment and publish them to GitHub right away (do not just print text for copying). Write the comments in Russian, in clear Yandex-style communication:
- No formalism or bureaucratese — like a person explaining to a colleague.
- Start with the gist of the problem (1–2 sentences), then explain the risk for the project/users, end with a concrete suggestion.
- No accusatory tone («вы забыли», «это неправильно») — use «здесь есть риск…», «стоит проверить…», «лучше сделать так…».
- For technically complex remarks (races, timeouts, session ownership, Redis signals), explain the essence so a developer without deep knowledge of that subsystem understands it.
- No "Generated with Claude Code" or any other AI marker — neither in the text nor as a signature.

Each remark is a separate comment (separate review comment), not one big text for all remarks.

Each comment must be attached to a specific line/block in the PR diff (inline review comment), not a standalone unattached comment.

## Publishing to GitHub

1. **Identify the PR.** If the PR number/link is given as a command argument or was already discussed in this conversation, use it. If ambiguous (several PRs mentioned, or none at all), ask the user which PR to publish to — do not guess. `gh auth status` must succeed; if not — stop and ask the user to run `! gh auth login`.
2. **Identify the repository.** `gh repo view --json nameWithOwner --jq .nameWithOwner` in the repo the PR belongs to (e.g. `the-lans/tracker`) — do not hardcode it.
3. **Get the PR head commit** in one request:
   ```
   gh pr view <number> --json headRefOid --jq .headRefOid
   ```
   This SHA is the `commit_id` for every inline comment below.
4. **For each remark determine the exact file and line** in the PR head version, if the remark doesn't already have an exact line number:
   - Open the file at the head commit (`git show <headRefOid>:<path>`) and find the exact line/start of block the remark refers to (function, specific expression) — do not guess the number, verify against the actual file content.
   - The line must be part of the PR diff (`gh pr diff <number>`): GitHub rejects inline comments on lines outside the diff hunks.
   - If a remark concerns several scattered places, lies outside the diff or doesn't map to one file (architectural/general remark), do not invent an artificial anchor; publish it as a regular PR comment (`gh pr comment <number> --body-file <file>`) and explicitly tell the user it's a general remark.
5. **Publish each anchored comment** via the GitHub REST API — one request per remark, so each becomes a separate thread on its own line:
   ```
   gh api --method POST repos/<owner>/<repo>/pulls/<number>/comments \
     -f body=@<file with the comment text> \
     -f commit_id=<headRefOid> \
     -f path=<file path relative to repo root> \
     -F line=<line number in the new file version> \
     -f side=RIGHT
   ```
   - For a multi-line block add `-F start_line=<first line> -f start_side=RIGHT` (with `line` = last line).
   - If the remark is about a deleted line (absent in the new version), use `side=LEFT` and the line number in the old version.
   - Keep comment texts in temporary files in the scratchpad, not in the repo.
6. **Verify.** Make sure each request returned `201 Created`, and give the user a short summary in Russian: how many comments were published inline (anchored to a line) and how many as general comments (if any), plus the PR link. If a request failed (e.g. `422` — the line is not part of the diff), show which comment failed and the error text; do not auto-retry it and do not re-anchor it to another line without checking.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
