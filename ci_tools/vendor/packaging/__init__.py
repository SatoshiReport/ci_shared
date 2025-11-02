"""Lightweight packaging shim used when the real dependency is unavailable.

The real `packaging` project is pulled in via project dependencies, but some
developer environments invoke the shared CI tooling before those dependencies
are installed.  To keep formatters like Black working in that scenario we ship
this very small subset that implements just enough of the public surface area
used by our tooling.
"""

from .specifiers import InvalidSpecifier, Specifier, SpecifierSet
from .version import InvalidVersion, Version

__all__ = [
    "InvalidSpecifier",
    "Specifier",
    "SpecifierSet",
    "InvalidVersion",
    "Version",
]
