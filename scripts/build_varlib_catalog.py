#!/usr/bin/env python3
"""
build_varlib_catalog.py

Builds the BDC Variable Library portal catalogs: one JSON file per concept
CURIE prefix, src/bdc_varlib/data/varlib_catalog_<prefix>.json (mondo, hpo,
oba, omop, rxcui, atc, ndfrt, vandf, mesh), in the shape of the study-palette
portal-varlib contract (portal-varlib/portal-varlib.yaml, pinned from
study-palette PR #72). This script writes data only; the schema and its
documentation are built separately by build_bdc_varlib.py.

  1. Read every <STUDY>-ingest folder of
     RTIInternational/NHLBI-BDC-DMC-HV/priority_variables_transform. Each
     derivation block that creates a BDCHM Condition, MeasurementObservation,
     Observation, SdohObservation, DrugExposure or Procedure is grouped by
     (BDCHM class, concept code).
  2. Optionally add concept labels (--ontology: MONDO, HP, OBA releases) and
     dbGaP variable details (--dbgap: public data dictionaries).
  3. Build one catalog per prefix: integrated variables (concept + BDCHM
     class), compound variables (one per spec block and study) and single
     variables (one per dbGaP phv), linked by row_metadata.
  4. Validate each catalog with the contract's own
     portal-varlib/validate_catalog.py. Nothing is written if any fails.
  5. Write the catalogs to src/bdc_varlib/data/.

Usage
  python3 scripts/build_varlib_catalog.py --ontology --dbgap           # downloads HV main
  python3 scripts/build_varlib_catalog.py --repo-dir ../NHLBI-BDC-DMC-HV --ontology --dbgap
  python3 scripts/build_varlib_catalog.py --ontology --dbgap --dbgap-only ARIC   # quick dbGaP test
"""
import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import yaml

SOURCE_REPO = "RTIInternational/NHLBI-BDC-DMC-HV"
SOURCE_PATH = "priority_variables_transform"
REPO_TARBALL_URL = f"https://codeload.github.com/{SOURCE_REPO}/tar.gz/refs/heads/main"
SCHEMA_VERSION = "1.0.0"

# BDCHM class -> (concept slot, value slot). Ranges are the BDCHM ranges of the
# value slot (RTIInternational/NHLBI-BDC-DMC-HM, src/bdchm/schema/bdchm.yaml).
CLASS_SLOTS = {
    "Condition": ("condition_concept", "condition_status"),
    "MeasurementObservation": ("observation_type", "value_quantity"),
    "Observation": ("observation_type", "value_quantity"),
    "SdohObservation": ("observation_type", "value_quantity"),
    "DrugExposure": ("drug_concept", "exposure_status"),
    "Procedure": ("procedure_concept", "procedure_status"),
}
STATUS_RANGES = {
    "condition_status": "HistoricalStatusEnum",
    "exposure_status": "HistoricalStatusEnum",
    "procedure_status": "StatusEnum",
}
QUANTITY_RANGES = {"value_decimal": "decimal", "value_integer": "integer",
                   "value_concept": "uriorcurie"}
VALUE_ENUM_RANGE = "BaseObservationValueEnum"

CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*:[\w.\-]+$")
QUOTED_CURIE_RE = re.compile(r"""["']([A-Za-z][A-Za-z0-9]*:[\w.\-]+)["']""")
PHV_RE = re.compile(r"phv\d{8}")
PHT_RE = re.compile(r"^pht\d{6}$")
VISIT_RE = re.compile(r"""\+\s*["']:([^"']+)["']\s*\)""")
CASE_RESULT_RE = re.compile(r""",\s*["']([^"':][^"']*)["']\s*\)""")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def snake(name):
    return slug(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name))


def ordered_unique(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def phvs_in(node):
    """All phv accessions mentioned anywhere in a spec node, in order."""
    return ordered_unique(PHV_RE.findall(json.dumps(node, sort_keys=False)))


def class_items(class_derivations):
    """class_derivations is a dict or a list of single-key dicts."""
    if isinstance(class_derivations, dict):
        return list(class_derivations.items())
    items = []
    for item in class_derivations or []:
        if isinstance(item, dict):
            items.extend(item.items())
    return items


def scalar(node, key="value"):
    if isinstance(node, dict) and isinstance(node.get(key), str) and node[key].strip():
        return node[key].strip()
    return None


def prefix_of(code):
    """File stem for a concept code: its CURIE prefix as written (MONDO, HP, RxCUI), else 'other'."""
    return code.split(":", 1)[0] if CURIE_RE.match(code) else "other"


# --------------------------------------------------------------------------- #
# Reading the specs
# --------------------------------------------------------------------------- #

def load_spec(path):
    # BaseLoader keeps every scalar as written: '1', 'Y', 'yes' stay strings,
    # so value mappings are not turned into ints or booleans.
    with open(path, encoding="utf-8") as fh:
        content = yaml.load(fh, Loader=yaml.BaseLoader)
    if isinstance(content, dict):
        content = [content]
    return content if isinstance(content, list) else []


def read_study(folder):
    """First ResearchStudy with a dbGaP accession in the folder's study spec."""
    candidates = sorted(glob.glob(os.path.join(folder, "research*study*.yaml")))
    for path in candidates:
        for block in load_spec(path):
            for cls, body in class_items((block or {}).get("class_derivations")):
                if cls != "ResearchStudy":
                    continue
                slots = body.get("slot_derivations") or {}
                accession = scalar(slots.get("accession_number"))
                if accession:
                    study = {
                        "id": f"bdchm:Study/{accession}",
                        "accession_number": accession,
                        "study_version": scalar(slots.get("version")),
                        "study_name": scalar(slots.get("name_shortened")) or os.path.basename(folder),
                        "study_title": scalar(slots.get("name")),
                        "ingest_folder": os.path.basename(folder),
                    }
                    return {k: v for k, v in study.items() if v is not None}
    return None


def concept_codes(node, concept_slot):
    """Return (codes, concept_expression, phvs used to pick the concept)."""
    if node is None:
        return [], None, []
    fixed = scalar(node)
    if fixed:
        return [fixed], None, []
    if isinstance(node, dict) and node.get("expr"):
        expr = str(node["expr"])
        return ordered_unique(QUOTED_CURIE_RE.findall(expr)), expr, phvs_in(expr)
    if isinstance(node, dict) and node.get("value_mappings"):
        mappings = node["value_mappings"]
        column = node.get("populated_from", "")
        codes = ordered_unique(str(v) for v in mappings.values() if CURIE_RE.match(str(v)))
        text = f"{concept_slot} from {column}: " + ", ".join(
            f"{k} -> {v}" for k, v in mappings.items())
        return codes, text, phvs_in(column)
    return [], None, []


def value_details(slots, value_slot):
    """Return (bdchm value slot, range, phvs, value mappings, expression, unit)."""
    if value_slot == "value_quantity":
        quantity = slots.get("value_quantity")
        if isinstance(quantity, dict):
            for _, qbody in class_items(quantity.get("class_derivations")):
                qslots = (qbody or {}).get("slot_derivations") or {}
                unit_node = qslots.get("unit")
                unit = scalar(unit_node) or scalar(unit_node, "expr")
                for key, rng in QUANTITY_RANGES.items():
                    node = qslots.get(key)
                    if isinstance(node, dict):
                        phvs = phvs_in(node)
                        expr = node.get("expr")
                        return ("value_quantity", rng, phvs, node.get("value_mappings"),
                                str(expr) if expr else None, unit)
        enum_node = slots.get("value_enum")
        if isinstance(enum_node, dict):
            expr = enum_node.get("expr")
            return ("value_enum", VALUE_ENUM_RANGE, phvs_in(enum_node),
                    enum_node.get("value_mappings"), str(expr) if expr else None, None)
        return ("value_quantity", None, [], None, None, None)
    node = slots.get(value_slot)
    if isinstance(node, dict):
        expr = node.get("expr")
        return (value_slot, STATUS_RANGES.get(value_slot), phvs_in(node),
                node.get("value_mappings"), str(expr) if expr else None, None)
    return (value_slot, STATUS_RANGES.get(value_slot), [], None, None, None)


def visit_label(node):
    """Visit name from an associated_visit derivation.

    Most specs build the visit id as uuid5(..., str({phv}) + ":ARIC EXAM 1").
    Some choose the visit with case(), e.g. FHS: + ":" + case(({phv} == '1',
    'FHS OFFSPRING EXAM 9'), ...); then every possible visit is listed.
    """
    expr = scalar(node, "expr") or scalar(node)
    if not expr:
        return None
    match = VISIT_RE.search(expr)
    if match:
        return [match.group(1).strip()]
    options = [o for o in CASE_RESULT_RE.findall(expr) if "UNKNOWN" not in o.upper()]
    return ordered_unique(options) or None


def extract(cls, body, context):
    """Turn one derivation body into zero or more records (one per concept code)."""
    concept_slot, value_slot = CLASS_SLOTS[cls]
    slots = body.get("slot_derivations") or {}
    codes, concept_expr, concept_phvs = concept_codes(slots.get(concept_slot), concept_slot)
    if not codes:
        return [], "no concept code"
    bdchm_value_slot, value_range, value_phvs, mappings, value_expr, unit = value_details(
        slots, value_slot)
    variables = value_phvs or concept_phvs
    if not variables:
        return [], "no dbGaP variable"

    supporting = []
    used = set(variables)
    for name, node in slots.items():
        if name in (concept_slot, bdchm_value_slot):
            continue
        for phv in phvs_in(node):
            if phv not in used:
                supporting.append({"variable_accession": phv, "bdchm_slot": name})
                used.add(phv)
    if concept_expr:
        for phv in concept_phvs:
            if phv not in used:
                supporting.append({"variable_accession": phv, "bdchm_slot": concept_slot})
                used.add(phv)

    visit_node = slots.get("associated_visit") or context.get("visit_node") or {}
    provenance = next((scalar(n) for k, n in slots.items() if k.endswith("_provenance")), None)
    evidence = scalar(slots.get("associated_evidence")) or scalar(slots.get("associated_evidence"), "expr")
    pht = body.get("populated_from") or context.get("pht")

    base = {
        "dataset_accession": pht if pht and PHT_RE.match(str(pht)) else None,
        "variable_accessions": variables,
        "supporting_variables": supporting or None,
        "visit": visit_label(visit_node),
        "bdchm_provenance": provenance,
        "evidence": evidence,
        "method": scalar(slots.get("method_type")),
        "unit": unit,
        "value_mappings": [{"source_value": str(k), "harmonized_value": str(v)}
                           for k, v in (mappings or {}).items()] or None,
        "derivation_expression": value_expr,
        "concept_expression": concept_expr,
    }
    return [{"code": code, "bdchm_class": cls, "concept_slot": concept_slot,
             "value_slot": bdchm_value_slot, "value_range": value_range, **base}
            for code in codes], None


def walk(class_derivations, context, out, skipped):
    for cls, body in class_items(class_derivations):
        if not isinstance(body, dict):
            continue
        slots = body.get("slot_derivations") or {}
        if cls in CLASS_SLOTS:
            records, reason = extract(cls, body, context)
            if records:
                out.extend({**r, **{k: context[k] for k in ("source_file", "source_index")}}
                           for r in records)
            else:
                skipped[f"{cls}: {reason}"].append(f"{context['source_file']}#{context['source_index']}")
        # nested derivations (e.g. MeasurementObservation inside MeasurementObservationSet)
        child_context = dict(context)
        child_context["pht"] = body.get("populated_from") or context.get("pht")
        if slots.get("associated_visit"):
            child_context["visit_node"] = slots["associated_visit"]
        for name, sub in slots.items():
            if name == "value_quantity" and cls in CLASS_SLOTS:
                continue
            if isinstance(sub, dict) and "class_derivations" in sub:
                walk(sub["class_derivations"], child_context, out, skipped)


def read_source(transform_dir):
    studies, records = {}, []
    skipped = collections.defaultdict(list)
    folders = sorted(d for d in glob.glob(os.path.join(transform_dir, "*-ingest")) if os.path.isdir(d))
    for folder in folders:
        study = read_study(folder)
        if study is None:
            print(f"  ! {os.path.basename(folder)}: no ResearchStudy with an accession; skipped",
                  file=sys.stderr)
            continue
        studies[study["accession_number"]] = study
        for path in sorted(glob.glob(os.path.join(folder, "*.yaml"))):
            rel = f"{os.path.basename(folder)}/{os.path.basename(path)}"
            try:
                blocks = load_spec(path)
            except yaml.YAMLError as exc:
                skipped["unparseable file"].append(f"{rel}: {exc}")
                continue
            for index, block in enumerate(blocks):
                if isinstance(block, dict) and "class_derivations" in block:
                    context = {"source_file": rel, "source_index": index}
                    found = []
                    walk(block["class_derivations"], context, found, skipped)
                    for record in found:
                        record["study_id"] = study["accession_number"]
                    records.extend(found)
    return folders, studies, records, skipped


# --------------------------------------------------------------------------- #
# Building the library
# --------------------------------------------------------------------------- #


USAGE_FIELDS = ("visit", "bdchm_provenance", "evidence", "method", "harmonized_unit", "value_mappings",
                "derivation_expression", "concept_expression")


def usage_of(record):
    """How one spec block uses its value variables (the flat fields of a SourceVariable)."""
    usage = {
        "visit": record["visit"],
        "bdchm_provenance": record["bdchm_provenance"],
        "evidence": record["evidence"],
        "method": record["method"],
        "harmonized_unit": record["unit"],
        "value_mappings": record["value_mappings"],
        "derivation_expression": record["derivation_expression"],
        "concept_expression": record["concept_expression"],
        "source_file": record["source_file"],
        "source_index": record["source_index"],
    }
    return {k: v for k, v in usage.items() if v is not None}


def same_usage(a, b):
    return all(a.get(k) == b.get(k) for k in USAGE_FIELDS)


def source_variable(phv, record, role, bdchm_slot):
    variable = {
        "id": f"dbgap:{phv}",
        "associated_study": f"bdchm:Study/{record['study_id']}",
        "variable_description": f"Source for {record['bdchm_class']}.{bdchm_slot}",
        "source_id": phv,
        "file_id": record["dataset_accession"],
        "variable_role": role,
        "bdchm_slot": bdchm_slot,
    }
    return {k: v for k, v in variable.items() if v is not None}


def build_concepts(records):
    """Group records into flat concepts: concept -> its dbGaP source variables, once each.

    A variable used by several blocks of one concept keeps the first block's usage; a later
    block that uses it differently is kept under additional_derivations.
    """
    grouped = collections.OrderedDict()
    for record in sorted(records, key=lambda r: (r["bdchm_class"], r["code"], r["study_id"],
                                                 r["source_file"], r["source_index"])):
        grouped.setdefault((record["bdchm_class"], record["code"]), []).append(record)

    concepts = []
    for (cls, code), group in grouped.items():
        value_slots = ordered_unique(r["value_slot"] for r in group)
        value_ranges = ordered_unique(r["value_range"] for r in group)
        variables = collections.OrderedDict()
        for r in group:
            usage = usage_of(r)
            for phv in r["variable_accessions"]:
                current = variables.get(phv)
                if current is None or current["variable_role"] == "supporting":
                    variables[phv] = {**source_variable(phv, r, "value", r["value_slot"]), **usage}
                elif not same_usage(current, usage):
                    current.setdefault("additional_derivations", []).append(usage)
            for support in r["supporting_variables"] or []:
                phv = support["variable_accession"]
                if phv not in variables:
                    variables[phv] = source_variable(phv, r, "supporting", support["bdchm_slot"])
        concept = {
            "concept_id": code,
            "bdchm_class": cls,
            "bdchm_concept_slot": group[0]["concept_slot"],
            "bdchm_value_slot": value_slots[0] if len(value_slots) == 1 else None,
            "value_range": value_ranges[0] if len(value_ranges) == 1 else None,
            "source_names": ordered_unique(
                os.path.splitext(os.path.basename(r["source_file"]))[0] for r in group),
            "source_variables": list(variables.values()),
        }
        concepts.append({k: v for k, v in concept.items() if v is not None})
    return concepts


def studies_of(concepts):
    return sorted({v["associated_study"] for c in concepts for v in c["source_variables"]})


def split_by_prefix(concepts, studies, source, library_version):
    by_id = {s["id"]: s for s in studies.values()}
    files = {}
    for concept in concepts:
        files.setdefault(prefix_of(concept["concept_id"]), []).append(concept)
    libraries = {}
    for prefix, group in sorted(files.items()):
        libraries[prefix] = {
            "schema_version": SCHEMA_VERSION,
            "library_version": library_version,
            "curie_prefix": prefix,
            "source": source,
            "studies": [by_id[s] for s in studies_of(group)],
            "integrated_concepts": group,
        }
    return libraries


def count_values(concepts):
    return sum(1 for c in concepts for v in c["source_variables"] if v["variable_role"] == "value")



# ---- source acquisition
def source_from_clone(repo_dir):
    transform = os.path.join(repo_dir, SOURCE_PATH)
    if not os.path.isdir(transform):
        sys.exit(f"{transform} not found")
    try:
        commit = subprocess.check_output(["git", "-C", repo_dir, "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return transform, commit


def source_from_tarball(tmp_dir):
    tarball = os.path.join(tmp_dir, "repo.tar.gz")
    print(f"Downloading {REPO_TARBALL_URL} ...")
    urllib.request.urlretrieve(REPO_TARBALL_URL, tarball)
    with tarfile.open(tarball) as tf:
        commit = tf.pax_headers.get("comment")  # GitHub stores the commit SHA here
        members = [m for m in tf.getmembers() if f"/{SOURCE_PATH}/" in m.name and m.isfile()
                   and m.name.endswith(".yaml") and ".." not in m.name]
        tf.extractall(tmp_dir, members=members)
    (root,) = [d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))]
    return os.path.join(tmp_dir, root, SOURCE_PATH), commit



# ---- ontology
RELEASES = {
    "MONDO": "https://github.com/monarch-initiative/mondo/releases/latest/download/mondo.obo",
    "HP": "https://github.com/obophenotype/human-phenotype-ontology/releases/latest/download/hp.obo",
    "OBA": "https://github.com/obophenotype/bio-attribute-ontology/releases/latest/download/oba.obo",
}


def parse_obo(path, prefix):
    """Return (data-version, {id: (name, obsolete, replaced_by)}) for this ontology's own terms."""
    version, terms, term = None, {}, None

    def keep(t):
        if t and t.get("id", "").startswith(prefix + ":") and t.get("name"):
            terms[t["id"]] = (t["name"], t["obsolete"], t["replaced_by"])

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if version is None and line.startswith("data-version:"):
                version = line.split(":", 1)[1].strip().rsplit("/", 1)[-1]
            if line.startswith("["):
                keep(term)
                term = {"obsolete": False, "replaced_by": ""} if line == "[Term]" else None
                continue
            if term is None or ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if key == "id":
                term["id"] = value
            elif key == "name":
                term["name"] = value
            elif key == "is_obsolete" and value == "true":
                term["obsolete"] = True
            elif key == "replaced_by":
                term["replaced_by"] = value
    keep(term)
    return version, terms


def obo_file(prefix, obo_dir):
    path = os.path.join(obo_dir, f"{prefix.lower()}.obo")
    if not os.path.exists(path):
        os.makedirs(obo_dir, exist_ok=True)
        print(f"Downloading {RELEASES[prefix]} ...")
        urllib.request.urlretrieve(RELEASES[prefix], path)
    return path


def load_manual(path):
    labels = {}
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if line.startswith(("#", "curie\t")) or len(parts) < 2 or not parts[1]:
                    continue
                labels[parts[0]] = (parts[1], parts[2] if len(parts) > 2 and parts[2] else "manual")
    return labels


def with_name(concept, name, source):
    """Return the concept with concept_name and concept_name_source right after concept_id."""
    out = {}
    for key, value in concept.items():
        if key in ("concept_name", "concept_name_source"):
            continue
        out[key] = value
        if key == "concept_id":
            out["concept_name"] = name
            out["concept_name_source"] = source
    return out



# ---- dbgap
DBGAP = "https://ftp.ncbi.nlm.nih.gov/dbgap/studies"
STUDY_DIR_RE = re.compile(r'href="(phs\d{6}\.v(\d+)\.p(\d+))/"')
DICT_RE = re.compile(r'href="((phs\d{6}\.v\d+)\.(pht\d{6})\.v(\d+)\.(.+?)\.data_dict\.xml)"')
DBGAP_FIELDS = ("file_name", "variable_name", "source_variable_description", "data_type", "unit",
                "minimum_value", "maximum_value", "coded_values")


class Fetcher:
    """GET with a disk cache and a polite pause between network requests."""

    def __init__(self, cache_dir, pause=0.34):
        self.cache_dir, self.pause = cache_dir, pause

    def get(self, url):
        path = os.path.join(self.cache_dir, re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1]))
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read()
        request = urllib.request.Request(url, headers={"User-Agent": "bdc-varlib/1.0"})
        for attempt in range(3):
            try:
                time.sleep(self.pause)
                with urllib.request.urlopen(request, timeout=60) as response:
                    text = response.read().decode("utf-8", errors="replace")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if attempt == 2:
                    raise
            except urllib.error.URLError:
                if attempt == 2:
                    raise
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return text


def data_type(dbgap_type, has_codes):
    t = (dbgap_type or "").lower()
    if "encoded" in t or (has_codes and not any(w in t for w in ("decimal", "integer"))):
        return "enum"
    for word, value in (("integer", "integer"), ("decimal", "decimal"), ("float", "decimal"),
                        ("numeric", "numeric"), ("string", "string"), ("text", "string"),
                        ("date", "string"), ("boolean", "boolean")):
        if word in t:
            return value
    return None


def number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def parse_data_dict(xml_text, table_name):
    """Return {phv: details} for one dbGaP data_dict.xml."""
    root = ET.fromstring(xml_text)
    variables = {}
    for var in root.iter("variable"):
        phv = (var.get("id") or "").split(".")[0]
        if not phv.startswith("phv"):
            continue
        codes = [{"indicator_char": v.get("code"), "indicator_meaning": (v.text or "").strip()}
                 for v in var.findall("value") if v.get("code") is not None]
        details = {
            "file_name": table_name,
            "variable_name": (var.findtext("name") or "").strip() or None,
            "source_variable_description": (var.findtext("description") or "").strip() or None,
            "data_type": data_type(var.findtext("type"), bool(codes)),
            "unit": (var.findtext("unit") or "").strip() or None,
            "minimum_value": number(var.findtext("logical_min")),
            "maximum_value": number(var.findtext("logical_max")),
            "coded_values": codes or None,
        }
        variables[phv] = {k: v for k, v in details.items() if v is not None}
    return variables


def study_dictionaries(fetcher, accession, version):
    """Return (study dir used, {pht: (url, table name)}) for one study."""
    listing = fetcher.get(f"{DBGAP}/{accession}/") or ""
    dirs = sorted(((int(v), int(p), d) for d, v, p in STUDY_DIR_RE.findall(listing)), reverse=True)
    if not dirs:
        return None, {}
    chosen = next((d for v, p, d in dirs if str(v) == str(version)), dirs[0][2])
    base = f"{DBGAP}/{accession}/{chosen}/pheno_variable_summaries/"
    tables = {}
    for filename, _, pht, pht_version, table_name in DICT_RE.findall(fetcher.get(base) or ""):
        current = tables.get(pht)
        if current is None or int(pht_version) > current[2]:
            tables[pht] = (base + filename, table_name, int(pht_version))
    return chosen, {pht: (url, name) for pht, (url, name, _) in tables.items()}


def ordered(variable, details):
    """Variable with dbGaP fields placed after file_id, in schema order."""
    base = {k: v for k, v in variable.items() if k not in DBGAP_FIELDS}
    out = {}
    for key, value in base.items():
        out[key] = value
        if key == "file_id":
            out.update({k: details[k] for k in DBGAP_FIELDS if k in details})
    return out



# --------------------------------------------------------------------------- #
# Enrichment (optional): ontology names and dbGaP details
# --------------------------------------------------------------------------- #

def add_ontology_names(libraries, obo_dir, manual_path):
    manual = load_manual(manual_path)
    named = 0
    for prefix, library in libraries.items():
        terms, source = {}, None
        if prefix in RELEASES:
            version, terms = parse_obo(obo_file(prefix, obo_dir), prefix)
            source = f"{prefix} {version}" if version else prefix
        concepts = []
        for concept in library["integrated_concepts"]:
            code = concept["concept_id"]
            if code in terms:
                name, obsolete, replaced_by = terms[code]
                if obsolete:
                    hint = f", replaced by {replaced_by}" if replaced_by else ""
                    print(f"  ! {code} is obsolete in {source}{hint}")
                concept = with_name(concept, name, source)
                named += 1
            elif code in manual:
                concept = with_name(concept, *manual[code])
                named += 1
            concepts.append(concept)
        library["integrated_concepts"] = concepts
    total = sum(len(lib["integrated_concepts"]) for lib in libraries.values())
    print(f"Ontology: named {named} of {total} concepts")


def add_dbgap_details(libraries, cache_dir, only=None):
    fetcher = Fetcher(cache_dir)
    studies = {s["id"]: s for lib in libraries.values() for s in lib["studies"]}
    if only:
        studies = {k: s for k, s in studies.items() if s["study_name"] == only}
    details, missing_tables = {}, set()
    for study_id, study in sorted(studies.items()):
        wanted = {v["file_id"] for lib in libraries.values() for c in lib["integrated_concepts"]
                  for v in c["source_variables"] if v["associated_study"] == study_id and v.get("file_id")}
        chosen, tables = study_dictionaries(fetcher, study["accession_number"], study.get("study_version"))
        if chosen is None:
            print(f"  ! {study['study_name']}: no study folder at dbGaP")
            continue
        note = "" if chosen.startswith(f"{study['accession_number']}.v{study.get('study_version')}.") else \
            f" (specs use v{study.get('study_version')}; not on dbGaP)"
        print(f"dbGaP {study['study_name']}: {chosen}{note}, {len(wanted)} tables")
        for pht in sorted(wanted):
            if pht not in tables:
                missing_tables.add((study["study_name"], pht))
                continue
            url, table_name = tables[pht]
            text = fetcher.get(url)
            if text:
                details.update(parse_data_dict(text, table_name))
    filled = total = 0
    for library in libraries.values():
        for concept in library["integrated_concepts"]:
            updated = []
            for variable in concept["source_variables"]:
                if variable["associated_study"] in studies:
                    total += 1
                    if variable["source_id"] in details:
                        variable = ordered(variable, details[variable["source_id"]])
                        filled += 1
                updated.append(variable)
            concept["source_variables"] = updated
    print(f"dbGaP: filled {filled} of {total} source variables")
    for name, pht in sorted(missing_tables):
        print(f"  ! {name}: no data dictionary for {pht}")


# --------------------------------------------------------------------------- #
# Portal catalogs (study-palette PR #72 portal-varlib contract)
# --------------------------------------------------------------------------- #

CATALOG_DIR = os.path.join("src", "bdc_varlib", "data")
CONTRACT_DIR = "portal-varlib"
PORTAL_CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*:[A-Za-z0-9._-]+$")
BDCHM_TYPES = {"Condition": "condition", "MeasurementObservation": "observation", "Observation": "observation",
               "SdohObservation": "observation", "DrugExposure": "drugexposure", "Procedure": "procedure"}
# BDCHM slot names used in the specs -> bdc-variable-library ClinicalMicroschemaEnum
MICROSCHEMA = {
    "condition_status": "condition_status", "exposure_status": "exposure_status",
    "procedure_status": "procedure_status", "value_quantity": "measurement_value",
    "value_enum": "measurement_value", "associated_participant": "subject_identifier",
    "associated_visit": "relative_timing", "age_at_observation": "age_at_measurement",
    "age_at_condition_start": "age_at_condition_start", "age_at_condition_end": "age_at_condition_end",
    "age_at_exposure_start": "age_at_drug_start", "age_at_procedure": "age_at_procedure_start",
    "drug_concept": "drug_type", "condition_concept": "condition_type", "observation_type": "measurement_type",
    "procedure_concept": "procedure_type", "condition_provenance": "condition_provenance",
    "condition_severity": "condition_severity", "method_type": "method",
}
CONCEPT_SLOT_MICROSCHEMA = {"Condition": "condition_type", "DrugExposure": "drug_type",
                            "Procedure": "procedure_type"}  # everything else: measurement_type
# bdc-variable-library only accepts MONDO or HP codes as a condition_type, so other condition
# codes stay in concept_type only. Provenance and method are kept in the compound's description:
# its ProvenanceEnum and MethodEnum use other vocabularies than the BDCHM values in the specs.
CONDITION_TYPE_RE = re.compile(r"^(MONDO|HP):\d{7}$")
CONTINUOUS_TYPES = {"decimal", "integer", "numeric"}


def catalog_stem(prefix):
    return f"varlib_catalog_{file_stem(prefix)}"


def compound_description(r):
    parts = []
    if r["bdchm_provenance"]:
        parts.append(f"provenance: {r['bdchm_provenance']}")
    if r["method"]:
        parts.append(f"method: {r['method']}")
    if r["value_mappings"]:
        parts.append(f"{r['value_slot']}: " + "; ".join(f"{m['source_value']} -> {m['harmonized_value']}"
                                                    for m in r["value_mappings"]))
    if r["derivation_expression"]:
        parts.append(f"{r['value_slot']} = {r['derivation_expression']}")
    if r["concept_expression"]:
        parts.append(f"applies when: {r['concept_expression']}")
    return " | ".join(parts) or None


def single_variable(phv, r, slot, role, details, study_id, source_id):
    found = details.get(phv, {})
    continuous = (found.get("data_type") in CONTINUOUS_TYPES if found.get("data_type")
                  else role == "value" and r["value_range"] in ("decimal", "integer"))
    record = {
        "id": f"dbgap:{phv}",
        "variable_name": found.get("variable_name") or phv,
        "variable_description": f"Source for {r['bdchm_class']}.{slot}",
        "associated_study": study_id,
        "source_id": phv,
        "file_id": found.get("file_id") or r["dataset_accession"],
        "file_name": found.get("file_name"),
        "source_variable_description": found.get("source_variable_description"),
        "data_type": found.get("data_type"),
    }
    if continuous:
        record.update({"unit": found.get("unit"), "minimum_value": found.get("minimum_value"),
                       "maximum_value": found.get("maximum_value")})
    elif found.get("coded_values"):
        record["coded_values"] = found["coded_values"]
    if not found.get("variable_name"):
        record["comment"] = "variable_name is the dbGaP accession; dbGaP details not fetched"
    record["metadata_sources"] = [source_id]
    return continuous, {k: v for k, v in record.items() if v is not None}


def build_catalogs(records, libraries, studies, source, release):
    """One portal catalog per concept CURIE prefix, in the shape of portal-varlib.yaml."""
    names = {(c["concept_id"], c["bdchm_class"]): c.get("concept_name")
             for lib in libraries.values() for c in lib["integrated_concepts"]}
    details = {v["source_id"]: v for lib in libraries.values() for c in lib["integrated_concepts"]
               for v in c["source_variables"]}
    by_prefix, skipped = collections.defaultdict(list), set()
    for r in records:
        if PORTAL_CURIE_RE.match(r["code"]):
            by_prefix[prefix_of(r["code"])].append(r)
        else:
            skipped.add(r["code"])
    for code in sorted(skipped):
        print(f"  ! {code} is not a CURIE; left out of the portal catalogs (the contract needs a CURIE)")

    catalogs = {}
    for prefix, recs in sorted(by_prefix.items()):
        sources, concepts, integrated, compounds = {}, {}, {}, {}
        singles = {"categorical": {}, "continuous": {}}
        used_studies = set()
        for r in sorted(recs, key=lambda r: (r["bdchm_class"], r["code"], r["study_id"],
                                             r["source_file"], r["source_index"])):
            code, cls = r["code"], r["bdchm_class"]
            name = names.get((code, cls))
            source_id = f"hv:{r['source_file']}"
            sources[source_id] = {"source_id": source_id, "repository": source["repository"],
                                  "revision": source["commit"], "path": f"{source['path']}/{r['source_file']}"}
            if code not in concepts or (name and "label" not in concepts[code]):
                concepts[code] = {"curie": code, **({"label": name} if name else {})}
            study = studies[r["study_id"]]
            study_id = study["id"]
            used_studies.add(study_id)

            base_id = f"hv:{r['source_file']}#{r['source_index']}/{code}"
            compound_id, n = base_id, 1
            while compound_id in compounds:  # one block can derive the same concept several times
                n += 1
                compound_id = f"{base_id}/{n}"
            label = " · ".join([study["study_name"], *(r["visit"] or []), *([r["evidence"]] if r["evidence"] else [])])
            row_metadata = []
            for phv in r["variable_accessions"]:
                row_metadata.append((phv, r["value_slot"], "value"))
            for support in r["supporting_variables"] or []:
                row_metadata.append((support["variable_accession"], support["bdchm_slot"], "supporting"))
            documentation = []
            if cls != "Condition" or CONDITION_TYPE_RE.match(code):
                documentation.append({"contr_vocab": code,
                                      "microschema_slot": [CONCEPT_SLOT_MICROSCHEMA.get(cls, "measurement_type")]})
            if r["evidence"]:
                documentation.append({"contr_vocab": r["evidence"], "microschema_slot": ["associated_evidence"]})
            compound = {
                "id": compound_id,
                "variable_label": label,
                "variable_description": compound_description(r),
                "associated_study": study_id,
                "concept_type": code,
                "bdchm_type": BDCHM_TYPES[cls],
                "unit": r["unit"],
                "metadata_sources": [source_id],
                "row_metadata": [{"id": f"dbgap:{phv}",
                                  **({"microschema_slot": [MICROSCHEMA[slot]]} if slot in MICROSCHEMA else {})}
                                 for phv, slot, _ in row_metadata],
                "documentation_metadata": documentation or None,
            }
            compounds[compound_id] = {k: v for k, v in compound.items() if v is not None}

            integrated_id = f"bdchm:{cls}/{code}"
            iv = integrated.setdefault(integrated_id, {
                "id": integrated_id,
                "variable_label": name or f"{code} ({cls})",
                "variable_description": f"{code} derived as BDCHM {cls}.{r['concept_slot']}"
                                        + (f"; value in {r['value_slot']} ({r['value_range']})" if r["value_range"] else ""),
                "concept_type": code,
                "bdchm_type": BDCHM_TYPES[cls],
                "integrates": [],
                "metadata_sources": [],
            })
            iv["integrates"].append(compound_id)
            if source_id not in iv["metadata_sources"]:
                iv["metadata_sources"].append(source_id)

            for phv, slot, role in row_metadata:
                kind_seen = "continuous" if f"dbgap:{phv}" in singles["continuous"] else (
                    "categorical" if f"dbgap:{phv}" in singles["categorical"] else None)
                if kind_seen:
                    record = singles[kind_seen][f"dbgap:{phv}"]
                    if source_id not in record["metadata_sources"]:
                        record["metadata_sources"].append(source_id)
                    continue
                continuous, record = single_variable(phv, r, slot, role, details, study_id, source_id)
                singles["continuous" if continuous else "categorical"][record["id"]] = record

        catalog = {
            "schema_version": 3,
            "release": release,
            "sources": list(sources.values()),
            "concepts": list(concepts.values()),
            "studies": [{"id": s["id"], "study_name": s["study_name"]}
                        for s in sorted(studies.values(), key=lambda s: s["study_name"]) if s["id"] in used_studies],
            "integrated_variables": list(integrated.values()),
            "compound_variables": list(compounds.values()),
        }
        if singles["categorical"]:
            catalog["single_categorical_variables"] = list(singles["categorical"].values())
        if singles["continuous"]:
            catalog["single_continuous_variables"] = list(singles["continuous"].values())
        catalogs[prefix] = catalog
    return catalogs


def contract_validator(contract_dir):
    """validate_catalog() from the pinned study-palette portal-varlib folder."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("portal_validate_catalog",
                                                  os.path.join(contract_dir, "validate_catalog.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_catalog


def write_catalogs(catalog_dir, catalogs):
    os.makedirs(catalog_dir, exist_ok=True)
    for old in glob.glob(os.path.join(catalog_dir, "varlib_catalog_*.json")):
        os.remove(old)
    for prefix, catalog in catalogs.items():
        path = os.path.join(catalog_dir, f"{catalog_stem(prefix)}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        singles = len(catalog.get("single_categorical_variables", [])) + len(catalog.get("single_continuous_variables", []))
        print(f"  wrote {path}: {len(catalog['integrated_variables'])} integrated, "
              f"{len(catalog['compound_variables'])} compound, {singles} single variables")


FILE_STEMS = {"HP": "hpo"}  # file names follow the ontology's usual name


def file_stem(prefix):
    return FILE_STEMS.get(prefix, prefix.lower())


def build(transform_dir, commit, args):
    if not commit or not re.fullmatch(r"[0-9a-f]{40}", commit):
        sys.exit("Could not determine the source commit; pass --commit <sha>.")
    folders, studies, records, skipped = read_source(transform_dir)
    print(f"Read {len(folders)} ingest folders, {len(studies)} studies, {len(records)} derivations")
    for reason, where in sorted(skipped.items()):
        for location in where:
            print(f"  ! not included ({reason}): {location}")
    source = {"repository": SOURCE_REPO, "commit": commit, "path": SOURCE_PATH}
    libraries = split_by_prefix(build_concepts(records), studies, source,
                                args.library_version or f"hv-{commit[:7]}")
    if args.ontology:
        add_ontology_names(libraries, args.obo_dir, args.manual_labels)
    if args.dbgap:
        add_dbgap_details(libraries, args.dbgap_cache, args.dbgap_only)

    release = args.library_version or f"hv-{commit[:7]}"
    catalogs = build_catalogs(records, libraries, studies, source, release)
    validate = contract_validator(args.contract_dir)
    failed = False
    for prefix, catalog in catalogs.items():
        errors = validate(catalog)
        if errors:
            failed = True
            print(f"  ! {catalog_stem(prefix)}: {len(errors)} errors against portal-varlib.yaml")
            for error in errors[:10]:
                print(f"      {error}")
    if failed:
        sys.exit("Catalog validation against portal-varlib.yaml failed; nothing written.")
    print(f"Validated {len(catalogs)} catalogs against {args.contract_dir}/portal-varlib.yaml")

    write_catalogs(args.catalog_dir, catalogs)
    return catalogs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", help="local clone of NHLBI-BDC-DMC-HV (default: download main)")
    parser.add_argument("--commit", help="source commit SHA, if it cannot be read automatically")
    parser.add_argument("--contract-dir", default=CONTRACT_DIR,
                        help="pinned study-palette portal-varlib folder (portal-varlib.yaml, validate_catalog.py)")
    parser.add_argument("--catalog-dir", default=CATALOG_DIR, help="where the portal catalogs are written")
    parser.add_argument("--library-version", help="library version to record (default: hv-<commit>)")
    parser.add_argument("--ontology", action="store_true", help="add concept names from MONDO, HP and OBA")
    parser.add_argument("--obo-dir", default=".cache/ontologies", help="OBO files, downloaded if missing")
    parser.add_argument("--manual-labels", default="scripts/labels_manual.tsv",
                        help="names for codes with no OBO release (curie, label, source)")
    parser.add_argument("--dbgap", action="store_true", help="add variable details from dbGaP data dictionaries")
    parser.add_argument("--dbgap-cache", default=".cache/dbgap", help="dbGaP download cache")
    parser.add_argument("--dbgap-only", help="limit dbGaP lookups to one study, e.g. ARIC")
    args = parser.parse_args(argv)
    if args.repo_dir:
        transform, commit = source_from_clone(args.repo_dir)
        return build(transform, args.commit or commit, args)
    with tempfile.TemporaryDirectory() as tmp:
        transform, commit = source_from_tarball(tmp)
        return build(transform, args.commit or commit, args)


if __name__ == "__main__":
    main()
