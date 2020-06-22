class RemoteError(Exception):
    """A base class for all remote's custom exception"""


class RemoteConnectionError(RemoteError):
    """Remote wasn't able to connect to remote host"""


class RemoteExecutionError(RemoteError):
    """A command executed remotely exited with non-zero status"""


class ConfigurationError(RemoteError):
    """The workspace configuration is incorrect"""


class InvalidInputError(RemoteError):
    """Invalid user input is passed from the cli"""


class InvalidRemoteHostLabel(RemoteError):
    """Invalid label is passed to the workspace."""
