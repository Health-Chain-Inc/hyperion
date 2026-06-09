import logging
import os
import re
import signal
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv()


class AdminGrantManager:
    """
    Watches engine FE audit logs for CREATE DATABASE statements and
    automatically grants privileges to the admin role.

    Production-hardened:
    - Survives log rotation (inode-based detection)
    - Startup sync to catch missed events
    - Graceful shutdown on SIGTERM/SIGINT
    - Health check file for K8s liveness probes
    - Single shared SQLAlchemy engine
    """

    CREATE_DB_PATTERN = re.compile(
        r'''(?i)                               # case-insensitive
            \b(?:create[\W_]*database)\b
            (?:\s+if\s+not\s+exists)?
            \s*
            (?:                                # capture the DB name in one of these forms:
                `([^`]+)`                      #   backticked
            | "([^"]+)"                        #   double-quoted
            | '([^']+)'                        #   single-quoted
            | ([A-Za-z0-9_]+)                  #   bare identifier
            )
        ''',
        re.X
    )

    SYSTEM_DATABASES = frozenset({
        '_statistics_', 'information_schema', 'sys',
    })

    def __init__(self):
        host, port = os.getenv('SILVER_LAYER_QUERY_SERVER').split(':')
        self.db_url = (
            f"mysql+pymysql://{os.getenv('SILVER_LAYER_ROOT_USERNAME')}:"
            f"{os.getenv('SILVER_LAYER_ROOT_PASSWORD')}@"
            f"{host}:{port}"
        )
        self.admin_role = os.getenv('ADMIN_ROLE')
        self.log_file_path = os.getenv('FE_LOG_FILE_PATH')
        self.max_retries = 3
        self.health_check_file = os.getenv(
            'HEALTH_CHECK_FILE', '/tmp/admin_grant_manager_healthy'
        )
        self._shutdown = False

        self.logger = self._setup_logger(
            name='admin_grant_manager_logger',
            filename=f'{os.getenv("FE_LOG_PATH")}/admin_grant_manager.log',
            level=os.getenv('LOG_LEVEL', 'DEBUG'),
            rotate=True
        )

        self.engine = create_engine(
            self.db_url,
            connect_args={'connect_timeout': 120},
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_size=5,
            max_overflow=0
        )

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        self.logger.info("Received %s, initiating graceful shutdown", sig_name)
        self._shutdown = True

    @staticmethod
    def _setup_logger(
        name: str,
        filename: str,
        level: str,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 10,
        rotate: bool = True
    ) -> logging.Logger:
        """Set up and return a logger with optional file rotation."""
        logger_config = logging.getLogger(name)
        logger_config.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger_config.propagate = False

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

    def _touch_health_file(self):
        """Update the health check file timestamp for K8s liveness probes."""
        try:
            Path(self.health_check_file).touch()
        except OSError:
            self.logger.warning(
                "Failed to touch health check file: %s",
                self.health_check_file, exc_info=True
            )

    def _extract_databases(self, line: str) -> list:
        """
        Extract database names from a log line containing CREATE DATABASE.

        Returns:
            List of database names found, or empty list if none.
        """
        stmt_match = re.search(r'Stmt=(.*?)(?=\|Digest=)', line, flags=re.S)
        stmt = stmt_match.group(1) if stmt_match else line
        db_names = [s for t in self.CREATE_DB_PATTERN.findall(stmt) for s in t if s]
        return db_names

    def _grant_privileges(self, database, conn):
        """Grant privileges on a database to the admin role."""
        try:
            quoted_db = f"`{database}`"
            quoted_role = f"`{self.admin_role}`"

            if 'hyperion' in database and ('audit' not in database and 'portal' not in database):
                grant_sqls = [
                    f"GRANT SELECT ON ALL TABLES IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT SELECT ON ALL VIEWS IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT SELECT ON ALL MATERIALIZED VIEWS IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT USAGE ON ALL FUNCTIONS IN DATABASE {quoted_db} TO ROLE {quoted_role}"
                ]
            elif 'audit' in database:
                self.logger.info("Skipping audit-related database: %s", database)
                return True
            elif 'portal' in database:
                self.logger.info("Skipping ui-portal related database: %s", database)
                return True
            else:
                grant_sqls = [
                    f"GRANT ALL ON DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT ALL ON ALL TABLES IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT ALL ON ALL VIEWS IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT ALL ON ALL MATERIALIZED VIEWS IN DATABASE {quoted_db} TO ROLE {quoted_role}",
                    f"GRANT ALL ON ALL FUNCTIONS IN DATABASE {quoted_db} TO ROLE {quoted_role}"
                ]

            for sql in grant_sqls:
                conn.execute(text(sql))
                self.logger.debug("Executed: %s", sql)

            return True
        except SQLAlchemyError as e:
            self.logger.error(
                "Failed to execute grant for database %s: %s",
                database, e, exc_info=True
            )
            raise

    def _process_databases(self, databases: list):
        """
        Process grants for a list of databases with retry logic.

        Uses the shared engine; connection errors are retried with exponential backoff.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                with self.engine.begin() as conn:
                    for database in databases:
                        self._grant_privileges(database, conn)
                        self.logger.info("Successfully granted privileges for %s", database)
                return

            except SQLAlchemyError as e:
                self.logger.error(
                    "Database error on attempt %d/%d: %s",
                    attempt, self.max_retries, e, exc_info=True
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    self.logger.error(
                        "Max retries reached for databases: %s", databases
                    )

            except Exception as e:
                self.logger.error(
                    "Unexpected error granting privileges: %s", e, exc_info=True
                )
                break

    def _startup_sync(self):
        """
        Sync grants for all existing databases.

        Queries SHOW DATABASES and grants privileges for each one.
        This is idempotent — re-granting already-granted privileges is a no-op
        in the engine.
        """
        self.logger.info("Running startup grant sync for all databases")
        for attempt in range(1, self.max_retries + 1):
            try:
                with self.engine.connect() as conn:
                    result = conn.execute(text("SHOW DATABASES"))
                    all_databases = [
                        row[0] for row in result
                        if row[0] not in self.SYSTEM_DATABASES
                    ]

                if not all_databases:
                    self.logger.info("No databases found during startup sync")
                    return

                self.logger.info(
                    "Startup sync: found %d databases to process",
                    len(all_databases)
                )
                self._process_databases(all_databases)
                self.logger.info("Startup sync completed successfully")
                return

            except SQLAlchemyError as e:
                self.logger.error(
                    "Startup sync failed on attempt %d/%d: %s",
                    attempt, self.max_retries, e, exc_info=True
                )
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)
                else:
                    self.logger.error(
                        "Startup sync failed after %d attempts, continuing anyway",
                        self.max_retries
                    )

            except Exception as e:
                self.logger.error(
                    "Unexpected error during startup sync: %s", e, exc_info=True
                )
                break

    def _get_file_inode(self, path):
        """Get the inode number for a file path. Returns None on error."""
        try:
            return os.stat(path).st_ino
        except FileNotFoundError:
            return None
        except OSError:
            self.logger.warning(
                "Could not stat %s", path, exc_info=True
            )
            return None

    def _tail_follow(self, path):
        """
        Generator that tails a file and survives log rotation.

        Yields lines from the file. Detects rotation by comparing the inode
        of the path on disk vs the open file descriptor. On rotation, reads
        remaining lines from the old fd, then reopens the new file from the
        beginning.

        Yields:
            tuple of (line, rotated) where rotated is True if rotation was
            just detected and handled.
        """
        while not self._shutdown:
            try:
                f = open(path, 'r')
            except FileNotFoundError:
                self.logger.warning(
                    "Log file not found: %s, waiting for it to appear", path
                )
                time.sleep(10)
                continue

            try:
                fd_inode = os.fstat(f.fileno()).st_ino
                f.seek(0, 2)  # seek to end
                self.logger.info(
                    "Opened log file: %s (inode: %s)", path, fd_inode
                )

                idle_count = 0
                while not self._shutdown:
                    line = f.readline()
                    if line:
                        idle_count = 0
                        yield (line.rstrip('\n'), False)
                    else:
                        idle_count += 1
                        time.sleep(1)

                        if idle_count >= 5:
                            idle_count = 0

                            # Check for rotation (inode change)
                            path_inode = self._get_file_inode(path)
                            if path_inode is None:
                                # File doesn't exist yet (mid-rotation)
                                self.logger.info(
                                    "Log file disappeared (rotation in progress), "
                                    "waiting for new file"
                                )
                                continue

                            if path_inode != fd_inode:
                                self.logger.info(
                                    "Log rotation detected (fd inode: %s, "
                                    "path inode: %s)", fd_inode, path_inode
                                )
                                # Drain remaining lines from old file
                                while True:
                                    remaining = f.readline()
                                    if not remaining:
                                        break
                                    yield (remaining.rstrip('\n'), False)

                                # Signal rotation so caller can run sync
                                yield ('', True)
                                break  # reopen new file

                            # Check for truncation (file smaller than position)
                            try:
                                current_size = os.fstat(f.fileno()).st_size
                                current_pos = f.tell()
                                if current_size < current_pos:
                                    self.logger.info(
                                        "File truncation detected (size: %d, "
                                        "pos: %d), seeking to beginning",
                                        current_size, current_pos
                                    )
                                    f.seek(0)
                            except OSError:
                                pass

            except OSError as e:
                self.logger.error(
                    "I/O error tailing log file: %s", e, exc_info=True
                )
                time.sleep(10)
            finally:
                f.close()

    def main(self):
        """
        Main loop — continuously watches the FE audit log file.

        Survives log rotation, handles errors gracefully, and syncs
        grants on startup and after each rotation.
        """
        self.logger.info("Starting AdminGrantManager: log=%s, role=%s, health=%s", self.log_file_path, self.admin_role, self.health_check_file)

        try:
            self._startup_sync()
            self._touch_health_file()

            for line, rotated in self._tail_follow(self.log_file_path):
                if self._shutdown:
                    break

                if rotated:
                    self.logger.info(
                        "Running post-rotation sync to catch missed events"
                    )
                    self._startup_sync()
                    self._touch_health_file()
                    continue

                if not line:
                    continue

                self.logger.debug(
                    "Log line: %s", line[:100]
                )

                databases = self._extract_databases(line)

                if databases:
                    self.logger.info("Found CREATE DATABASE: %s", databases)
                    self._process_databases(databases)

                self._touch_health_file()

        except Exception:
            self.logger.error(
                "Fatal error in main loop", exc_info=True
            )
        finally:
            self.logger.info("Shutting down AdminGrantManager")
            try:
                self.engine.dispose()
                self.logger.info("Database engine disposed")
            except Exception:
                self.logger.error(
                    "Error disposing engine", exc_info=True
                )

            # Remove health file on shutdown
            try:
                os.remove(self.health_check_file)
            except OSError:
                pass

            self.logger.info("AdminGrantManager stopped")


if __name__ == "__main__":
    admin_grant_manager = AdminGrantManager()
    admin_grant_manager.main()
