from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator

import uvicorn
from fastapi import Depends, FastAPI, Response
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from pnorm import AsyncPostgresClient, PostgresCredentials, QueryContext
from pnorm.hooks.opentelemetry import (
    RequestsCounterHook,
    RequestsFailureHook,
    RequestsSuccessHook,
    RequestsTimingHook,
    SpanHook,
)

db_client = AsyncPostgresClient(
    PostgresCredentials(
        host="host.docker.internal",
        port=5436,
        user="postgres",
        password="postgres",
        dbname="postgres",
    ),
    hooks=[],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with db_client.start_session() as db:
        await db.execute("create table if not exists test (a int, name text);")
        await db.execute("insert into test values (1, 'test-1');")

    yield


app = FastAPI(lifespan=lifespan)


reader = PrometheusMetricReader()
meter_provider = MeterProvider(metric_readers=[reader])
set_meter_provider(meter_provider)


FastAPIInstrumentor.instrument_app(app)


async def client() -> AsyncGenerator[AsyncPostgresClient, None]:
    async with db_client.start_session() as session:
        yield session


ClientDep = Annotated[AsyncPostgresClient, Depends(client)]


@app.get("/")
async def read_root(db: ClientDep) -> dict[str, dict[str, Any]]:
    res = await db.find(
        dict,
        "select * from test where a = %(a)s;",
        {"a": 1},
        query_context=QueryContext(
            primary_table_name="test",
            operation_name="select",
            query_summary="select from test",
        ),
        hooks=[
            SpanHook(),
            RequestsCounterHook(),
            RequestsTimingHook(),
            RequestsSuccessHook(),
            RequestsFailureHook(),
        ],
    )
    return {"message": res}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
