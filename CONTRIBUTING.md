# Contributing to mfethuls

Thanks for helping! Bug reports, instrument definitions and parsers for new instruments, fixes and documentation are all welcome. Most text-file instruments need no code: see [docs/guides/instruments.md](docs/guides/instruments.md).

## Contributor License Agreement

Before your first pull request can be merged, you sign the [Contributor License Agreement](CLA.md) (CLA). A bot comments on the pull request with a link; signing takes a minute and covers all your later contributions.

The CLA is a licence grant, not a copyright transfer: you keep the copyright to your work. You confirm that you have the right to contribute it, and give the project a broad licence to use, change and distribute it, including under licences other than Apache-2.0. That lets the project keep its licensing flexible.

If you contribute as part of your job, your employer may own your work. Please check with them before signing. If your organization (a company, university or institute) should sign for its employees instead, it signs the [Entity Contributor License Agreement](CLA-entity.md) once and lists who may contribute on its behalf.

## Development setup

```bash
uv venv --python 3.11
uv pip install -e ".[dev,viz]"
uv run --no-sync pytest -q
uv run --no-sync ruff check
```

CI runs the same tests and lint on Ubuntu and Windows.

## Pull requests

- Keep each pull request to one change, with tests for new behaviour.
- New instrument parsers come with a small example file in `tests/fixtures` and a parser test.
- Update the docs in `docs/` when behaviour visible to users changes.

## Licence

mfethuls is licensed under the [Apache License 2.0](LICENSE). Contributions are accepted under the same licence, together with the CLA.

## Releasing (maintainers)

Releases are published to PyPI by GitHub Actions (`.github/workflows/publish.yml`), using trusted publishing; no API token is stored.

1. Set the new version in `pyproject.toml` (`version = "X.Y.Z"`) and merge into `master`.
2. Optional dry run: **Actions → publish → Run workflow** builds, tests the built package and uploads it to TestPyPI.
3. Tag the release on `master` and push the tag:

   ```bash
   git tag -a vX.Y.Z -m "mfethuls X.Y.Z"
   git push origin vX.Y.Z
   ```

   The workflow checks that the tag matches the version, builds, tests the built package and publishes it to PyPI.
4. Write the release notes on GitHub (**Releases → Draft a new release** from the tag).
