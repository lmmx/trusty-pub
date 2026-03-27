# 🛡 Operation Trusty Pub

Indexing support for Trusted Publishing on PyPI

## Usage

This repo contains a reproducible analysis with a cached directory of the `.github/workflows`
subdirs of Python packages on the Python package registry _PyPI_.

To re-run, call the package entrypoint `trusty-pub`.

- To just refresh Hugo VK's PyPI package listings, run `tp-refresh-pkgs`

## Trusted Publishing detection

We use [grepow][grepow] to pull down the GitHub repos in sparse mode (we only need the
`.github/workflows` subdir),
after having acquired the repo names from package metadata on PyPI.

[grepow]: https://github.com/lmmx/grepow

Then we look for signs of Trusted Publishing:

- A `permissions` field on the workflow job with `id-token: write`
  is the strongest indicator (required but not sufficient).
- Either a step that runs `uv publish` or (more commonly) uses the
  `pypa/gh-action-pypi-publish` action.
  - Example of `uv publish` for the [fastmcp][fastmcp] package
- The presence of username/password credentials for a package upload
  is a sign that Trusted Publishing is **not** being used.

[fastmcp]: https://github.com/PrefectHQ/fastmcp/blob/b1505ba5d7cd90cbd04912f2e88cdd42c57b9e80/.github/workflows/publish.yml#L23
