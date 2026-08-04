"""Data model package for BDC Variable Library."""

from pathlib import Path
from .bdc_varlib import *  # noqa: F403

THIS_PATH = Path(__file__).parent

SCHEMA_DIRECTORY = THIS_PATH.parent / "schema"
MAIN_SCHEMA_PATH = SCHEMA_DIRECTORY / "bdc_varlib.yaml"
