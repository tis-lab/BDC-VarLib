"""BDC Variable Library.

A LinkML-based variable library for BioData Catalyst datasets.
"""

try:
    from bdc_varlib._version import __version__, __version_tuple__
except ImportError:  # pragma: no cover
    __version__ = "0.0.0"
    __version_tuple__ = (0, 0, 0)
