from typing import Never


class NoRecordsReturnedException(Exception):
    """Expected to return at least one record but query did not"""


class MultipleRecordsReturnedException(Exception):
    """Expected to return at most one record but query returned multiple"""


class ConnectionAlreadyEstablishedException(Exception):
    """Trying to create a connection when one is already established. This should typically not occur"""


class ConnectionNotEstablishedException(Exception):
    """Trying to execute a query before creating an exception. Check that auto connections are turned on or you are inside a session"""


def connection_not_created() -> Never:
    """This could be from not using a session"""
    raise ConnectionNotEstablishedException()


class MarshallRecordException(Exception):
    """The returned record does not match the model you are trying to marshall it into"""
