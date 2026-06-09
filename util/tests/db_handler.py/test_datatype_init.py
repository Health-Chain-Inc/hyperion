from unittest.mock import patch

import pytest

from pyfiles.db_handler.datatype_init import DataTypeInit


@pytest.fixture
def sample_fhir_schema():
    return {
        "id": "http://hl7.org/fhir/4.0.1",
        "discriminator": {
            "mapping": {
                "Patient": "#/definitions/Patient",
                "Observation": "#/definitions/Observation",
            }
        },
        "definitions": {
            "Timing_Repeat": {
                "description": "Specifies an event that may occur multiple times. Timing schedules are used to record when things are planned, expected or requested to occur. The most common usage is in dosage instructions for medications. They are also used when planning care of various kinds, and may be used for reporting the schedule to which past regular activities were carried out.",
                "properties": {
                    "id": {
                        "description": "Unique id for the element within a resource (for internal references). This may be any string value that does not contain spaces.",
                        "$ref": "#/definitions/string",
                    },
                    "extension": {
                        "description": "May be used to represent additional information that is not part of the basic definition of the element. To make the use of extensions safe and manageable, there is a strict set of governance  applied to the definition and use of extensions. Though any implementer can define an extension, there is a set of requirements that SHALL be met as part of the definition of the extension.",
                        "items": {"$ref": "#/definitions/Extension"},
                        "type": "array",
                    },
                    "modifierExtension": {
                        "description": "May be used to represent additional information that is not part of the basic definition of the element and that modifies the understanding of the element in which it is contained and/or the understanding of the containing element\u0027s descendants. Usually modifier elements provide negation or qualification. To make the use of extensions safe and manageable, there is a strict set of governance applied to the definition and use of extensions. Though any implementer can define an extension, there is a set of requirements that SHALL be met as part of the definition of the extension. Applications processing a resource are required to check for modifier extensions.\n\nModifier extensions SHALL NOT change the meaning of any elements on Resource or DomainResource (including cannot change the meaning of modifierExtension itself).",
                        "items": {"$ref": "#/definitions/Extension"},
                        "type": "array",
                    },
                },
            },
            "Patient": {
                "properties": {
                    "id": {"type": "string"},
                    "name": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/HumanName"},
                    },
                }
            },
            "Observation": {"properties": {"valueString": {"type": "string"}}},
            "HumanName": {
                "properties": {
                    "family": {"type": "string"},
                    "given": {"type": "array", "items": {"type": "string"}},
                }
            },
            "CodeableConcept": {
                "properties": {
                    "coding": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/Coding"},
                    },
                    "text": {"type": "string"},
                }
            },
            "Coding": {
                "properties": {"system": {"type": "uri"}, "code": {"type": "code"}}
            },
            "ResourceList": {},
            "ElementDefinition": {},
            "Element": {},
            "SubstanceAmount": {},
            "string": {},
            "boolean": {},
        },
    }


def test_datatypeinit_constructor():
    dti = DataTypeInit("schema.json")
    assert dti.file_name == "schema.json"
    assert dti.fhir_schema is None
    assert dti.fhir_data_types == []
    assert dti.primitive_data_types == []
    assert dti.resource_types == []


@patch("pyfiles.db_handler.datatype_init.Handlers.json_reader")
def test_init_data_types(mock_reader, sample_fhir_schema):
    mock_reader.return_value = sample_fhir_schema

    dti = DataTypeInit("schema.json")
    dti.init_data_types()

    assert "Patient" in dti.resource_types
    assert "Observation" in dti.resource_types

    assert "HumanName" in dti.fhir_data_types
    assert "CodeableConcept" in dti.fhir_data_types
    assert "Timing_Repeat" in dti.fhir_data_types

    assert "string" in dti.primitive_data_types
    assert "boolean" in dti.primitive_data_types
    assert "enum" in dti.primitive_data_types
    assert "number" in dti.primitive_data_types

    assert "ResourceList" not in dti.fhir_data_types
    assert "ElementDefinition" not in dti.fhir_data_types
    assert "Element" not in dti.fhir_data_types
    assert "SubstanceAmount" not in dti.fhir_data_types


@patch("pyfiles.db_handler.datatype_init.Handlers.json_reader")
def test_get_fhir_datatype_attributes(mock_reader, sample_fhir_schema):
    mock_reader.return_value = sample_fhir_schema

    dti = DataTypeInit("schema.json")
    schema = dti.get_fhir_datatype_attributes()

    assert "CodeableConcept" in schema
    cc_props = schema["CodeableConcept"]
    assert any("coding_system" in p for p in cc_props)
    assert any("coding_code" in p for p in cc_props)

    assert "HumanName" in schema
    hn_props = schema["HumanName"]
    assert any("family" in p for p in hn_props)
    assert any("given" in p for p in hn_props)

    assert "Extension" not in schema


def test_get_prop_type_cardinality_ref():
    desc = {"$ref": "#/definitions/HumanName"}
    dtype, is_array, db_type = DataTypeInit.get_prop_type_cardinality(
        ["HumanName"], desc, True
    )
    assert dtype == "HumanName"
    assert is_array is False
    assert db_type == "JSON"


def test_get_prop_type_cardinality_array_ref():
    desc = {"type": "array", "items": {"$ref": "#/definitions/Coding"}}
    dtype, is_array, db_type = DataTypeInit.get_prop_type_cardinality(
        ["Coding"], desc, True
    )
    assert dtype == "Coding"
    assert is_array is True
    assert db_type == "JSON"


def test_get_prop_type_cardinality_enum():
    desc = {"enum": ["a", "b"]}
    dtype, is_array, db_type = DataTypeInit.get_prop_type_cardinality([], desc, True)
    assert dtype == "enum"
    assert is_array is False
    assert db_type == "STRING"


def test_get_prop_type_cardinality_primitive():
    desc = {"type": "string"}
    dtype, is_array, db_type = DataTypeInit.get_prop_type_cardinality([], desc, True)
    assert dtype == "string"
    assert is_array is False
    assert db_type == "STRING"


@pytest.mark.parametrize(
    "data_type,expected",
    [
        ("string", "STRING"),
        ("boolean", "BOOLEAN"),
        ("integer", "INTEGER"),
        ("decimal", "DECIMAL(20,10)"),
        ("dateTime", "DATETIME"),
        ("Extension", "JSON"),
        ("unknownType", "JSON"),
    ],
)
def test_get_db_type_mapping(data_type, expected):
    result = DataTypeInit.get_db_type_mapping(data_type, ["HumanName"], True)
    assert result == expected


def test_get_db_type_mapping_non_init_fhir_type():
    result = DataTypeInit.get_db_type_mapping("HumanName", ["HumanName"], False)
    assert result == "VARCHAR"
