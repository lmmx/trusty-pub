from pathlib import Path

import tomllib

_TOML = Path(__file__).with_name("defaults.toml")


def _load_toml() -> dict:
    return tomllib.loads(_TOML.read_text())


def resolve_package_listing(name: str | None = None) -> dict:
    listings = _load_toml()["data"]["top_pypi_packages"]
    if name is None:
        name = next(iter(listings))
    return listings[name]


def resolve_pypi_metadata(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["pypi_metadata"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_workflows(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["workflows"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_results(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["results"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_results_nogithub(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["results_nogithub"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_report(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["report"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_analysis(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["analysis"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_tracker(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["tracker"]
    if name is None:
        name = next(iter(sources))
    return sources[name]


def resolve_bulk_search(name: str | None = None) -> dict:
    sources = _load_toml()["data"]["bulk_search"]
    if name is None:
        name = next(iter(sources))
    return sources[name]
