"""Tests for the portal catalogs (version 1): src/bdc_varlib/data/varlib_catalog_<prefix>.json.

Run on their own with `just test-data`.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "bdc_varlib" / "data"
CONTRACT = ROOT / "portal-varlib"
CATALOGS = sorted(DATA.glob("varlib_catalog_*.json"))
FILE_STEMS = {"HP": "hpo"}  # same naming rule as scripts/build_bdc_varlib.py
VALUE_SLOTS = {"condition_status", "exposure_status", "procedure_status", "measurement_value"}

pytestmark = pytest.mark.skipif(not CATALOGS, reason="no catalogs in src/bdc_varlib/data")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validate_catalog():
    """validate_catalog() from the pinned study-palette portal-varlib contract."""
    spec = importlib.util.spec_from_file_location("portal_validate_catalog", CONTRACT / "validate_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_catalog


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_catalog_passes_portal_contract(path, validate_catalog):
    """Schema, references and publication rules of portal-varlib.yaml (no synthetic data allowed)."""
    assert validate_catalog(load(path)) == []


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_file_holds_one_curie_prefix(path):
    prefixes = {c["curie"].split(":", 1)[0] for c in load(path)["concepts"]}
    assert len(prefixes) == 1
    (prefix,) = prefixes
    assert path.stem == f"varlib_catalog_{FILE_STEMS.get(prefix, prefix.lower())}"


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_every_concept_has_an_integrated_variable_with_a_value(path):
    catalog = load(path)
    compounds = {c["id"]: c for c in catalog["compound_variables"]}
    concepts = {c["curie"] for c in catalog["concepts"]}
    assert concepts == {iv["concept_type"] for iv in catalog["integrated_variables"]}
    for iv in catalog["integrated_variables"]:
        slots = {s for cid in iv["integrates"] for r in compounds[cid].get("row_metadata", [])
                 for s in r.get("microschema_slot", [])}
        assert slots & VALUE_SLOTS, f"{iv['id']}: no compound reads a value variable"


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_ids_follow_the_naming_rules(path):
    catalog = load(path)
    assert all(re.fullmatch(r"bdchm:Study/phs\d{6}", s["id"]) for s in catalog["studies"])
    for iv in catalog["integrated_variables"]:
        assert iv["id"].endswith("/" + iv["concept_type"]) and iv["id"].startswith("bdchm:")
    for cv in catalog["compound_variables"]:
        assert re.fullmatch(r"hv:[^#\s]+\.yaml#\d+/" + re.escape(cv["concept_type"]) + r"(/\d+)?", cv["id"])
    for key in ("single_categorical_variables", "single_continuous_variables"):
        for sv in catalog.get(key, []):
            assert sv["id"] == f"dbgap:{sv['source_id']}" and re.fullmatch(r"phv\d{8}", sv["source_id"])


@pytest.mark.parametrize("path", CATALOGS, ids=lambda p: p.name)
def test_placeholder_variable_names_are_flagged(path):
    """Without --dbgap, variable_name is the phv accession; that must be said in a comment."""
    catalog = load(path)
    for key in ("single_categorical_variables", "single_continuous_variables"):
        for sv in catalog.get(key, []):
            if sv["variable_name"] == sv["source_id"]:
                assert "dbGaP details not fetched" in sv.get("comment", ""), sv["id"]


def test_all_catalogs_come_from_one_source_release():
    releases = {load(p)["release"] for p in CATALOGS}
    revisions = {s["revision"] for p in CATALOGS for s in load(p)["sources"]}
    assert len(releases) == 1 and len(revisions) == 1
    (release,), (revision,) = releases, revisions
    assert release == f"hv-{revision[:7]}" or not release.startswith("hv-")
