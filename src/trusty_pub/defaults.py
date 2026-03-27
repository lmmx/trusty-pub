from pathlib import Path

import tomllib

_TOML = Path(__file__).with_name("defaults.toml")


def resolve_package_listing(name: str | None = None) -> dict:
    """
    Return metadata for a package listing.

    If `name` is None, picks the first key under [data.top_pypi_packages].
    """
    raw = tomllib.loads(_TOML.read_text())
    listings = raw["data"]["top_pypi_packages"]
    if name is None:
        # Pick the first key in TOML — canonical
        name = next(iter(listings))
    return listings[name]  # KeyError if not found


def resolve_pypi_metadata(name: str | None = None) -> dict:
    raw = tomllib.loads(_TOML.read_text())
    sources = raw["data"]["pypi_metadata"]
    if name is None:
        name = next(iter(sources))
    return sources[name]
