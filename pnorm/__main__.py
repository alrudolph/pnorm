import os
from glob import glob
from importlib import import_module
from pathlib import Path
from typing import Any, Sequence, Type

import click

from pnorm import linter, migrations
from pnorm.linter import PostgresCredentials


@click.group()
def cli():
    ...


@cli.command()
@click.option("--path", default=".", help="Path to file or directory")
def lint(path: str) -> None:
    raise NotImplementedError("linting is not currently enabled")
    expanded_path = os.path.expanduser(path)
    abs_path = os.path.abspath(expanded_path)
    linter.main(Path(abs_path))


@cli.command()
@click.option("--path", default=".", help="Path to file or directory")
@click.option("--host")
@click.option("--dbname", default=None)
@click.option("--database", default=None)
@click.option("--port", type=int)
@click.option("--user")
@click.option("--password")
def migrate(
    path: str,
    dbname: str | None,
    database: str | None,
    host: str,
    port: int,
    user: str,
    password: str,
):
    credentials = PostgresCredentials(
        dbname=dbname or database or "postgres",
        host=host,
        port=port,
        user=user,
        password=password,
    )

    migrations.main(Path(path), credentials)


if __name__ == "__main__":
    cli()
