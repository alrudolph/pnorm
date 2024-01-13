from typing import Never


class NoRecordsReturnedException(Exception):
    ...


class MultipleRecordsReturnedException(Exception):
    ...


class ConnectionAlreadyEstablishedException(Exception):
    ...


class ConnectionNotEstablishedException(Exception):
    ...


def connection_not_created() -> Never:
    """This could be from not using a session"""
    raise ConnectionNotEstablishedException()


class MarshallRecordException(Exception):
    ...
