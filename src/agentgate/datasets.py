import json

import jsonschema


def validate_definition(definition):
    schema = definition.record_schema
    if schema is None:
        return
    jsonschema.Draft202012Validator.check_schema(schema)
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("Writable datasets require an object schema rejecting additional properties")
    if '"$ref"' in json.dumps(schema):
        raise ValueError("Schema references are unsupported")
