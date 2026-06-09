from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import logging
from logging.handlers import RotatingFileHandler
import socket

class SidecarInit():

    def __init__(self, logger_config, project_configurations:dict):
        self.logger = logger_config
        self.project_configurations = project_configurations
        self.engine = self.get_engine()

    @staticmethod
    def setup_logger(
        name: str,
        filename: str,
        level: str,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
        rotate: bool = True
    ) -> logging.Logger:
        """
        Set up and return a logger with optional file rotation.

        Parameters:
            name (str): Logger name.
            filename (str): Log file path.
            level (str): Logging level as a string (e.g., 'DEBUG', 'INFO', etc.).
            max_bytes (int): Max bytes per log file before rotation.
            backup_count (int): Number of backup files to keep.
            rotate (bool): Whether to enable file rotation.

        Returns:
            logging.Logger: Configured self.logger.
        """
        logger_config = logging.getLogger(name)
        logger_config.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger_config.propagate = False  # Prevent duplicate logs if root logger is also logging

        # Avoid adding duplicate handlers
        if not logger_config.handlers:
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

            if rotate:
                handler = RotatingFileHandler(
                    filename, maxBytes=max_bytes, backupCount=backup_count
                )
            else:
                handler = logging.FileHandler(filename)

            handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            handler.setFormatter(formatter)
            logger_config.addHandler(handler)

            console_handler = logging.StreamHandler()
            console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
            console_handler.setFormatter(formatter)
            logger_config.addHandler(console_handler)

        return logger_config

    def get_current_hostname(self):
        try:
            hostname = socket.getfqdn()
            self.logger.debug('Current hostname: %s', hostname)
            return hostname
        except Exception as e:
            self.logger.error("Error getting hostname: %s", e)
            return None

    def get_engine(self):
        host, port = self.project_configurations.get('query_server').split(':')
        db_url = f"mysql+pymysql://{self.project_configurations.get('username')}:" \
                      f"{self.project_configurations.get('root_password')}@" \
                      f"{host}:{port}"
        engine = create_engine(
            db_url,
            connect_args={'connect_timeout': 120},
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=0
        )
        return engine
        

    def check_leader_fe(self):
        try:
            hostname = self.get_current_hostname()

            if not hostname:
                return False

            if not self.engine:
                return False

            with self.engine.connect() as conn:
                result = conn.execute(text("SHOW FRONTENDS")).mappings().all()

            for row in result:
                if row['IP'] == hostname and row['Role'] == 'LEADER':
                    self.logger.info("This FE (%s) is the leader", hostname)
                    return True

            self.logger.info("This FE (%s) is not the leader", hostname)
            return False

        except SQLAlchemyError as e:
            self.logger.error("Error checking FE role: %s", e)
            return False

    def dispose_engine(self):
        """Dispose the cached engine and release DB connections."""
        if self.engine:
            try:
                self.engine.dispose()
                self.logger.debug("SQLAlchemy engine disposed")
            except Exception as e:
                self.logger.warning("Error disposing engine: %s", e)
            self.engine = None