# Example prompts

## Clone and inspect a repo

Use local-shell-mcp. Clone `https://github.com/fwerkor/FrameDiff.git` into `/workspace/FrameDiff`, inspect the tree, search for `fullnet`, and report the main entry points.

## Make a change safely

Use local-shell-mcp. In `/workspace/FrameDiff`, create a new branch `ai/example-change`, make the requested code edit with `edit_file` or `apply_patch`, run relevant tests, show `git diff --stat`, run `secret_scan`, commit, and push the branch.

## Playwright

Use local-shell-mcp. Open `https://example.com` with Playwright, save a screenshot to `screenshots/example.png`, and return the page title and visible text.
