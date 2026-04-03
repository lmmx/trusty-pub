# 🛡 Operation Trusty Pub

Indexing support for Trusted Publishing on PyPI

## Usage

This repo contains a reproducible analysis with a cached directory of the `.github/workflows`
subdirs of Python packages on the Python package registry _PyPI_.

To re-run, call the package entrypoint `trusty-pub`.

- To just refresh Hugo VK's PyPI package listings, run `tp-refresh-pkgs`

## Trusted Publishing detection

### Initial iteration

We use [grepow] to pull down the GitHub repos in sparse mode (we only need the
`.github/workflows` subdir),
after having acquired the repo names from package metadata on PyPI.

Then we look for signs of Trusted Publishing:

- A `permissions` field on the workflow job with `id-token: write`
  is the strongest indicator (required but not sufficient).
- Either a step that runs `uv publish` or (more commonly) uses the
  `pypa/gh-action-pypi-publish` action.
    - Example of `uv publish` for the [fastmcp] package
- The presence of username/password credentials for a package upload
  is a sign that Trusted Publishing is **not** being used.

[fastmcp]: https://github.com/PrefectHQ/fastmcp/blob/b1505ba5d7cd90cbd04912f2e88cdd42c57b9e80/.github/workflows/publish.yml#L23
[grepow]: https://github.com/lmmx/grepow

### Further iterations

It quickly became clear that while it was polite not to hammer PyPI,
for some cases we would have to fall back to actually reviewing it,
so this was done by first defining as many rules as could be relied on
to get true positives, with no guesswork if ambiguous.

After all these rules were exhausted, another pass was done to request the packages'
pages from PyPI, and then some manual review was done when rate limited.

## Tracking issue detection

To detect tracking issues, first the ones I'd submitted myself were added,
followed by bulk search over GitHub issues via API,
followed by manual triage in a FastAPI app (in the `static` directory
in the tracker submodule).

## Static site deployment

Lastly, the results were deployed as a static site to GitHub Pages
at [lmmx.github.io/trusty-pub](https://lmmx.github.io/trusty-pub/).

As well as a search bar, there's a Resources tab with links to
blogs, incident reports, et cet.
