"""Tests for expressing variable records as library entries of caller-supplied classes."""

import logging

import pytest
from pydantic import BaseModel

from bdc_varlib.pipeline.classify import VariableKind, always_unknown
from bdc_varlib.pipeline.emit import describe, to_entries, to_yaml
from bdc_varlib.pipeline.records import VariableRecord, VariableUsage


class Continuous(BaseModel):
    """A stand-in for the generated SingleContinuousVariable: identity plus two descriptive slots."""

    id: str
    source_id: str
    file_id: str
    associated_study: str | None = None
    variable_description: str | None = None
    variable_name: str | None = None
    unit: str | None = None


class Categorical(BaseModel):
    """A stand-in for the generated SingleCategoricalVariable."""

    id: str
    source_id: str
    file_id: str
    associated_study: str | None = None
    variable_description: str | None = None
    coded_values: list[str] | None = None


ENTRY_CLASSES = {
    VariableKind.continuous: Continuous,
    VariableKind.categorical: Categorical,
}

BMI = "phv00204719"
SEX = "phv00204720"
STUDY = "bdchm:Study/phs000280"


def _records() -> dict[str, VariableRecord]:
    return {
        SEX: VariableRecord(
            SEX,
            {"pht004063"},
            STUDY,
            [VariableUsage("Demography", "sex", False, "spec")],
        ),
        BMI: VariableRecord(
            BMI,
            {"pht004063"},
            STUDY,
            [
                VariableUsage("Quantity", "value_decimal", False, "spec"),
                VariableUsage("Obs", "id", True, "spec"),
            ],
        ),
    }


def _classify(dataset: str, accession: str) -> VariableKind:
    return VariableKind.continuous if accession == BMI else VariableKind.categorical


def _emit(metadata=None):
    return to_entries(_records(), _classify, metadata, entry_classes=ENTRY_CLASSES)


def test_unclassified_variables_are_not_emitted(caplog):
    """source_id and file_id only exist on the typed classes, so untyped entries are held back."""
    with caplog.at_level(logging.WARNING):
        entries = to_entries(_records(), always_unknown, entry_classes=ENTRY_CLASSES)
    assert len(entries) == 0
    assert entries.unclassified == sorted(_records())
    assert "could not be typed" in caplog.text


def test_each_kind_takes_its_class():
    """The classifier's answer picks the class; the caller's mapping says which class that is."""
    entries = _emit()
    assert [type(e) for e in entries.continuous] == [Continuous]
    assert [type(e) for e in entries.categorical] == [Categorical]


def test_identity_triple_populated_from_records_alone():
    """The phv/pht/phs join survives into the entry without any metadata source."""
    (entry,) = _emit().continuous
    assert (entry.id, entry.source_id, entry.file_id, entry.associated_study) == (
        f"dbgap:{BMI}",
        BMI,
        "pht004063",
        STUDY,
    )
    assert (
        entry.variable_description
        == "Source for Quantity.value_decimal; Obs.id (via expression)"
    )


def test_descriptive_slots_left_empty_without_a_metadata_source():
    """Data-dictionary slots stay unset rather than being invented from the records."""
    (entry,) = _emit().continuous
    assert entry.variable_name is None
    assert entry.unit is None


def test_metadata_source_fills_descriptive_slots():
    """The seam to data dictionaries is one lookup, not a restructure."""

    class Dictionary:
        def lookup(self, dataset: str, accession: str) -> dict:
            return (
                {"variable_name": "BMI01", "unit": "kg/m2"} if accession == BMI else {}
            )

    (entry,) = _emit(Dictionary()).continuous
    assert (entry.variable_name, entry.unit) == ("BMI01", "kg/m2")


def test_metadata_slots_unknown_to_the_class_are_dropped_with_a_warning(caplog):
    """A dictionary field with no home in the class is reported, not silently discarded."""

    class Dictionary:
        def lookup(self, dataset: str, accession: str) -> dict:
            return {"not_a_slot": "x"}

    with caplog.at_level(logging.WARNING):
        _emit(Dictionary())
    assert "has no slot not_a_slot" in caplog.text


def test_a_record_under_two_datasets_collapses_to_the_lowest(caplog):
    """file_id is single-valued; the collapse is deterministic and visible."""
    records = {BMI: VariableRecord(BMI, {"pht004070", "pht004063"}, STUDY, [])}
    with caplog.at_level(logging.WARNING):
        (entry,) = to_entries(
            records, _classify, entry_classes=ENTRY_CLASSES
        ).continuous
    assert entry.file_id == "pht004063"
    assert "multiple datasets" in caplog.text


def test_description_records_every_use():
    """The rendered description names each target slot, marking expression references."""
    assert (
        describe(
            [
                VariableUsage("Demography", "sex", False, "spec"),
                VariableUsage("Demography", "id", True, "spec"),
            ]
        )
        == "Source for Demography.sex; Demography.id (via expression)"
    )


def test_output_is_grouped_and_omits_unset_slots():
    """Both groups are always present; unset slots are omitted rather than written as nulls."""
    document = to_yaml(_emit())
    assert document.startswith("single_continuous_variables:\n")
    assert "single_categorical_variables:\n" in document
    assert "variable_name" not in document


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_output_is_deterministic(order):
    """Records are emitted sorted by accession, whatever order they were collected in."""
    records = _records()
    reordered = {
        k: records[k]
        for k in (
            sorted(records) if order == ("a", "b") else sorted(records, reverse=True)
        )
    }
    assert to_yaml(
        to_entries(reordered, _classify, entry_classes=ENTRY_CLASSES)
    ) == to_yaml(_emit())
