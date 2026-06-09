# Standard library imports
import logging
import json
# Local imports
from pyfiles.dependencies.handlers import Handlers


class DataTypeInit:
    """
    Schema generator class
    """

    def __init__(self, file_name: str):
        """
        file_name -> schema file path
        """
        logging.info("Initializing schema generator object")
        self.file_name = file_name
        self.fhir_schema = None
        self.fhir_data_types = []
        self.primitive_data_types = []
        self.resource_types = []

    def init_data_types(
        self,
    ):
        """
        function to get the data types from json
        """
        self.fhir_schema = Handlers.json_reader(self.file_name)
        if self.fhir_schema:
            logging.info(
                "Creating schema for fhir version %s",
                self.fhir_schema.get("id").split("/")[-1],
            )

        resources_from_schema = list(
            self.fhir_schema.get("discriminator", {}).get("mapping").keys()
        )
        data_types_from_schema = list(self.fhir_schema.get("definitions").keys())
        data_types_from_schema = list(
            set(data_types_from_schema) - set(resources_from_schema)
        )
        data_types_from_schema = [
            data_type for data_type in data_types_from_schema if "_" not in data_type
        ]

        [
            (
                self.fhir_data_types.append(data_type)
                if data_type[0].isupper()
                else self.primitive_data_types.append(data_type)
            )
            for data_type in data_types_from_schema
        ]

        self.resource_types = resources_from_schema

        self.primitive_data_types.append("enum")
        self.primitive_data_types.append("number")
        self.primitive_data_types.append("Extension")
        self.fhir_data_types.append("Timing_Repeat")

        self.fhir_data_types.remove("ResourceList")
        self.fhir_data_types.remove("ElementDefinition")
        self.fhir_data_types.remove("Element")
        self.fhir_data_types.remove("SubstanceAmount")
        # self.fhir_data_types.remove("DataRequirement")

    def get_fhir_datatype_attributes(self):
        """
        function to initialize the first level attributes for fhir data types
        """
        self.init_data_types()

        properties_to_ignore = [
            "resourceType",
            "implicitRules",
            "contained",
            "modifierExtension",
            "id",
        ]
        fhir_type_schema = {}
        for _, data_type in enumerate(self.fhir_data_types):
            data_type_definition = self.fhir_schema.get("definitions", {}).get(
                data_type, None
            )
            data_type_properties = data_type_definition.get("properties")
            if data_type == "CodeableConcept":
                temp_prop_dict_list = []
                prop = "coding_system"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "uri"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "STRING"
                temp_prop_dict_list.append(temp_prop_dict)

                prop = "coding_version"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "string"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "STRING"
                temp_prop_dict_list.append(temp_prop_dict)

                prop = "coding_code"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "code"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "STRING"
                temp_prop_dict_list.append(temp_prop_dict)

                prop = "coding_display"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "string"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "STRING"
                temp_prop_dict_list.append(temp_prop_dict)

                prop = "coding_userSelected"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "boolean"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "BOOLEAN"
                temp_prop_dict_list.append(temp_prop_dict)

                prop = "text"
                temp_prop_dict = {}
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = "string"
                temp_prop_dict[prop]["is_array"] = True
                temp_prop_dict[prop]["database_type"] = "STRING"
                temp_prop_dict_list.append(temp_prop_dict)

                fhir_type_schema[data_type] = temp_prop_dict_list
                continue

            if data_type == "Extension":
                continue

            temp_prop_dict_list = []
            for _, (prop, description) in enumerate(data_type_properties.items()):
                temp_prop_dict = {}
                if prop in properties_to_ignore or prop[0] == "_":
                    pass
                else:
                    attr_data_type, cardinality, db_data_type = (
                        DataTypeInit.get_prop_type_cardinality(
                            self.fhir_data_types, description, True
                        )
                    )

                    temp_prop_dict[prop] = {}
                    temp_prop_dict[prop]["attribute_type"] = attr_data_type
                    temp_prop_dict[prop]["is_array"] = cardinality
                    temp_prop_dict[prop]["database_type"] = db_data_type
                    temp_prop_dict_list.append(temp_prop_dict)

            fhir_type_schema[data_type] = temp_prop_dict_list
        return fhir_type_schema

    @staticmethod
    def get_prop_type_cardinality(fhir_types, prop_description: dict, data_type_init):
        """
        function to check the property type
        """
        data_type = None
        keys = prop_description.keys()
        if "$ref" in keys:
            data_type = prop_description["$ref"].split("/")[-1]
        elif "items" in keys:
            items = prop_description["items"]
            if "$ref" in items.keys():
                data_type = items["$ref"].split("/")[-1]
            elif "enum" in items.keys():
                data_type = "enum"
        elif "enum" in keys:
            data_type = "enum"

        if "type" in keys:
            if data_type is None:
                data_type = prop_description["type"]
                return (
                    data_type,
                    False,
                    DataTypeInit.get_db_type_mapping(
                        data_type, fhir_types, data_type_init
                    ),
                )

            if prop_description["type"] == "array":
                return (
                    data_type,
                    True,
                    DataTypeInit.get_db_type_mapping(
                        data_type, fhir_types, data_type_init
                    ),
                )

        return (
            data_type,
            False,
            DataTypeInit.get_db_type_mapping(data_type, fhir_types, data_type_init),
        )

    @staticmethod
    def get_db_type_mapping(data_type, fhir_types, data_type_init):
        """
        return database data type for the fhir data type
        """
        data_type_map = {
            "positiveInt": "INTEGER",
            "unsignedInt": "INTEGER",
            "integer": "INTEGER",
            "number": "INTEGER",
            "boolean": "BOOLEAN",
            "decimal": "DECIMAL(20,10)",
            "dateTime": "DATETIME",
            "date": "DATETIME",
            "time": "DATETIME",
            "uuid": "VARCHAR(100)",
            "id": "VARCHAR(100)",
            "uri": "STRING",
            "url": "STRING",
            "code": "STRING",
            "enum": "STRING",
            "canonical": "STRING",
            "instant": "STRING",
            "base64Binary": "STRING",
            "markdown": "STRING",
            "string": "STRING",
            "oid": "STRING",
            "xhtml": "STRING",
            "Extension": "JSON",
            "extension": "JSON",
            "ElementDefinition": "JSON",
            "":"JSON"
        }
        db_type = data_type_map.get(data_type, None)
        if data_type_init:
            if not db_type and data_type in fhir_types:
                db_type = "JSON"
            elif not db_type and data_type not in fhir_types:
                db_type = "JSON"
        else:
            if not db_type and data_type in fhir_types:
                db_type = "VARCHAR"
        return db_type


if __name__ == "__main__":

    data_init = DataTypeInit(r"db_schema\fhir_schema.json")
    print(json.dumps(data_init.get_fhir_datatype_attributes()))
