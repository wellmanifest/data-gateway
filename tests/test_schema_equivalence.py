"""The compiled validators must accept and reject exactly what Draft 2020-12 accepts and rejects for every catalog schema."""
import copy
import itertools
import json
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from data_gateway.kernel import CompiledSchema
from data_gateway.upstream import data_plane

UUID = '3f1a7c9e-2b4d-4e6f-8a1b-0c2d3e4f5a6b'


def sample(schema):
    """A minimal instance that satisfies the schema's required structure, used as a seed for mutations."""
    if 'const' in schema: return schema['const']
    if 'enum' in schema: return schema['enum'][0]
    kind = schema.get('type')
    if isinstance(kind, list): kind = next(k for k in kind if k != 'null')
    if kind == 'object':
        props = schema.get('properties', {})
        return {k: sample(props[k]) for k in schema.get('required', []) if k in props}
    if kind == 'array': return []
    if kind == 'integer': return max(0, schema.get('minimum', 0))
    if kind == 'boolean': return False
    if kind == 'string':
        if schema.get('format') == 'uuid': return UUID
        return 'a' * max(1, schema.get('minLength', 1))
    return None


def mutations(value):
    """Valid-looking and invalid variants: drop each key, retype each value, add an unknown key, bad uuid casing."""
    yield value
    if isinstance(value, dict):
        for key in value:
            yield {k: v for k, v in value.items() if k != key}
            for replacement in (None, 1, 'x', [], {}, True, UUID.upper(), UUID.replace('-', '')):
                changed = copy.deepcopy(value); changed[key] = replacement; yield changed
            for nested in itertools.islice(mutations(value[key]), 40):
                changed = copy.deepcopy(value); changed[key] = nested; yield changed
        yield {**value, 'unexpected': 1}


class SchemaEquivalence(unittest.TestCase):
    def test_compiled_validators_agree_with_draft_2020_12(self):
        _, line, _ = data_plane()
        root = data_plane()[0]
        _, operations = line.load_contracts(root)
        checked = 0
        for name, op in operations.items():
            for side in ('inputSchema', 'outputSchema'):
                schema = op[side]
                reference = Draft202012Validator(schema, format_checker=FormatChecker())
                compiled = CompiledSchema(schema)
                for instance in mutations(sample(schema)):
                    expected = reference.is_valid(instance)
                    self.assertEqual(compiled.valid(instance), expected, f'{name}.{side}: {json.dumps(instance)[:300]}')
                    checked += 1
        self.assertGreater(checked, 1000)


if __name__ == '__main__':
    unittest.main()
