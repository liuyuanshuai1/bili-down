# Issue tracker: GitHub

Issues and PRDs for this repository live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- Create issues with `gh issue create`.
- Read issues with `gh issue view <number> --comments`.
- List issues with `gh issue list` and request structured JSON when automation consumes the result.
- Comment with `gh issue comment <number>`.
- Apply or remove labels with `gh issue edit <number> --add-label <label>` or `--remove-label <label>`.
- Close issues with `gh issue close <number>`.

Infer the repository from the configured Git remote. When a skill says to publish to the issue tracker, create a GitHub issue.
