from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional

from typing_extensions import override

from pnorm.pnorm_types import QueryContext

from .base import BaseHook

if TYPE_CHECKING:
    from opentelemetry.trace import Span, Tracer

# TODO: try to import -> failure message


def _get_attributes(
    query: str,
    query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
    query_context: Optional[QueryContext] = None,
) -> dict[str, Any]:
    #
    # TODO: ADD REQUEST TIME ??
    #

    attributes: dict[str, Any] = {
        "db.system.name": "postgresql",
        "db.query.text": query,
        # "server.address": "",
        # "server.port": "",
        # "network.peer.address": "",
        # "network.peer.port": "",
    }

    # TODO: schema

    if query_context is not None:
        if query_context.primary_table_name is not None:
            attributes["db.collection.name"] = query_context.primary_table_name

        if query_context.operation_name is not None:
            attributes["db.operation.name"] = query_context.operation_name

        if query_context.query_summary is not None:
            attributes["db.query.summary"] = query_context.query_summary

    if query_params is None:
        return attributes

    if isinstance(query_params, Mapping):
        for key, value in query_params.items():
            # TODO: secret values?
            # either have pydantic models with SecretStr
            # or in context have a list of values to replace with **
            if isinstance(value, str | bytes | int | float | bool):
                attributes[f"db.operation.parameter.{key}"] = value
            else:
                attributes[f"db.operation.parameter.{key}"] = str(value)

        return attributes

    # TODO: this could be bad for inserting data... maybe have a way to turn off in execute
    # or have a way to specify only certain parameters are being included
    for i, params in enumerate(query_params):
        for key, value in params.items():
            # TODO: secret values?
            # either have pydantic models with SecretStr
            # or in context have a list of values to replace with **
            if isinstance(value, str | bytes | int | float | bool):
                attributes[f"db.operation.parameter.{i}.{key}"] = value
            else:
                attributes[f"db.operation.parameter.{i}.{key}"] = str(value)

    return attributes


def _get_result_attributes(
    rows_returned: int,
    batch_size: int = 1,
) -> dict[str, Any]:
    return {
        "db.response.returned_rows": rows_returned,
        "db.operation.batch.size": batch_size,
    }


class RequestsTimingHook(BaseHook):
    def __init__(self) -> None:
        from opentelemetry.metrics import get_meter_provider

        self.meter = get_meter_provider().get_meter("pnorm")
        self.counter = self.meter.create_histogram(
            name="database_requests_duration",
            description="Duration of database requests",
        )
        self.start_time: datetime | None = None
        self.attributes: dict[str, Any] = {}

    @override
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        self.start_time = datetime.now()
        self.attributes = _get_attributes(query, query_params, query_context)

    @override
    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None:
        assert self.start_time is not None, "start_time should not be None"

        self.attributes.update(_get_result_attributes(rows_returned, batch_size))

        self.counter.record(
            (datetime.now() - self.start_time).total_seconds(),
            self.attributes,
        )


class RequestsCounterHook(BaseHook):
    def __init__(self) -> None:
        from opentelemetry.metrics import get_meter_provider

        self.meter = get_meter_provider().get_meter("pnorm")
        self.counter = self.meter.create_counter(
            name="database_requests_total",
            description="Total number of database requests",
        )
        self.attributes: dict[str, Any] = {}

    @override
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        self.attributes = _get_attributes(query, query_params, query_context)

    @override
    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None:
        self.attributes.update(_get_result_attributes(rows_returned, batch_size))

        self.counter.add(1, self.attributes)


class RequestsSuccessHook(BaseHook):
    def __init__(self) -> None:
        from opentelemetry.metrics import get_meter_provider

        self.meter = get_meter_provider().get_meter("pnorm")
        self.counter = self.meter.create_counter(
            name="database_requests_success",
            description="Total number of successful database requests",
        )
        self.attributes: dict[str, Any] = {}

    @override
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        self.attributes = _get_attributes(query, query_params, query_context)

    @override
    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None:
        if result_type != "success":
            return

        self.attributes.update(_get_result_attributes(rows_returned, batch_size))

        self.counter.add(1, self.attributes)


class RequestsFailureHook(BaseHook):
    def __init__(self) -> None:
        from opentelemetry.metrics import get_meter_provider

        self.meter = get_meter_provider().get_meter("pnorm")
        self.counter = self.meter.create_counter(
            name="database_requests_failure",
            description="Total number of failed database requests",
        )
        self.attributes: dict[str, Any] = {}

    @override
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        self.attributes = _get_attributes(query, query_params, query_context)

    @override
    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None:
        if result_type != "failure":
            return

        self.attributes.update(_get_result_attributes(rows_returned, batch_size))

        self.counter.add(1, self.attributes)

    @override
    def on_exception(self, exception: Exception):
        # TODO:
        ...


class SpanHook(BaseHook):
    def __init__(self) -> None:
        from opentelemetry import trace

        self.span: Span | None = None
        self.tracer = trace.get_tracer("pnorm.async_client")

    @override
    def pre_query(
        self,
        query: str,
        query_params: Optional[dict[str, Any] | Sequence[dict[str, Any]]] = None,
        query_context: Optional[QueryContext] = None,
    ) -> None:
        self.span = self.tracer.start_span(query)
        attributes = _get_attributes(query, query_params, query_context)
        self._set_span_attributes(attributes)

    @override
    def post_query(
        self,
        result_type: Literal["success", "error"],
        rows_returned: int,
        batch_size: int = 1,
    ) -> None:
        assert self.span is not None, "span should not be None"

        attributes = _get_result_attributes(rows_returned, batch_size)
        self._set_span_attributes(attributes)
        self.span.end()

    @override
    def on_exception(self, exception: Exception):
        assert self.span is not None, "span should not be None"

        self.span.set_attribute("error.type", "timeout")
        # except psycopg.OperationalError as e:
        #     # https://www.psycopg.org/docs/errors.html
        #     span.record_exception(e)
        #     span.set_attribute("db.response.status_code", str(e.pgcode))
        self.span.record_exception(exception)
        self.span.end()

    def _set_span_attributes(self, attributes: dict[str, Any]) -> None:
        assert self.span is not None, "span should not be None"

        for key, value in attributes.items():
            self.span.set_attribute(key, value)
