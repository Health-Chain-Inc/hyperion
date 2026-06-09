import os
from unittest.mock import patch

import pytest

from pyfiles.db_handler.index_creator import IndexCreator


@pytest.fixture
def directory_path():
    return "/fake/schema/dir"


@pytest.fixture
def resource_list():
    return ["Patient", "Observation"]


@pytest.fixture
def index_creator(directory_path):
    return IndexCreator(directory_path)

PATIENT_SCHEMA = {
    "snapshot": {
        "element": [
            {
                "id": "Patient.active",
                "max": "1",
                "isModifier": True,
                "isSummary": False,
                "type": [{"code": "boolean"}],
            },
            {
                "id": "Patient.gender",
                "max": "1",
                "isModifier": False,
                "isSummary": True,
                "type": [{"code": "code"}],
            },
            {
                "id": "Patient.name",
                "max": "*",  # should be ignored
                "isModifier": True,
                "type": [{"code": "string"}],
            },
            {
                "id": "Patient.deceased[x]",
                "max": "1",
                "isModifier": True,
                "type": [{"code": "boolean"}],
            },
            {
                "id": "Patient.extension",
                "max": "1",
                "isModifier": True,
                "type": [{"code": "Extension"}],  # ignored datatype
            },
        ]
    }
}


OBSERVATION_SCHEMA = {
    "snapshot": {
        "element": [
            {
                "id": "Observation.status",
                "max": "1",
                "isModifier": True,
                "type": [{"code": "code"}],
            },
            {
                "id": "Observation.value[x]",
                "max": "1",
                "isSummary": True,
                "type": [{"code": "string"}],
            },
        ]
    }
}


EMPTY_SCHEMA = {
    "snapshot": {
        "element": []
    }
}


NO_SNAPSHOT_SCHEMA = {}

def test_index_creator_init(directory_path):
    creator = IndexCreator(directory_path)

    assert creator.directory_path == directory_path
    assert "string" in creator.index_column_types
    assert "boolean" in creator.index_column_types
    assert "enum" in creator.index_column_types
    assert "code" in creator.index_column_types

@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_success(mock_reader, index_creator):
    mock_reader.return_value = PATIENT_SCHEMA

    result = index_creator.resource_index_creator("Patient")

    assert {"active": "boolean"} in result
    assert {"gender": "code"} in result
    assert {"deceasedboolean": "boolean"} in result

    assert not any("name" in r for r in result)

    assert not any("extension" in r for r in result)


@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_polymorphic_x_replacement(mock_reader, index_creator):
    mock_reader.return_value = OBSERVATION_SCHEMA

    result = index_creator.resource_index_creator("Observation")

    assert {"value_string": "string"} not in result
    assert {"valuestring": "string"} in result


@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_no_snapshot(mock_reader, index_creator):
    mock_reader.return_value = NO_SNAPSHOT_SCHEMA

    result = index_creator.resource_index_creator("Patient")

    assert result == []


@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_empty_elements(mock_reader, index_creator):
    mock_reader.return_value = EMPTY_SCHEMA

    result = index_creator.resource_index_creator("Patient")

    assert result == []


@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_ignores_non_modifier_and_non_summary(
    mock_reader, index_creator
):
    schema = {
        "snapshot": {
            "element": [
                {
                    "id": "Patient.test",
                    "max": "1",
                    "isModifier": False,
                    "isSummary": False,
                    "type": [{"code": "string"}],
                }
            ]
        }
    }

    mock_reader.return_value = schema

    result = index_creator.resource_index_creator("Patient")

    assert result == []


@patch("pyfiles.db_handler.index_creator.Handlers.json_reader")
def test_resource_index_creator_ignores_nested_fields(mock_reader, index_creator):
    schema = {
        "snapshot": {
            "element": [
                {
                    "id": "Patient.name.family",  # nested -> ignored
                    "max": "1",
                    "isModifier": True,
                    "type": [{"code": "string"}],
                }
            ]
        }
    }

    mock_reader.return_value = schema

    result = index_creator.resource_index_creator("Patient")

    assert result == []

# test case actual reads and creates indexes from actual schema files for a view selected resources
def test_index_creator_with_actual_schema_files():

    # Resolve schema path relative to this test file so it works regardless
    # of where pytest is invoked from (CI runs from repo root, devs may run
    # from util/).
    schema_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "schema", "index_creation_schema"
    )
    creator = IndexCreator(schema_dir)

    # Resource-schema JSON files on disk are lowercase (e.g. patient.json),
    # matching the production caller in resource_schema_generator.py which
    # invokes resource_index_creator(resource.lower()). Linux filesystems
    # are case-sensitive, so the lookup name must match the file casing.
    index_patient = creator.resource_index_creator("patient")
    index_condition = creator.resource_index_creator("condition")
    index_immunization = creator.resource_index_creator("immunization")
    index_medicationStatement = creator.resource_index_creator("medicationstatement")
    index_medicationRequest = creator.resource_index_creator("medicationrequest")
    index_observation = creator.resource_index_creator("observation")

    assert index_patient == [{'active': 'boolean'}, {'gender': 'code'}, {'deceasedboolean': 'boolean'}]
    assert index_condition == [{'onsetstring': 'string'}]
    assert index_immunization == [{'status': 'code'}, {'occurrencestring': 'string'}, {'primarysource': 'boolean'}, {'issubpotent': 'boolean'}]
    assert index_medicationStatement == [{'status': 'code'}]
    assert index_medicationRequest == [{'status': 'code'}, {'intent': 'code'}, {'priority': 'code'}, {'donotperform': 'boolean'}, {'reportedboolean': 'boolean'}]
    assert index_observation == [{'status': 'code'}, {'valuestring': 'string'}, {'valueboolean': 'boolean'}]
