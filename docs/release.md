# Releasing

A release is a signed `v<version>` tag on `main`. [curtains](https://github.com/nielsmadan/curtaincall)
prepares and pushes it from a checkout; GitHub Actions publishes it.

## Cutting a release

```sh
just release --dry-run
just release              # version from the commit messages; or: just release minor, just release 0.2.0
```

`just release` runs curtains 1.x with the policy in [scripts/release.json](../scripts/release.json),
from a clean checkout of `main` that has a working Git signing key. It runs `just check-static` and
`just coverage`, then sets the version in `pyproject.toml` (`scripts/release.py prepare`), runs
`uv lock`, regenerates `CHANGELOG.md` with git-cliff (`just changelog <version>`, configured in
[cliff.toml](../cliff.toml)), and checks the result with `just build` and `just check-package`. It
commits those three files as `chore: release <version>`, tags the commit and pushes branch and tag
together. Only `feat`, `fix` and `perf` commits reach the changelog.

## What the tag starts

[release.yml](../.github/workflows/release.yml) runs on a `v*` tag:

1. **verify** checks that the tag is annotated, on `main` and equal to the project version, runs
   the static checks, the suite with coverage and the packaging test on the tagged source, builds
   the sdist and the wheel from it, and installs each into a fresh environment.
2. **formula** renders [scripts/formula.rb.in](../scripts/formula.rb.in) for GitHub's archive of the
   tag and runs `brew install --build-from-source` and `brew test` on macOS. The formula depends
   on `nielsmadan/tap/bellhop`, so bellhop's formula has to be in the tap first, and the job
   installs it by its full name first, because Homebrew refuses a dependency from a tap it does
   not trust.
3. **publish** creates the GitHub release with the wheel, the sdist, `SHA256SUMS` and the notes.
4. **homebrew** commits the tested formula to
   [nielsmadan/homebrew-tap](https://github.com/nielsmadan/homebrew-tap), unless the tap already
   holds a newer version.

The repository needs the Actions secret `HOMEBREW_TAP_TOKEN`, a token that can push to the tap.
Without it the formula job fails before anything is published.

A run that failed part-way is retried from the Actions page: run the Release workflow from `main`
with the existing tag. `curtains ci publish` completes what is missing and changes nothing that
is already published.

`.github/workflows/actions.lock` pins every action to a commit; regenerate it with
`gh actions-lock` after changing a workflow.
