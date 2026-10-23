# BDC Variable Library

A LinkML-based variable library for BioData Catalyst datasets.

## Background

BDC Variable Library (BDCVL) groups related variables into a single
LinkML slot per concept, so atrial fibrillation (`MONDO:0004981`) is one slot
with a comma-delimited `source_study` / `dataset_accession` /
`variable_accession` annotation, rather than separate near-duplicate records
per study. Concepts are grouped into classes that follow the BioData Catalyst
Harmonized Model (BDCHM), spanning all contributing BioData Catalyst studies.

## Classes

Each class is a BDCHM class, with its own module, and its slots are the
concepts derived as that class. Counts per class and per study are on the
[Stats](stats.md) page.

| Class | Concept identified by | Module |
|---|---|---|
| `Condition` | `condition_concept` | `bdc_varlib_condition.yaml` |
| `MeasurementObservation` | `observation_type` | `bdc_varlib_measurement_observation.yaml` |
| `Observation` | `observation_type` | `bdc_varlib_observation.yaml` |
| `SdohObservation` | `observation_type` | `bdc_varlib_sdoh_observation.yaml` |
| `DrugExposure` | `drug_concept` | `bdc_varlib_drug_exposure.yaml` |
| `Procedure` | `procedure_concept` | `bdc_varlib_procedure.yaml` |

Use the [Schema](elements/index.md) tab to browse every class and slot.

## From class to concept to variable

The library has three levels:

| Level | LinkML construct | Example |
|---|---|---|
| **Class** | class | `Condition` |
| **Concept** | slot, named after its ontology code | `mondo_0004981` (`afib`) |
| **Variable** | annotation entries on a slot | one dbGaP `phv` / `pht` pair |

A concept's slot records every contributing study, and each study can have
several dbGaP variables behind it (one per exam wave, hospital form, or
follow-up survey). Those are stored as comma-delimited lists in the slot's
annotations rather than as separate slots. For atrial fibrillation:

```yaml
mondo_0004981:
  title: afib
  range: ConditionStatusEnum
  annotations:
    concept_id: MONDO:0004981
    concept_name: afib
    bdchm_class: Condition
    source_study: ARIC, CHS, COPDGene, FHS, HCHS, JHS, MESA, WHI
    dataset_accession: pht004037, pht004038, pht004039, ...
    variable_accession: phv00203303, phv00203306, phv00203309, ...
    source_file: ARIC-ingest/afib.yaml, CHS-ingest/afib.yaml, ...
  exact_mappings:
  - MONDO:0004981
```

One slot pools many dbGaP datasets and variables from several cohorts into a
single concept. The [Schema](elements/index.md) tab lists the full
`dataset_accession` and `variable_accession` lists on each slot page.

## Concept names

Slots are identified by ontology code (`concept_id`, also in
`exact_mappings`). The `concept_name` shown next to it is currently taken from
the source file name (for example `afib`, `hist_cor_angio`) and will be
replaced with ontology labels in a later release.

## Structure

- `bdc_varlib.yaml`: the umbrella schema; imports every class module.
- `bdc_varlib_common.yaml`: enums shared across classes (for example
  `ConditionStatusEnum`), so every module is self-contained and can be loaded
  standalone, not only via the umbrella.
- `bdc_varlib_<class>.yaml`: one module per BDCHM class.

## Provenance

Every slot's `annotations` record exactly which studies, dbGaP datasets
(`pht`), and dbGaP variables (`phv`) it was derived from, and the source file
it came from. The concept code (MONDO, OBA, OMOP, RxCUI, ATC, HP and others)
is carried through as a LinkML `exact_mappings` entry.

## Source

Generated from
[RTIInternational/NHLBI-BDC-DMC-HV](https://github.com/RTIInternational/NHLBI-BDC-DMC-HV/tree/main/priority_variables_transform).
