# Contributing to mfethuls

Thanks for helping! Bug reports, parsers for new instruments, fixes and documentation are all welcome.

## Contributor License Agreement

Before your first pull request can be merged, you sign a Contributor License Agreement (CLA). A bot comments on the pull request with a link; signing takes a minute and covers all your later contributions.

The CLA is a licence grant, not a copyright transfer: you keep the copyright to your work. You confirm that you have the right to contribute it, and give the project a broad licence to use, change and distribute it, including under licences other than Apache-2.0. That lets the project keep its licensing flexible.

If you contribute as part of your job, your employer may own your work. Please check with them before signing.

## Development setup

```bash
uv venv --python 3.11
uv pip install -e ".[dev,viz,service]"
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
