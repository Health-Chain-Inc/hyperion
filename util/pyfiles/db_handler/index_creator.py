# Standard library imports

from pyfiles.dependencies.handlers import Handlers


class IndexCreator:
    """
        index creator identifies the columns that need to have indexes on them,
        refer solution design document for more information
    """
    def __init__(self, directory_path):
        self.directory_path = directory_path
        self.index_column_types = [
            "boolean",
            "code",
            "enum",
            "string",
        ]

    def resource_index_creator(self, resource_name):
        """
        Function to create/identify index columns
        """
        index_column_list = []
        resource_schema = Handlers.json_reader(
            f"{self.directory_path}/{resource_name}.json"
        )

        resource_snap_shot = resource_schema.get("snapshot", {})
        resource_snap_shot_elements = resource_snap_shot.get("element", [])
        for column_snap_shot in resource_snap_shot_elements:
            if len(column_snap_shot.get("id").split(".")) == 2:
                if column_snap_shot.get("max") == str("1") and (
                    column_snap_shot.get("isModifier")
                    or column_snap_shot.get("isSummary")
                ):
                    for column in column_snap_shot.get("type", []):
                        column_data_type = column.get("code")
                        if column_data_type.lower() in self.index_column_types:
                            index_column = (
                                column_snap_shot.get("id").split(".")[-1].lower()
                            )
                            if "[x]" in index_column:
                                index_column = index_column.replace(
                                    "[x]", column_data_type
                                )
                            index_column_list.append({index_column: column_data_type})

        return index_column_list
