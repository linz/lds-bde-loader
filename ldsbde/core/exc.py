"""lds-bde-loader exception classes."""

class Error(Exception):
    """Generic errors."""
    def __init__(self, msg):
        super(Error, self).__init__()
        self.msg = msg

    def __str__(self):
        return "%s: %s" % (self.__class__.__name__, self.msg)


class ConfigError(Error):
    """Config related errors."""
    pass


class RuntimeError(Error):
    """Generic runtime errors."""
    pass


class ArgumentError(Error):
    """Argument related errors."""
    pass
