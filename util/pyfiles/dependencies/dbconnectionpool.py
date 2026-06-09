
import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from pyfiles.dependencies.handlers import Handlers


class DBConnectionPool:
    def __init__(self, config):
        """
        Class to create async connection pools
        """
        self.config = config
        logging.info("DBConnectionPool instance created")

    def initialize(self, db_type):
        """
        Initialize the database engine and pool asynchronously.
        This method should be called after the DBConnectionPool object is created.
        db_type accepts two values 1> core, 2> audit
        """
        try:
            logging.info("Creating async connection engine and pool")

            if db_type == "core":
                self.connection_string = (
                    f"mysql+pymysql://{Handlers.get_silver_layer_core_connection_parameters(self.config)}"
                )
            elif db_type == "audit":
                self.connection_string = (
                    f"mysql+pymysql://{Handlers.get_silver_layer_audit_connection_parameters(self.config)}"
                )
            elif db_type:
                self.connection_string = (
                    f"mysql+pymysql://{Handlers.get_database_connection_parameters(self.config, db_type)}"
                )
            else:
                self.connection_string = (
                    f"mysql+pymysql://{Handlers.get_database_connection_parameters(self.config, db_type)}"
                )

            logging.info("Connection string for %s database created successfully", db_type)
            logging.info(self.connection_string)

            self.engine = create_engine(
                self.connection_string,
                echo=False
            )

            return self.engine

        except SQLAlchemyError as err:
            logging.error("Error creating async connection engine or pool. Error: %s", str(err))
            raise
