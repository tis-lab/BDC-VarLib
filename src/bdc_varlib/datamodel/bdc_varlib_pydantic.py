from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'bdcvl',
     'description': 'A LinkML-based variable library for BioData Catalyst '
                    'datasets.\n',
     'id': 'https://w3id.org/bdc/varlib',
     'imports': ['linkml:types'],
     'name': 'bdc_varlib',
     'prefixes': {'bdcvl': {'prefix_prefix': 'bdcvl',
                            'prefix_reference': 'https://w3id.org/bdc/varlib/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'src/bdc_varlib/schema/bdc_varlib.yaml',
     'title': 'BDC Variable Library'} )


class Variable(ConfiguredBaseModel):
    """
    A data variable definition.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/bdc/varlib'})

    name: Optional[str] = Field(default=None, description="""Name of the variable.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Variable']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Variable.model_rebuild()
