import os
from unittest.mock import MagicMock

import pytest

from pyfiles.db_handler.resource_schema_generator import \
    ResourceSchemaGenerator


@pytest.fixture
def mock_fhir_schema():
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
            "Patient_Contact": {
                "properties": {
                    "id": {"type": "string"},
                    "extension": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/Extension"},
                    },
                    "modifierExtension": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/Extension"},
                    },
                    "relationship": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/CodeableConcept"},
                    },
                    "name": {"$ref": "#/definitions/HumanName"},
                }
            },
            "ResourceList": {},
            "ElementDefinition": {},
            "Element": {},
            "SubstanceAmount": {},
            "string": {},
            "boolean": {},
        },
    }


@pytest.fixture
def mock_dependencies(monkeypatch, mock_fhir_schema):

    mock_data_type_init = MagicMock()
    mock_data_type_instance = MagicMock()
    mock_data_type_instance.fhir_data_types = {}
    mock_data_type_instance.get_fhir_datatype_attributes.return_value = {
        "HumanName": [
            {"family": {"is_array": False, "database_type": "STRING"}},
            {"given": {"is_array": True, "database_type": "STRING"}},
        ]
    }
    mock_data_type_init.return_value = mock_data_type_instance

    monkeypatch.setattr(
        "pyfiles.db_handler.datatype_init.DataTypeInit",
        mock_data_type_init,
    )

    monkeypatch.setattr(
        "pyfiles.db_handler.datatype_init.DataTypeInit.get_prop_type_cardinality",
        MagicMock(return_value=("string", False, "STRING")),
    )

    monkeypatch.setattr(
        "pyfiles.dependencies.handlers.Handlers.json_reader",
        MagicMock(return_value=mock_fhir_schema),
    )

    mock_index_creator = MagicMock()
    mock_index_creator_instance = MagicMock()
    mock_index_creator_instance.resource_index_creator.return_value = [
        {"name": "string"},
        {"active": "boolean"},
    ]
    mock_index_creator.return_value = mock_index_creator_instance

    monkeypatch.setattr(
        "pyfiles.db_handler.index_creator.IndexCreator",
        mock_index_creator,
    )


def test_init_success(mock_dependencies):
    gen = ResourceSchemaGenerator(
        file_name="schema.json",
        resources=["Patient"],
        schema_destination="out.sql",
        common_table_schema_path="common.sql",
        replication_number="3",
    )

    assert gen.file_name == "schema.json"
    assert gen.resources == ["Patient"]
    assert gen.fhir_schema is not None
    assert "Patient" in gen.back_bone_dictionary

def test_get_back_bone_elements(mock_dependencies):
    gen = ResourceSchemaGenerator(
        "schema.json", ["Patient"], "out.sql", "common.sql", "1"
    )

    patient_backbone_schema = gen.back_bone_dictionary.get("Patient")
    assert "Patient_Contact" in patient_backbone_schema


def test_backbone_attribute_generator(mock_dependencies):
    gen = ResourceSchemaGenerator(
        "schema.json", ["Patient"], "out.sql", "common.sql", "1"
    )

    patient_backbone_schema = gen.backbone_attribute_generator(["Patient_Contact"])
    assert "Patient_Contact" in patient_backbone_schema
    assert isinstance(patient_backbone_schema["Patient_Contact"], list)

# ============================================================
# RESOURCE ATTRIBUTE GENERATION
# ============================================================

def test_get_resource_attributes_generator_ignores_internal_fields(
    mock_dependencies,
):
    gen = ResourceSchemaGenerator(
        "schema.json", ["Patient"], "out.sql", "common.sql", "1"
    )

    props = {
        "resourceType": {},
        "_internal": {},
        "name": {"type": "string"},
    }

    result = gen.get_resource_attributes_generator("Patient", props)

    assert len(result) == 1
    assert "name" in result[0]


# ============================================================
# PRIMITIVE DATATYPE SCHEMA GENERATOR
# ============================================================

def test_primitive_scalar():
    result = ResourceSchemaGenerator.primitive_datatype_schema_generator(
        "age", False, "INTEGER"
    )
    assert result == {"age": "INTEGER"}


def test_primitive_array():
    result = ResourceSchemaGenerator.primitive_datatype_schema_generator(
        "tags", True, "STRING"
    )
    assert result == {"tags": "ARRAY<STRING>"}


def test_primitive_extension_forces_json_array():
    result = ResourceSchemaGenerator.primitive_datatype_schema_generator(
        "extension", False, "STRING"
    )
    assert result == {"extension": "ARRAY<JSON>"}


# ============================================================
# FHIR DATATYPE SCHEMA GENERATOR
# ============================================================

def test_fhir_datatype_schema_generator_skips_reference():
    deletion_dict = {
        "identifier": [],
        "codeableconcept": [],
        "reference": [],
    }

    result = ResourceSchemaGenerator.fhir_datatype_schema_generator(
        attribute_name="subject",
        attribute_type="Reference",
        attribute_cardinality=False,
        fhir_attributes_dict={},
        parent_cardinality=False,
        deletion_attribute_dict=deletion_dict,
    )

    assert result is None
    assert "subject" in deletion_dict["reference"]


# ============================================================
# SCHEMA CREATOR
# ============================================================

def test_schema_creator_with_primitive_only():
    resource_attributes = [
        {
            "name": {
                "attribute_type": "string",
                "is_array": False,
                "database_type": "STRING",
            }
        }
    ]

    schema, deletion_dict = ResourceSchemaGenerator.schema_creator(
        resource_attributes,
        back_bone_attributes_dict={},
        fhir_attributes_dict={},
    )

    assert schema == [{"name": "STRING"}]
    assert deletion_dict["reference"] == []


# ============================================================
# INDEX CREATOR
# ============================================================

def test_index_creator_adds_bitmap_and_bloom():
    column_defs = ["    `name` STRING"]
    index_dict = {
        "patient": [
            {"name": "string"},
            {"active": "boolean"},
        ]
    }

    bloom, bitmap = ResourceSchemaGenerator.index_creator(
        index_dict, column_defs, "patient"
    )

    assert "name" in bloom
    assert "active" in bitmap
    assert any("BITMAP" in col for col in column_defs)

def test_generate_schema_to_file(tmp_path):
    out_file = tmp_path / "schema.sql"
    common_file = tmp_path / "common.sql"
    common_file.write_text("CREATE DATABASE test;")

    ResourceSchemaGenerator.generate_schema_to_file(
        schema_dict={"Patient": [{"name": "STRING"}]},
        output_file=str(out_file),
        common_table_schema_path=str(common_file),
        replication_num="1",
        index_column_dict={},
    )

    assert out_file.exists()
    content = out_file.read_text()
    assert "CREATE TABLE IF NOT EXISTS `patient`" in content
    assert "`name` STRING" in content


# ============================================================
# CONFIG FILE CREATOR
# ============================================================

def test_config_file_creator_creates_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    os.makedirs("configurations", exist_ok=True)

    ResourceSchemaGenerator.config_file_creator(
        ["age ARRAY<INTEGER>"], "patient"
    )

    config_file = tmp_path / "configurations/patient.ini"
    assert config_file.exists()
    assert "age:ARRAY<INTEGER>" in config_file.read_text()


# ============================================================
# DELETION ATTRIBUTE FILE CREATION
# ============================================================

def test_create_deletion_attributes():
    from unittest.mock import mock_open, patch

    data = {"Patient": {"reference": ["subject"]}}

    m = mock_open()
    with patch("builtins.open", m):
        with patch("json.dump") as mock_json_dump:
            ResourceSchemaGenerator.create_deletion_attributes(data)

    mock_json_dump.assert_called_once()
    dumped_data = mock_json_dump.call_args[0][0]
    assert dumped_data == data

def test_schema_generator_end_to_end(
    mock_dependencies, tmp_path
):
    from unittest.mock import patch

    common_file = tmp_path / "common.sql"
    common_file.write_text("CREATE DATABASE test;")

    gen = ResourceSchemaGenerator(
        file_name="schema.json",
        resources=["Patient"],
        schema_destination=str(tmp_path / "out.sql"),
        common_table_schema_path=str(common_file),
        replication_number="1",
    )

    with patch.object(ResourceSchemaGenerator, "create_deletion_attributes"), \
         patch.object(ResourceSchemaGenerator, "config_file_creator"):
        gen.schema_generator()

    assert (tmp_path / "out.sql").exists()
