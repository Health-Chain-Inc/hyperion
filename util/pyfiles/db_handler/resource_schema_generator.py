# Standard library imports
import json
import logging

# Local imports
from pyfiles.db_handler.datatype_init import DataTypeInit
from pyfiles.db_handler.index_creator import IndexCreator
from pyfiles.dependencies.handlers import Handlers


# pylint: disable=too-many-arguments
class ResourceSchemaGenerator:
    """
    Schema generator class
    """

    def __init__(
        self,
        file_name: str,
        resources: list,
        schema_destination: str,
        common_table_schema_path: str,
        replication_number: str,
    ):
        """
        file_name -> schema file path
        """
        logging.info("Initializing schema generator object")
        self.file_name = file_name
        self.fhir_schema = None
        data_init = DataTypeInit(file_name)
        self.fhir_data_types = data_init.fhir_data_types
        self.fhir_attributes = data_init.get_fhir_datatype_attributes()
        self.back_bone_dictionary = {}
        self.resources = resources
        self.fhir_schema = Handlers.json_reader(self.file_name)
        self.get_back_bone_elements()
        self.schema_destination = schema_destination
        self.replication_number = replication_number
        self.common_table_schema_path = common_table_schema_path

    def schema_generator(self):
        """
        function to create schema for required tables
        """
        schema_dictionary = {}
        deletion_attribute_dictionary = {}
        index_column_dict = {}
        # self.resources = ["AuditEvent"]
        for resource in self.resources:
            logging.info("Creating schema for resource - %s", resource)
            resource_definition = self.fhir_schema.get("definitions").get(resource)
            resource_properties = resource_definition.get("properties")
            back_bone_attributes = self.backbone_attribute_generator(
                self.back_bone_dictionary[resource]
            )
            resource_attribute_list = self.get_resource_attributes_generator(
                resource, resource_properties
            )
            schema_dictionary[resource], deletion_attribute_dictionary[resource] = (
                ResourceSchemaGenerator.schema_creator(
                    resource_attribute_list, back_bone_attributes, self.fhir_attributes
                )
            )
            index_creator_obj = IndexCreator(
                r"schema/index_creation_schema")
            index_column_dict[resource.lower()] = (
                index_creator_obj.resource_index_creator(resource.lower())
            )

        ResourceSchemaGenerator.generate_schema_to_file(
            schema_dictionary,
            self.schema_destination,
            self.common_table_schema_path,
            self.replication_number,
            index_column_dict,
        )

        ResourceSchemaGenerator.create_deletion_attributes(
            deletion_attribute_dictionary
        )

    @staticmethod
    def schema_creator(
        resource_attributes, back_bone_attributes_dict, fhir_attributes_dict
    ):
        deletion_attribute_dict = {}
        deletion_attribute_dict["identifier"] = []
        deletion_attribute_dict["codeableconcept"] = []
        deletion_attribute_dict["reference"] = []
        flattened_schema = []
        for attribute in resource_attributes:
            attribute_name = list(attribute.keys())[0]
            attribute = attribute[attribute_name]
            attribute_cardinality = attribute["is_array"]
            attribute_type = attribute["attribute_type"]
            if attribute_type in fhir_attributes_dict:
                fhir_attributes_schema = (
                    ResourceSchemaGenerator.fhir_datatype_schema_generator(
                        attribute_name,
                        attribute_type,
                        attribute_cardinality,
                        fhir_attributes_dict,
                        False,
                        deletion_attribute_dict,
                    )
                )
                if fhir_attributes_schema:
                    flattened_schema += fhir_attributes_schema
            elif attribute_type in back_bone_attributes_dict:
                if attribute_cardinality or attribute_type in ["Reference", "CodeableConcept", "Identifier", "Coding"]:
                    flattened_schema.append({attribute_name: "ARRAY<JSON>"})
                else:
                    back_bone_attributes = back_bone_attributes_dict[attribute_type]
                    for back_bone_attribute in back_bone_attributes:
                        back_bone_attribute_name = list(back_bone_attribute.keys())[0]
                        back_bone_attribute = back_bone_attribute[
                            back_bone_attribute_name
                        ]
                        back_bone_attribute_type = back_bone_attribute["attribute_type"]
                        back_bone_attribute_cardinality = back_bone_attribute[
                            "is_array"
                        ]
                        back_bone_attribute_name = (
                            f"{attribute_name}_{back_bone_attribute_name}"
                        )
                        if back_bone_attribute_type in fhir_attributes_dict:
                            flattened_schema.append({back_bone_attribute_name: "JSON"})
                        elif back_bone_attribute_type in back_bone_attributes_dict:
                            if (
                                back_bone_attribute_cardinality
                                and attribute_cardinality
                            ):
                                flattened_schema.append(
                                    {back_bone_attribute_name: "ARRAY<ARRAY<JSON>>"}
                                )
                            elif (
                                not back_bone_attribute_cardinality
                                and not attribute_cardinality
                            ):
                                flattened_schema.append(
                                    {back_bone_attribute_name: "JSON"}
                                )
                            else:
                                flattened_schema.append(
                                    {back_bone_attribute_name: "ARRAY<JSON>"}
                                )
                        else:
                            flattened_schema.append(
                                ResourceSchemaGenerator.primitive_datatype_schema_generator(
                                    back_bone_attribute_name,
                                    back_bone_attribute_cardinality,
                                    back_bone_attribute["database_type"],
                                    attribute_cardinality,
                                )
                            )
            else:
                flattened_schema.append(
                    ResourceSchemaGenerator.primitive_datatype_schema_generator(
                        attribute_name,
                        attribute_cardinality,
                        attribute["database_type"],
                    )
                )
        return flattened_schema, deletion_attribute_dict

    def get_back_bone_elements(self):
        """
        Function to retrieve back bone elements for each resource and
        add it to back_bone_dictionary attribute
        """

        for resource in self.resources:
            fhir_data_elements = list(self.fhir_schema.get("definitions").keys())
            resource_back_bone_elements = [
                fhir_data_element
                for fhir_data_element in fhir_data_elements
                if f"{resource}_" in fhir_data_element
            ]
            self.back_bone_dictionary[resource] = resource_back_bone_elements

    def get_resource_attributes_generator(
        self, resource_name: str, resource_properties: dict
    ):
        """
        function to initialize the first level attributes for fhir data types
        """
        properties_to_ignore = [
            "resourceType",
            "implicitRules",
            "contained",
            "modifierExtension",
            "id",
            "Narrative",
        ]

        logging.info("Creating resource attributes for %s", resource_name)
        prop_dict_list = []
        for _, (prop, description) in enumerate(resource_properties.items()):
            temp_prop_dict = {}
            if prop in properties_to_ignore or prop[0] == "_":
                pass
            else:
                attr_data_type, cardinality, db_data_type = (
                    DataTypeInit.get_prop_type_cardinality(
                        self.fhir_data_types, description, False
                    )
                )
                temp_prop_dict[prop] = {}
                temp_prop_dict[prop]["attribute_type"] = attr_data_type
                temp_prop_dict[prop]["is_array"] = cardinality
                temp_prop_dict[prop]["database_type"] = db_data_type
                prop_dict_list.append(temp_prop_dict)
        return prop_dict_list

    def backbone_attribute_generator(self, backbone_elements: list):
        """
        Function to create back bone element attributes
        """
        properties_to_ignore = [
            "resourceType",
            "implicitRules",
            "contained",
            "extension",
            "modifierExtension",
            "id",
        ]
        back_bone_schema = {}
        for _, data_type in enumerate(backbone_elements):
            data_type_definition = self.fhir_schema.get("definitions", {}).get(
                data_type, None
            )
            data_type_properties = data_type_definition.get("properties")
            temp_prop_dict_list = []
            for _, (prop, description) in enumerate(data_type_properties.items()):
                temp_prop_dict = {}
                if prop in properties_to_ignore or prop[0] == "_":
                    pass
                else:
                    attr_data_type, cardinality, db_data_type = (
                        DataTypeInit.get_prop_type_cardinality(
                            self.fhir_data_types, description, False
                        )
                    )
                    temp_prop_dict[prop] = {}
                    temp_prop_dict[prop]["attribute_type"] = attr_data_type
                    temp_prop_dict[prop]["is_array"] = cardinality
                    temp_prop_dict[prop]["database_type"] = db_data_type
                    temp_prop_dict_list.append(temp_prop_dict)
            back_bone_schema[data_type] = temp_prop_dict_list
        return back_bone_schema

    @staticmethod
    def fhir_datatype_schema_generator(
        attribute_name,
        attribute_type,
        attribute_cardinality,
        fhir_attributes_dict,
        parent_cardinality,
        deletion_attribute_dict,
    ):
        """
        Function handles the schema creation part for fhir attribute types
        attribute_XYZ -> fhir_data_type related variables
        parent_cardinality -> cardinality of the back bone element
        """
        fhir_schema = []
        # we dont want to create codeable concept and reference data type columns,
        # as we are creating individual tables.
        if attribute_type in ["Reference", "CodeableConcept", "Identifier", "Coding"]:
            if attribute_type == "Coding":
                return None
            if not parent_cardinality:
                deletion_attribute_dict[attribute_type.lower()].append(
                    attribute_name.lower()
                )
            return None
        fhir_attributes = fhir_attributes_dict[attribute_type]
        for fhir_attribute in fhir_attributes:
            fhir_attribute_name = list(fhir_attribute.keys())[0]
            fhir_attribute = fhir_attribute[fhir_attribute_name]
            fhir_attribute_cardinality = fhir_attribute["is_array"]
            if attribute_cardinality and fhir_attribute_cardinality:
                fhir_attribute_data_type = (
                    f"ARRAY<ARRAY<{fhir_attribute['database_type']}>>"
                )
            elif attribute_cardinality or fhir_attribute_cardinality:
                fhir_attribute_data_type = f"ARRAY<{fhir_attribute['database_type']}>"
            else:
                fhir_attribute_data_type = f"{fhir_attribute['database_type']}"
            fhir_attribute_data_type = (
                f"ARRAY<{fhir_attribute_data_type}>"
                if parent_cardinality
                else fhir_attribute_data_type
            )
            fhir_schema.append(
                {f"{attribute_name}_{fhir_attribute_name}": fhir_attribute_data_type}
            )
        return fhir_schema

    @staticmethod
    def primitive_datatype_schema_generator(
        attribute_name,
        attribute_cardinality,
        attribute_database_type,
        parent_cardinality=False,
    ):
        """
        Function handles the schema creation part for fhir attribute types
        attribute_XYZ -> primitive_data_type related variables
        parent_cardinality -> cardinality of the back bone element
        """
        if "Extension" in attribute_name or "extension" in attribute_name:
            return {attribute_name: "ARRAY<JSON>"}
        attribute_data_type = (
            f"ARRAY<{attribute_database_type}>"
            if attribute_cardinality
            else f"{attribute_database_type}"
        )
        attribute_data_type = (
            f"ARRAY<{attribute_data_type}>"
            if parent_cardinality
            else attribute_data_type
        )
        return {attribute_name: attribute_data_type}

    @staticmethod
    def initialize_schema_for_excel(
        table_name,
        column_definitions,
        bloom_filter_columns,
        bitmap_index_columns,
        column_names,
        column_datatypes,
        table_names,
        index_info,
    ):
        """
        Function to create excel file with table names and column definitions
        """
        table_names.append(table_name)
        for i,column in enumerate(column_definitions):
            if i != 0:
                table_names.append("")
            column_info = column.strip().split("`")
            column_names.append(column_info[1].strip())
            column_datatypes.append(column_info[2].strip())
            if column_info[1].strip() in bloom_filter_columns:
                index_info.append("bloom filter")
            elif column_info[1].strip() in bitmap_index_columns:
                index_info.append("bitmap index")
            elif column_info[1].strip() == "id":
                index_info.append("primary key")
            else:
                index_info.append("")
            if column_info[1].strip() == "identifier_max_array_size":
                break
        column_names.append("")
        column_datatypes.append("")
        table_names.append("")
        index_info.append("")
        return column_names, column_datatypes, table_names, index_info

    @staticmethod
    def generate_schema_to_file(
        schema_dict,
        output_file,
        common_table_schema_path,
        replication_num,
        index_column_dict,
    ):
        """
        function takes the attribute name, attribute data type to create
        final schema and writes schema to a file
        """
        column_names = []
        column_data_types = []
        table_names = []
        index_info = []

        with open(common_table_schema_path, "r", encoding="utf-8") as file:
            schema_sql = file.read()
            schema_sql = schema_sql.replace("env_replication_num", replication_num)
            schema_sql += "\n\n"

        for table_name, columns in schema_dict.items():
            table_name = table_name.lower()
            create_table_stmt = f"CREATE TABLE IF NOT EXISTS `{table_name}` (\n"
            column_definitions = []
            column_definitions.append("    `id` VARCHAR(100)")
            for column in columns:
                for column_name, data_type in column.items():
                    if (
                        data_type == "ARRAY<DATETIME>"
                        or data_type == "ARRAY<ARRAY<DATETIME>>"
                    ):
                        data_type = data_type.replace("DATETIME", "STRING")
                    column_definitions.append(
                        f"    `{column_name.lower()}` {data_type}"
                    )
            column_definitions.append(
                "    `updated_date` DATETIME NOT NULL default current_timestamp"
            )
            column_definitions.append("    `codeableconcept_max_array_size` INT")
            column_definitions.append("    `reference_max_array_size` INT")
            column_definitions.append("    `identifier_max_array_size` INT")

            bloom_filter_columns, bitmap_index_columns = (
                ResourceSchemaGenerator.index_creator(
                    index_column_dict, column_definitions, table_name
                )
            )

            column_names, column_data_types, table_names, index_info = (
                ResourceSchemaGenerator.initialize_schema_for_excel(
                    table_name,
                    column_definitions,
                    bloom_filter_columns,
                    bitmap_index_columns,
                    column_names,
                    column_data_types,
                    table_names,
                    index_info,
                )
            )

            ResourceSchemaGenerator.config_file_creator(column_definitions, table_name)

            create_table_stmt += ",\n".join(column_definitions)
            create_table_stmt += "\n)"
            create_table_stmt += "ENGINE=olap\n"
            create_table_stmt += "PRIMARY KEY (id)\n"
            create_table_stmt += "DISTRIBUTED BY HASH(id) BUCKETS 16\n"
            if bloom_filter_columns:
                bloom_filter_properties = (
                    '"' + ", ".join(f"{item}" for item in bloom_filter_columns) + '"'
                )
                create_table_stmt += f"""PROPERTIES
(
"storage_type"="column",
"compression" = "LZ4",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num"= "{replication_num}",
"bloom_filter_columns" = {bloom_filter_properties},
"colocate_with" = "core_group"
);\n\n"""
            else:
                create_table_stmt += f"""PROPERTIES
(
"storage_type"="column",
"compression" = "LZ4",
"enable_async_write_back" = "false",
"enable_persistent_index" = "true",
"persistent_index_type" = "CLOUD_NATIVE",
"replication_num"= "{replication_num}",
"colocate_with" = "core_group"
);\n\n"""
            schema_sql += create_table_stmt

        with open(output_file, "w", encoding="utf-8") as file:
            file.write(schema_sql)

        logging.info("Database schema saved to %s", output_file)

    @staticmethod
    def config_file_creator(column_definitions, resource_name):
        """
        Function to create config file
        """
        config_content = []

        for column_definition in column_definitions:
            column_definition = column_definition.replace("`", "")
            column_definition = column_definition.strip().split(" ")
            if column_definition[1] in ["ARRAY<INTEGER>", "ARRAY<ARRAY<INTEGER>>"]:
                config_content.append(f"{column_definition[0]}:{column_definition[1]}")

        if config_content:
            with open(
                f"configurations/{resource_name}.ini", "w", encoding="utf-8"
            ) as file:
                file.write("[column_mappings]\n")
                file.write("\n".join(config_content))

    @staticmethod
    def index_creator(index_column_dict: dict, column_definitions: list, table_name):
        """
        Function to handle index creation
        """

        bloom_filter_columns = []
        bitmap_index_columns = []
        for table_indexes in index_column_dict.get(table_name, []):
            column_name = list(table_indexes.keys())[0]
            if table_indexes[column_name] in ["code", "boolean", "enum"]:
                bitmap_index_columns.append(column_name)
                column_definitions.append(
                    f"    INDEX {table_name}_{column_name}_index (`{column_name}`) USING BITMAP"
                )
            elif table_indexes[column_name] == "string":
                bloom_filter_columns.append(column_name)

        return bloom_filter_columns, bitmap_index_columns

    @staticmethod
    def create_deletion_attributes(deletion_attribute_dict):
        """
        Function creates a python file for quick access of deletion attributes
        """
        try:
            logging.info("Writing deletion attributes dictionary into file as json")
            json.dump(
                deletion_attribute_dict,
                open("schema/output/deletion_attributes.json", "w", encoding="utf-8"),
            )
            logging.info("Deletion attributes written to file")
        except Exception as ex:
            logging.info("Failed to create deletion attribute file")
            logging.info(ex)
            logging.info(ex)
