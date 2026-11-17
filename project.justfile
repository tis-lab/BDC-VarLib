## Add your own just recipes here. This is imported by the main justfile.

# Overriding recipes from the root justfile by adding a recipe with the same
# name in this file is not possible until a known issue in just is fixed,
# https://github.com/casey/just/issues/2540

# ============== BDC Variable Library: portal catalogs ==============

# Location of a local clone of RTIInternational/NHLBI-BDC-DMC-HV (optional)
hv_repo := env_var_or_default("BDC_HV_REPO", "")

# Build the portal catalogs (src/bdc_varlib/data/) with ontology names and dbGaP details
[group('library data')]
data:
  uv run python scripts/build_varlib_catalog.py --ontology --dbgap {{ if hv_repo != "" { "--repo-dir " + hv_repo } else { "" } }}

# Test the portal catalogs only
[group('library data')]
test-data:
  uv run python -m pytest tests/test_data.py
