# Portal variable-library contract

`portal-varlib.yaml` defines the producer catalog. It extends pinned upstream IntegratedVariable, CompoundVariable, ResearchStudy and single-variable classes. `terms-response.yaml` defines a small harmonized-search projection for middleware. Both reuse `Term` from `schema/terms.yaml`.

## Producing catalogs

One catalog per concept CURIE prefix is supported. Partition integrated variables by `concept_type` prefix; use the same `schema_version: 3` and release across the collection. Each catalog includes its referenced compounds, studies, concepts, provenance and any source-variable records used by `row_metadata`. Shared identities remain stable across files.

An integrated variable has its own ID and links to study-specific compound variables through `integrates`. Each compound identifies its study. Source-variable references in `row_metadata` resolve to supplied single-variable definitions for that study. Several integrated variables can describe the same concept.

`concepts` remains a list of objects with `curie` and optional `label`; reusing Term adds optional `vocabulary` and `parents` without requiring a producer change. Each concept needs its curie for reference resolution. Parent references may resolve in the separate term graph; they need not be copied into every prefix file. Missing parents means hierarchy was not supplied, not that the concept is a root or leaf.

## Serving terms

The Java middleware loads the catalogs as one searchable collection, groups by concept, preserves integrated-variable identities and derives mapped study counts from distinct study references. The response fixture illustrates the metadata projection; it is separate from the deployed mixed Monarch/BDC GraphQL pagination contract. The schema files alone do not modify the endpoint or its query fields.

Ontology hierarchy belongs to the shared term graph. The middleware can enrich concept metadata by CURIE when that data is available. These catalogs do not provide participant totals or a complete ontology graph.

