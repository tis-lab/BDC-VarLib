"""Tests for typing variables from the canonical data dictionary's type vocabulary."""

import logging
from dataclasses import dataclass, field

import pytest

from bdc_varlib.pipeline.classify import VariableKind, classifier_for, classify_from_dd


@dataclass
class Entry:
    """The smallest thing that satisfies ``TypedEntry``."""

    data_type: str | None = None


@dataclass
class Table:
    """The smallest thing that satisfies ``TypedTable``."""

    entries: dict[str, Entry] = field(default_factory=dict)


DATASET = "pht000001"


@pytest.fixture()
def tables():
    """Provide one table covering the adapter's whole type vocabulary."""
    return {
        DATASET: Table(
            {
                "phv00000001": Entry("integer"),
                "phv00000002": Entry("decimal"),
                "phv00000003": Entry("permissible_values"),
                "phv00000004": Entry("boolean"),
                "phv00000005": Entry("string"),
                "phv00000006": Entry("date"),
                "phv00000007": Entry("Integer"),
                "phv00000008": Entry(None),
            }
        )
    }


class TestClassifyFromDd:
    """The DD type is the adapter's decision; this only maps its vocabulary onto two classes."""

    @pytest.mark.parametrize(
        ("accession", "kind"),
        [
            ("phv00000001", VariableKind.continuous),
            ("phv00000002", VariableKind.continuous),
            ("phv00000003", VariableKind.categorical),
            ("phv00000004", VariableKind.categorical),
            ("phv00000005", VariableKind.categorical),
            ("phv00000006", VariableKind.categorical),
        ],
    )
    def test_quantities_are_continuous_and_labels_categorical(
        self, tables, accession, kind
    ):
        """``integer`` and ``decimal`` are the only quantities in the vocabulary."""
        assert classify_from_dd(tables, DATASET, accession) is kind

    def test_type_matching_ignores_case_and_whitespace(self, tables):
        """A hand-edited DD may capitalize; the vocabulary is lowercase."""
        assert (
            classify_from_dd(tables, DATASET, "phv00000007") is VariableKind.continuous
        )

    def test_a_variable_the_dd_lacks_is_unknown(self, tables):
        """Absent entry or absent table: nothing to read, so nothing is asserted."""
        assert classify_from_dd(tables, DATASET, "phv99999999") is VariableKind.unknown
        assert (
            classify_from_dd(tables, "pht999999", "phv00000001") is VariableKind.unknown
        )

    def test_an_entry_without_a_type_is_unknown(self, tables):
        """An untyped row is not a label by default; it is undecided."""
        assert classify_from_dd(tables, DATASET, "phv00000008") is VariableKind.unknown


class TestClassifierFor:
    """A classifier is a dictionary index, or nothing."""

    def test_types_what_the_dictionary_describes(self, tables, caplog):
        """Described variables get a class; undescribed ones stay unknown, without complaint."""
        with caplog.at_level(logging.WARNING):
            classify = classifier_for(tables)
        assert classify(DATASET, "phv00000001") is VariableKind.continuous
        assert classify(DATASET, "phv99999999") is VariableKind.unknown
        assert "cannot be typed" not in caplog.text

    @pytest.mark.parametrize("tables", [None, {}])
    def test_warns_when_there_is_no_dictionary(self, tables, caplog):
        """With nothing to read, every variable would be held back, and the run should say so."""
        with caplog.at_level(logging.WARNING):
            classify = classifier_for(tables)
        assert classify(DATASET, "phv00000001") is VariableKind.unknown
        assert "cannot be typed" in caplog.text
