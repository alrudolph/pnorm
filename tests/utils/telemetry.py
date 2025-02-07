import json
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

trace_provider = TracerProvider()
trace.set_tracer_provider(trace_provider)


def test_dict_is_subset(test_dict: dict[str, Any], subset_dict: dict[str, Any]) -> bool:
    for key, value in subset_dict.items():
        test_value = test_dict.get(key)

        if test_value is None:
            print("Key not found", key, value)
            return False

        if isinstance(value, dict) and isinstance(test_value, dict):
            if not test_dict_is_subset(test_value, value):
                print("Dict not subset", key)
                return False
        elif test_value != value:
            print("Value not equal", key, test_value, value)
            return False

    return True


@contextmanager
def assert_span(expected_span: dict[str, Any]):
    span_exporter = InMemorySpanExporter()
    span_processor = SimpleSpanProcessor(span_exporter)
    trace_provider.add_span_processor(span_processor)

    yield

    exported = span_exporter.get_finished_spans()

    assert len(exported) == 1
    print(exported[0].to_json())
    assert test_dict_is_subset(json.loads(exported[0].to_json()), expected_span)
