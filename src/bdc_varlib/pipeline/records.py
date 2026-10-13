"""
The intermediate representation between reading transformation specs and emitting entries.

A variable library entry *is* the source variable, so the record for one accumulates every
target slot that variable feeds rather than keeping only the first use seen. The pipeline
that reads the specs (``dm-bip``) builds these; :mod:`bdc_varlib.pipeline.emit` consumes
them.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class VariableUsage:
    """
    One place a source variable feeds a target slot.

    ``via_expression`` distinguishes a slot populated directly (``populated_from: phv...``)
    from one that references the variable inside a LinkML expression. An identifier woven
    into a ``uuid5()`` call is a materially weaker claim about the variable's role than a
    value copied straight across, and a library entry should not flatten the two.
    """

    target_class: str
    slot: str
    via_expression: bool
    spec_id: str


@dataclass
class VariableRecord:
    """
    A source variable and every target slot it feeds.

    ``datasets`` is a set rather than a scalar because nothing in the spec format prevents
    the same accession appearing under two ``pht`` values; see :meth:`sole_dataset`.
    """

    accession: str
    datasets: set[str] = field(default_factory=set)
    study_id: str | None = None
    usages: list[VariableUsage] = field(default_factory=list)

    def sole_dataset(self) -> str:
        """
        Return the dataset this variable belongs to.

        The variable library's ``file_id`` is single-valued, so a variable seen under
        several datasets has to collapse to one. That collapse is lossy, so it warns and
        picks deterministically rather than silently taking whichever spec was read first.
        """
        datasets = sorted(self.datasets)
        if len(datasets) > 1:
            logger.warning(
                "Variable %s appears under multiple datasets %s; using %s for file_id",
                self.accession,
                datasets,
                datasets[0],
            )
        return datasets[0]
