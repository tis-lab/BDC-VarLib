# portal-varlib contract (pinned copy)

Copied from
[tis-lab/study-palette PR #72](https://github.com/tis-lab/study-palette/pull/72),
branch `feature/104-portal-varlib-contract`, commit
[`b3c96b0`](https://github.com/tis-lab/study-palette/commit/b3c96b074f000ff4c96aed3fcf70f67da5692747)
("Address VarLib contract review and reuse shared Term model").

| File here | Upstream path | Change |
|---|---|---|
| `portal-varlib.yaml` | `schema/proposals/portal-varlib/portal-varlib.yaml` | import `../../terms` changed to `terms` |
| `validate_catalog.py` | `schema/proposals/portal-varlib/validate_catalog.py` | none |
| `README.md` | `schema/proposals/portal-varlib/README.md` | none |
| `vendor/` | `schema/proposals/portal-varlib/vendor/` | none |
| `terms.yaml` | `schema/terms.yaml` | none |

Only the files the validator needs are copied. Upstream examples,
`terms-response.yaml` and tests are not.

`scripts/build_varlib_catalog.py` validates every catalog it writes with
`validate_catalog.py` from this folder (LinkML validation of
`portal-varlib.yaml` plus the catalog cross-references), and
`tests/test_data.py` runs the same check. Refresh this copy when the contract
changes upstream; once PR #72 is merged, re-pin to the merge commit on
`main`.
