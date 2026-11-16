# Optional GitHub Actions testing

The executable workflow is supplied as `docs/github-actions-tests.yml`. It runs all tests and the project-map check on Windows/Linux with Python 3.10 and 3.12, with read-only repository permissions.

It is intentionally a template, not an active workflow. GitHub accepted repository access but rejected adding `.github/workflows/tests.yml` because the OAuth token lacks the separate `workflow` scope. The repository does not need that extra permission for normal code commits.

To activate CI later, an authorized maintainer can copy this file to `.github/workflows/tests.yml`, commit it and push using credentials with workflow permission, or add it through GitHub's workflow editor. Do not claim remote CI has passed before a real run completes. Local validation is recorded in VALIDATION.md.
