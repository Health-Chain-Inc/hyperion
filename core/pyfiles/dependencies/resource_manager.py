"""
Centralized Resource Manager for coordinating cleanup of all resources.

This module provides a singleton ResourceManager that tracks all resources
and ensures proper cleanup during application shutdown.
"""

import atexit
import gc
import logging
from typing import Any, Callable, List, Tuple


class ResourceManager:
    """
    Singleton resource manager for centralized cleanup coordination.

    Usage:
        # Register a resource with cleanup function
        ResourceManager().register("db_pool", pool, pool.dispose)

        # Manual shutdown (also called automatically via atexit)
        ResourceManager().shutdown()
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._resources = {}
            cls._instance._cleanup_functions: List[Tuple[str, Callable]] = []
            cls._instance._is_shutdown = False
            atexit.register(cls._instance.shutdown)
        return cls._instance

    def register(self, name: str, resource: Any, cleanup_fn: Callable = None):
        """
        Register a resource for tracking and cleanup.

        Args:
            name: Unique identifier for the resource
            resource: The resource object to track
            cleanup_fn: Optional cleanup function to call during shutdown
        """
        if self._is_shutdown:
            logging.warning("Cannot register resource '%s': ResourceManager already shut down", name)
            return

        self._resources[name] = resource
        if cleanup_fn:
            self._cleanup_functions.append((name, cleanup_fn))
        logging.debug("Registered resource: %s", name)

    def unregister(self, name: str):
        """
        Unregister a resource without calling cleanup.

        Args:
            name: The resource identifier to unregister
        """
        if name in self._resources:
            del self._resources[name]
            self._cleanup_functions = [
                (n, fn) for n, fn in self._cleanup_functions if n != name
            ]
            logging.debug("Unregistered resource: %s", name)

    def get(self, name: str) -> Any:
        """
        Get a registered resource by name.

        Args:
            name: The resource identifier

        Returns:
            The registered resource or None if not found
        """
        return self._resources.get(name)

    def shutdown(self):
        """
        Clean up all registered resources in reverse registration order.

        This method is called automatically via atexit, but can also be
        called manually for graceful shutdown.
        """
        if self._is_shutdown:
            return

        self._is_shutdown = True
        logging.info("ResourceManager: Starting shutdown, cleaning up %d resources",
                     len(self._cleanup_functions))

        # Clean up in reverse order (LIFO)
        for name, cleanup_fn in reversed(self._cleanup_functions):
            try:
                cleanup_fn()
                logging.debug("Cleaned up resource: %s", name)
            except Exception as e:
                logging.warning("Error cleaning up %s: %s", name, e)

        self._resources.clear()
        self._cleanup_functions.clear()

        # Force garbage collection
        gc.collect()
        logging.info("ResourceManager: Shutdown complete")

    def clear_caches(self):
        """
        Clear all registered LRU caches.

        Call this method to free memory from cached function results.
        """
        from pyfiles.hyperion_core.core_load_processor import CoreLoadProcessor
        from pyfiles.dependencies.df_ops import DFOps

        try:
            if hasattr(CoreLoadProcessor, 'get_fhir_structure'):
                CoreLoadProcessor.get_fhir_structure.cache_clear()
                logging.debug("Cleared CoreLoadProcessor.get_fhir_structure cache")
        except Exception as e:
            logging.warning("Error clearing CoreLoadProcessor cache: %s", e)

        try:
            if hasattr(DFOps, 'create_pandas_dataframe'):
                DFOps.create_pandas_dataframe.cache_clear()
                logging.debug("Cleared DFOps.create_pandas_dataframe cache")
        except Exception as e:
            logging.warning("Error clearing DFOps cache: %s", e)

        gc.collect()

    @property
    def is_shutdown(self) -> bool:
        """Check if the ResourceManager has been shut down."""
        return self._is_shutdown

    def reset(self):
        """
        Reset the ResourceManager state (primarily for testing).

        Warning: This does not call cleanup functions.
        """
        self._resources.clear()
        self._cleanup_functions.clear()
        self._is_shutdown = False
