# Standard library imports
import logging

# Third-party imports
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

# Local imports
from pyfiles.dependencies.data_processing_error import PrerequisiteError
from pyfiles.dependencies.handlers import Handlers
from pyfiles.dependencies.resource_manager import ResourceManager


class DBConnectionPool:
    """
    Database connection pool creation class
    """
    def __init__(self, config, database):
        """
            Class to create connection pools
        """
        try:
            connection_string = (
                f"mysql+pymysql://{Handlers.get_silver_layer_connection_parameters(config, database)}"
            )
            self.engine = create_engine(
                connection_string,
                echo=False,
                pool_pre_ping=True,
                pool_recycle=300,      # Reduced from 3600 to 300 (5 min) for faster cleanup
                pool_size=int(config['pools']['database']),
                max_overflow=2,        # Reduced from 10 to 2 to limit memory usage
                pool_timeout=30,       # Add timeout to prevent hanging connections
                future=True
            )

            try:
                self.engine.connect()
            except SQLAlchemyError as err:
                logging.exception("Database connection test failed")
                raise PrerequisiteError("Database connection test failed") from err

            self.SessionFactory = sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False,
                future=True
            )
            logging.info("Created database connection pool: database=%s, size=%s", database, config['pools']['database'])

            # Register with ResourceManager for cleanup on shutdown
            ResourceManager().register("db_pool", self, self.dispose)

        except SQLAlchemyError as err:
            logging.exception("Error creating connection engine or pool")
            raise PrerequisiteError("Error creating connection engine or pool") from err

    def create_connection(self):
        """
        function to create connections in the pool
        """
        return self.engine.connect()

    def dispose(self):
        """
        Dispose the connection pool and release all resources.
        Should be called during application shutdown.
        """
        if self.engine:
            logging.info("Disposing database connection pool")
            self.engine.dispose()
            self.engine = None
