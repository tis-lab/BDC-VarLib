from linkml_runtime import SchemaView


def test_schema_loads():
    schema = SchemaView("src/bdc_varlib/schema/bdc_varlib.yaml")
    assert schema.schema is not None
