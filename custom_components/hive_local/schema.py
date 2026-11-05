"""Support HA's current validator and the previous voluptuous-based releases."""

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

__all__ = ["vol"]
