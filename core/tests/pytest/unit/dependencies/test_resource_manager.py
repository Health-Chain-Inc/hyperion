"""Unit tests for ResourceManager singleton class."""
import pytest
from unittest.mock import MagicMock, patch

from pyfiles.dependencies.resource_manager import ResourceManager


@pytest.fixture(autouse=True)
def reset_resource_manager():
    """Reset the ResourceManager singleton state before each test."""
    ResourceManager().reset()
    yield
    ResourceManager().reset()


@pytest.mark.unit
class TestResourceManagerSingleton:
    """Test singleton behaviour of ResourceManager."""

    def test_singleton_returns_same_instance(self):
        """Two ResourceManager() calls must return the identical object."""
        instance_a = ResourceManager()
        instance_b = ResourceManager()
        assert instance_a is instance_b

    def test_singleton_preserves_state_across_calls(self):
        """State registered on one reference is visible through another."""
        rm1 = ResourceManager()
        rm1.register("db", object())

        rm2 = ResourceManager()
        assert rm2.get("db") is not None


@pytest.mark.unit
class TestResourceManagerRegister:
    """Test register() method."""

    def test_register_resource_retrievable_via_get(self):
        """A registered resource is returned by get()."""
        rm = ResourceManager()
        obj = object()
        rm.register("my_resource", obj)
        assert rm.get("my_resource") is obj

    def test_register_stores_cleanup_function(self):
        """A registered cleanup function is stored for later invocation."""
        rm = ResourceManager()
        cleanup = MagicMock()
        rm.register("res", object(), cleanup)

        # Cleanup is not yet called
        cleanup.assert_not_called()

        # It should be in the internal list
        names = [name for name, _ in rm._cleanup_functions]
        assert "res" in names

    def test_register_without_cleanup_function_is_allowed(self):
        """Registering a resource with no cleanup function does not raise."""
        rm = ResourceManager()
        rm.register("bare_resource", object())  # no cleanup_fn
        assert rm.get("bare_resource") is not None

    def test_register_after_shutdown_logs_warning_and_does_not_add(self):
        """Registering after shutdown emits a warning and is ignored."""
        rm = ResourceManager()
        rm.shutdown()

        with patch("pyfiles.dependencies.resource_manager.logging") as mock_log:
            rm.register("late_resource", object())
            mock_log.warning.assert_called_once()

        assert rm.get("late_resource") is None


@pytest.mark.unit
class TestResourceManagerUnregister:
    """Test unregister() method."""

    def test_unregister_removes_resource(self):
        """unregister() removes the resource so get() returns None."""
        rm = ResourceManager()
        rm.register("temp", object())
        rm.unregister("temp")
        assert rm.get("temp") is None

    def test_unregister_removes_cleanup_function(self):
        """unregister() removes the associated cleanup function."""
        rm = ResourceManager()
        cleanup = MagicMock()
        rm.register("temp", object(), cleanup)
        rm.unregister("temp")

        names = [name for name, _ in rm._cleanup_functions]
        assert "temp" not in names

    def test_unregister_nonexistent_name_is_idempotent(self):
        """Calling unregister() on a name that was never registered does not raise."""
        rm = ResourceManager()
        rm.unregister("does_not_exist")  # should not raise


@pytest.mark.unit
class TestResourceManagerGet:
    """Test get() method."""

    def test_get_returns_none_for_missing_name(self):
        """get() returns None when no resource with that name exists."""
        rm = ResourceManager()
        assert rm.get("nonexistent") is None

    def test_get_returns_correct_resource_among_multiple(self):
        """get() returns the right resource when several are registered."""
        rm = ResourceManager()
        obj_a = object()
        obj_b = object()
        rm.register("a", obj_a)
        rm.register("b", obj_b)
        assert rm.get("a") is obj_a
        assert rm.get("b") is obj_b


@pytest.mark.unit
class TestResourceManagerShutdown:
    """Test shutdown() method."""

    def test_shutdown_calls_all_cleanup_functions(self):
        """shutdown() invokes every registered cleanup function."""
        rm = ResourceManager()
        fn1 = MagicMock()
        fn2 = MagicMock()
        rm.register("r1", object(), fn1)
        rm.register("r2", object(), fn2)

        rm.shutdown()

        fn1.assert_called_once()
        fn2.assert_called_once()

    def test_shutdown_calls_cleanup_in_reverse_order(self):
        """Cleanup functions are called in LIFO (reverse registration) order."""
        rm = ResourceManager()
        call_order = []
        rm.register("first", object(), lambda: call_order.append("first"))
        rm.register("second", object(), lambda: call_order.append("second"))
        rm.register("third", object(), lambda: call_order.append("third"))

        rm.shutdown()

        assert call_order == ["third", "second", "first"]

    def test_shutdown_continues_when_one_cleanup_raises(self):
        """An exception in one cleanup function does not abort the others."""
        rm = ResourceManager()
        fn_good = MagicMock()
        fn_bad = MagicMock(side_effect=RuntimeError("boom"))
        rm.register("good", object(), fn_good)
        rm.register("bad", object(), fn_bad)

        # Should not propagate the RuntimeError
        rm.shutdown()

        fn_good.assert_called_once()
        fn_bad.assert_called_once()

    def test_shutdown_sets_is_shutdown_true(self):
        """is_shutdown is True after shutdown() is called."""
        rm = ResourceManager()
        assert rm.is_shutdown is False
        rm.shutdown()
        assert rm.is_shutdown is True

    def test_shutdown_is_idempotent(self):
        """Calling shutdown() a second time is a no-op (does not re-run cleanups)."""
        rm = ResourceManager()
        fn = MagicMock()
        rm.register("r", object(), fn)

        rm.shutdown()
        rm.shutdown()

        # cleanup function called exactly once
        assert fn.call_count == 1


@pytest.mark.unit
class TestResourceManagerIsShutdown:
    """Test is_shutdown property."""

    def test_is_shutdown_false_initially(self):
        """is_shutdown is False on a fresh (or reset) instance."""
        rm = ResourceManager()
        assert rm.is_shutdown is False

    def test_is_shutdown_true_after_shutdown(self):
        """is_shutdown is True after shutdown() is called."""
        rm = ResourceManager()
        rm.shutdown()
        assert rm.is_shutdown is True


@pytest.mark.unit
class TestResourceManagerReset:
    """Test reset() method (used primarily in testing)."""

    def test_reset_clears_resources(self):
        """reset() removes all registered resources."""
        rm = ResourceManager()
        rm.register("item", object())
        rm.reset()
        assert rm.get("item") is None

    def test_reset_clears_cleanup_functions(self):
        """reset() empties the cleanup function list."""
        rm = ResourceManager()
        rm.register("item", object(), MagicMock())
        rm.reset()
        assert rm._cleanup_functions == []

    def test_reset_restores_is_shutdown_to_false(self):
        """reset() allows the manager to be re-used after shutdown."""
        rm = ResourceManager()
        rm.shutdown()
        assert rm.is_shutdown is True
        rm.reset()
        assert rm.is_shutdown is False


@pytest.mark.unit
class TestResourceManagerClearCaches:
    """Test clear_caches() method."""

    def test_clear_caches_does_not_raise_when_no_caches(self):
        """clear_caches() completes without error even if caches are absent."""
        rm = ResourceManager()
        # Patch out imports so we can test the method in isolation
        with patch("pyfiles.dependencies.resource_manager.gc") as mock_gc:
            rm.clear_caches()
            mock_gc.collect.assert_called_once()
