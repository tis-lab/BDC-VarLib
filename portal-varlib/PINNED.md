# portal-varlib contract (pinned copy)

Copied unchanged from
[tis-lab/study-palette PR #72](https://github.com/tis-lab/study-palette/pull/72),
`schema/proposals/portal-varlib/` at commit `d4295b3`
(branch `feature/104-portal-varlib-contract`).

`scripts/build_bdc_varlib.py` validates every catalog it writes with
`validate_catalog.py` from this folder, which checks the pinned vendor hashes,
the schema (`portal-varlib.yaml`) and the catalog references. Update this copy
when the contract changes upstream.
