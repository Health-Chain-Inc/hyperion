"""Import modules"""

import json
import logging

import pandas as pd

from pyfiles.dependencies.data_processing_error import DataProcessingException
from pyfiles.dependencies.df_ops import DFOps
from pyfiles.dependencies.enum import PipelineErrorCode

# Disable pandas chained assignment warnings
pd.options.mode.chained_assignment = None

class Normalizer:
    """FHIR Normalizer Class"""

    def __init__(
        self, resource_structure, fhir_resource_type, fhir_df, filepath_id
    ):
        self.fhir_resource_type = fhir_resource_type
        self.resource_structure = resource_structure
        self.data = fhir_df
        self.filepath_id = filepath_id
        self.backbone_objects = {}
        self.dataframes = {}

    def dataframe_column_iterator(self, dataframe, schema_definition):
        """
        Iterate through columns in dataframe to classify column as primitive,
        extension, codeableconcept, reference, identifier, backbone,
        child backbone, complex datatypes with and without arrays
        Args:
            dataframe: Dataframe created from FHIR JSON
            schema_definition: HL7 FHIR schema
        """
        codeableconcepts = []
        references = []
        identifiers = []
        array_other_complex = []
        non_array_other_complex = []
        primitive = []
        extensions = []
        for column in dataframe.columns:
            (fhir_datatype, is_array, complex_datatype, backbone) = (
                self.get_column_information(schema_definition, column)
            )
            if backbone:
                self.backbone_objects[fhir_datatype] = {}
                self.backbone_objects[fhir_datatype]["data"] = self.data[["id", column]]
                self.backbone_objects[fhir_datatype]["array"] = is_array
                self.backbone_objects[fhir_datatype]["column"] = column

            elif not complex_datatype:
                primitive.append(column)

            elif complex_datatype:
                if fhir_datatype in ("CodeableConcept", "Coding"):
                    codeableconcepts.append(column)
                elif fhir_datatype == "Reference":
                    references.append(column)
                elif fhir_datatype == "Identifier":
                    identifiers.append(column)
                elif fhir_datatype == "Extension":
                    extensions.append(column)
                else:
                    if is_array:
                        array_other_complex.append(column)
                    else:
                        non_array_other_complex.append(column)

        return (
            codeableconcepts,
            references,
            identifiers,
            extensions,
            array_other_complex,
            non_array_other_complex,
            primitive,
        )

    def get_column_information(self, schema_definition, column):
        """
        Iterate through columns in dataframe to get column datatypes and cardinality
        Args:
            schema_definition: HL7 FHIR schema
            column: column name from dataframe
        """
        try:
            column_configuration = self.resource_structure["definitions"][
                schema_definition
            ]["properties"][column]

            # Check if column is array
            is_array = column_configuration.get("type") == "array"

            # Check for fhir datatype, complex datatype and backbone
            complex_datatype = False
            backbone = False

            if column not in self.data:
                self.data[column] = None

            fhir_datatype = column_configuration.get("items", {}).get(
                "$ref"
            ) or column_configuration.get("$ref")
            if fhir_datatype:
                fhir_datatype = fhir_datatype.split("/")[-1]
            else:
                fhir_datatype = "string"

            if self.fhir_resource_type in fhir_datatype:
                backbone = True

            if (
                self.resource_structure["definitions"]
                .get(fhir_datatype, {})
                .get("properties")
            ):
                complex_datatype = True

            return fhir_datatype, is_array, complex_datatype, backbone
        except DataProcessingException as e:
            # pylint: disable=line-too-long
            message = f"(filepath_id={self.filepath_id}): Function failed to get column information for {column}: {e.errors}"
            # pylint: enable=line-too-long
            raise DataProcessingException(message, str(e), PipelineErrorCode.NORMALIZATION_FAILED.value) from e

    @staticmethod
    def normalizer(input_dataframe, column_list, is_array: bool) -> pd.DataFrame:
        """
        FHIR data normalizer
        Args:
            input_dataframe: FHIR dataframe
            column_list: list of columns/FHIR attributes to be normalized
            is_array: Flag to check if FHIR attribute is array
        """
        try:
            output_dataframe = input_dataframe[["id"]]
            output_dataframe["index"] = range(len(output_dataframe))
            for column in column_list:
                data = input_dataframe[["id", column]]
                data = data.dropna(subset=column).reset_index(drop=True)
                # Each dictionary/list can create multiple rows and when
                # creating array of arrays this value will be required
                # for proper grouping of values based on dictionary values
                data["hash"] = data[column].apply(DFOps.hash_row)
                if data[column].apply(lambda x: isinstance(x, list)).any():
                    data = (
                        data.set_index(["id", "hash"])
                        .apply(lambda x: x.apply(pd.Series).stack())
                        .reset_index()
                    )
                    DFOps.drop_column(data, ["level_2"])

                if data[column].apply(lambda x: isinstance(x, dict)).any():
                    data[column] = data[column].where(pd.notnull(data[column]), {})

                    normalized_data = pd.json_normalize(
                        data[column], max_level=0, errors="ignore"
                    )
                    # normalized_data = normalized_data.fillna(None)
                    normalized_data.columns = [
                        f"{column}_{col}" for col in normalized_data.columns
                    ]
                    normalized_data.columns = [
                        col.replace(".", "_") for col in normalized_data.columns
                    ]
                    normalized_data = pd.concat([data, normalized_data], axis=1)
                    DFOps.drop_column(normalized_data, [column])
                    columns_to_check = [
                        column
                        for column in normalized_data.columns
                        if column not in ["id", "hash"]
                    ]
                    normalized_data = normalized_data.dropna(
                        subset=columns_to_check, how="all"
                    ).reset_index(drop=True)

                    if len(normalized_data) >= 1:
                        normalized_data.columns = [
                            column.lower() for column in normalized_data.columns
                        ]
                        normalized_data = normalized_data.where(
                            pd.notnull(normalized_data), None
                        )
                        normalized_data = normalized_data.where(
                            pd.notna(normalized_data), None
                        )

                        columns_to_list = [
                            column
                            for column in normalized_data.columns
                            if column not in ["id", "hash", "hash_interim"]
                        ]

                        if is_array:
                            normalized_data = normalized_data.groupby(
                                ["hash", "id"], as_index=False
                            )[columns_to_list].agg(list)

                    normalized_data[f"{column}_index"] = range(len(normalized_data))

                DFOps.drop_column(normalized_data, [column, "hash", "hash_interim"])
                output_dataframe = output_dataframe.merge(
                    normalized_data,
                    left_on=["id"],
                    right_on=["id"],
                    how="left",
                )
                DFOps.drop_column(output_dataframe, [f"{column}_index"])
                output_dataframe = output_dataframe.where(
                    pd.notnull(output_dataframe), None
                )
                output_dataframe = output_dataframe.where(
                    pd.notna(output_dataframe), None
                )
            DFOps.drop_column(output_dataframe, ["index"])
            return output_dataframe
        except Exception as e:
            raise DataProcessingException("Normalization failed", str(e), PipelineErrorCode.NORMALIZATION_FAILED.value) from e

    def run(self):
        """
        Main function that normalizes the data as required,
          joins all the dataframes into one unified resource
          dataframe and adds all dataframes in a dictionary
        """
        (
            codeableconcepts,
            references,
            identifiers,
            extensions,
            array_other_complex,
            non_array_other_complex,
            primitive,
        ) = self.dataframe_column_iterator(self.data, self.fhir_resource_type)

        resource_dataframe = self.data[["id"]]

        primitives = pd.DataFrame()
        if primitive:
            primitives = self.data[primitive]
            resource_dataframe = resource_dataframe.merge(
                primitives, on="id", how="left"
            )
            resource_dataframe.columns = [
                col.lower() if col != "id" else col
                for col in resource_dataframe.columns
            ]

        codeableconcept_dataframe = pd.DataFrame()
        max_cc_dataframe = pd.DataFrame()
        reference_dataframe = pd.DataFrame()
        max_references_dataframe = pd.DataFrame()
        identifier_dataframe = pd.DataFrame()
        max_identifier_dataframe = pd.DataFrame()

        if codeableconcepts:
            codeableconcept_dataframe = self.data[["id"] + codeableconcepts]
            (
                codeableconcept_dataframe,
                max_cc_dataframe,
            ) = DFOps.process_codeableconcepts(
                codeableconcept_dataframe, self.fhir_resource_type, self.filepath_id
            )

        if references:
            reference_dataframe = self.data[["id"] + references]
            (
                reference_dataframe,
                max_references_dataframe,
            ) = DFOps.process_references(
                reference_dataframe, self.fhir_resource_type, self.filepath_id
            )

        if identifiers:
            identifier_dataframe = self.data[["id"] + identifiers]
            (
                identifier_dataframe,
                max_identifier_dataframe,
            ) = DFOps.process_identifiers(
                identifier_dataframe, self.fhir_resource_type, self.filepath_id
            )

        extension_dataframe = self.data[["id"] + extensions]
        resource_dataframe = resource_dataframe.merge(
            extension_dataframe, on="id", how="left"
        )

        array_other_complex_dataframe = pd.DataFrame()
        if array_other_complex:
            array_other_complex_dataframe = Normalizer.normalizer(
                self.data, array_other_complex, True
            )
            resource_dataframe = resource_dataframe.merge(
                array_other_complex_dataframe, on="id", how="left"
            )
        non_array_other_complex_dataframe = pd.DataFrame()
        if non_array_other_complex:
            non_array_other_complex_dataframe = Normalizer.normalizer(
                self.data, non_array_other_complex, False
            )
            resource_dataframe = resource_dataframe.merge(
                non_array_other_complex_dataframe, on="id", how="left"
            )

        # Backbone element normalization
        for backbone_name, obj in self.backbone_objects.items():
            logging.debug(
                "(filepath_id=%s): Working on backbone %s",
                self.filepath_id,
                backbone_name,
            )

            if obj["array"]:
                # No need to explode or unnest backbones with 0..* or 1..*
                obj["normalized"] = obj["data"]
                obj["normalized"].columns = [
                    col.lower() if col != "id" else col
                    for col in obj["normalized"].columns
                ]

            else:
                obj["data"].dropna(subset=obj["column"], inplace=True)
                data_to_normalize = json.loads(obj["data"][['id', obj["column"]]].to_json(orient='records'))

                rows = []
                for entry in data_to_normalize:
                    # Add all first-level fields from the nested dict
                    if obj["column"] in entry and isinstance(entry[obj["column"]], dict):
                        row = {'id': entry['id']}
                        row.update(entry[obj["column"]])
                        rows.append(row)

                # Build the normalized DataFrame and rename columns once, after the loop.
                # (Prior to this fix, both statements ran inside the for-loop, which built
                # N throwaway DataFrames for N entries and could leave a stale value if the
                # last entry didn't match the dict-check above.)
                obj["normalized"] = pd.DataFrame(rows)
                obj["normalized"].columns = [
                    f"{obj['column'].lower()}_{col.lower()}" if col != "id" else col
                    for col in obj["normalized"].columns
                ]

            resource_dataframe = resource_dataframe.merge(
                obj["normalized"], on="id", how="left"
            )

            logging.debug(
                "(filepath_id=%s): Processing complete for backbone %s",
                self.filepath_id,
                backbone_name,
            )

        if not max_cc_dataframe.empty:
            resource_dataframe = resource_dataframe.merge(
                max_cc_dataframe, on="id", how="left"
            )
            resource_dataframe["codeableconcept_max_array_size"] = resource_dataframe[
                ["codeableconcept_max_array_size"]
            ].fillna(0)

        if not max_references_dataframe.empty:
            resource_dataframe = resource_dataframe.merge(
                max_references_dataframe, on="id", how="left"
            )
            resource_dataframe["reference_max_array_size"] = resource_dataframe[
                ["reference_max_array_size"]
            ].fillna(0)

        if not max_identifier_dataframe.empty:
            resource_dataframe = resource_dataframe.merge(
                max_identifier_dataframe, on="id", how="left"
            )
            resource_dataframe["identifier_max_array_size"] = resource_dataframe[
                ["identifier_max_array_size"]
            ].fillna(0)

        resource_dataframe.columns = [
                    column.lower() for column in resource_dataframe.columns
                ]
        self.dataframes[self.fhir_resource_type.lower()] = resource_dataframe
        self.dataframes["codeableconcept"] = codeableconcept_dataframe
        self.dataframes["reference"] = reference_dataframe
        self.dataframes["identifier"] = identifier_dataframe
        return self.dataframes
