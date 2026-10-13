"""
Variable assignment: from indexed source variables to BDC variable library entries.

This package holds the logic that decides what a source variable *is* and how it is
expressed as a library entry. It deliberately owns no I/O: reading transformation specs,
fetching dbGaP digests and rendering canonical data dictionaries stay with the pipeline
that calls it (``dm-bip``), which populates the intermediate representation in
:mod:`bdc_varlib.pipeline.records` and supplies the target datamodel classes.

- :mod:`records` — the intermediate representation: a source variable and every target
  slot it feeds.
- :mod:`classify` — continuous or categorical, read off the canonical data dictionary's
  ``type``.
- :mod:`emit` — assemble entries of the caller's datamodel classes and serialize them.
"""

from bdc_varlib.pipeline.classify import (
    DD_CONTINUOUS_TYPES,
    Classifier,
    VariableKind,
    always_unknown,
    classifier_for,
    classify_from_dd,
)
from bdc_varlib.pipeline.emit import (
    DBGAP_PREFIX,
    EntryClasses,
    MetadataSource,
    VariableEntries,
    describe,
    to_entries,
    to_yaml,
)
from bdc_varlib.pipeline.records import VariableRecord, VariableUsage

__all__ = [
    "DBGAP_PREFIX",
    "DD_CONTINUOUS_TYPES",
    "Classifier",
    "EntryClasses",
    "MetadataSource",
    "VariableEntries",
    "VariableKind",
    "VariableRecord",
    "VariableUsage",
    "always_unknown",
    "classifier_for",
    "classify_from_dd",
    "describe",
    "to_entries",
    "to_yaml",
]
