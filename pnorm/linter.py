import ast
import sys
from glob import glob
from importlib import import_module
from pathlib import Path
from typing import Any, Sequence, Type, cast

from pydantic import BaseModel

from pnorm import PostgresClient, PostgresCredentials, Session
from pnorm.main import Session

creds = PostgresCredentials(
    user="postgres",
    password="postgres",
    host="localhost",
    port=5436,
)

client = PostgresClient(creds)


def get_all_files_in_path(path: Path) -> Sequence[Path]:
    if path.is_dir():
        return tuple(path / p for p in glob("*.py", root_dir=str(path), recursive=True))

    return tuple([path])


class GetStatement(BaseModel):
    statement: str = "get"
    sql_statement: str
    return_model: Type[BaseModel]


class SelectStatement(BaseModel):
    statement: str = "select"
    sql_statement: str
    return_model: Type[BaseModel]


class ExecuteStatement(BaseModel):
    statement: str = "execute"
    sql_statement: str


Statement = GetStatement | SelectStatement | ExecuteStatement


def parse_statements(file_path: Path, file_contents: str) -> list[Statement]:
    tree = ast.parse(file_contents)

    statements: list[Statement] = []

    sys.path.append(str(file_path.parent.parent))
    module = import_module("test_mod.test")

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

        # print(ast.dump(node))

        # print(file_path)

        match node:
            case ast.Call(
                func=ast.Attribute(attr="get"),
                args=function_args,
            ):
                (return_model, sql_statement, *_) = function_args

                if not isinstance(sql_statement, ast.Constant) or not isinstance(
                    sql_statement.value, str
                ):
                    print("RAISE EXCEPTION, MUST BE HARDCODED STRING")

                statements.append(
                    GetStatement(
                        return_model=getattr(module, return_model.id),
                        sql_statement=sql_statement.value,
                    )
                )

            case ast.Call(
                func=ast.Attribute(attr="select"),
                args=function_args,
            ):
                (return_model, sql_statement, *_) = function_args

                statements.append(SelectStatement(sql_statement=sql_statement.value))

            case ast.Call(
                func=ast.Attribute(attr="execute"),
                args=function_args,
            ):
                (sql_statement, *_) = function_args

                statements.append(
                    ExecuteStatement(
                        return_model=return_model.id,
                        sql_statement=sql_statement.value,
                    )
                )

    return statements


def get_params(sql: str, session: PostgresClient):
    return {"username": "alex"}


class Result(BaseModel):
    statement: Statement
    success: bool
    value: BaseModel | None = None
    exception: Any | None = None
    example_params: dict[str, str] | None = None


def execute_statements(
    statements: Sequence[Statement], session: PostgresClient
) -> list[Result]:
    results: list[Result] = []

    for statement in statements:
        match statement:
            case GetStatement(
                statement="get",
                return_model=return_model,
                sql_statement=sql_statement,
            ):
                params = get_params(sql_statement, session)
                try:
                    value = session.get(
                        return_model,
                        sql_statement,
                        params,
                    )
                    results.append(
                        Result(
                            statement=statement,
                            value=value,
                            success=True,
                            example_params=params,
                        )
                    )
                except Exception as e:
                    results.append(
                        Result(
                            statement=statement,
                            success=False,
                            exception=e,
                            example_params=params,
                        )
                    )

            case SelectStatement(
                statement="select",
                return_model=return_model,
                sql_statement=sql_statement,
            ):
                params = get_params(sql_statement, session)
                session.select(return_model, sql_statement, params)

            case ExecuteStatement(
                statement="execute",
                sql_statement=sql_statement,
            ):
                params = get_params(sql_statement, session)
                session.execute(sql_statement, params)

            case _:
                raise Exception(statement)

    return results


def lint_file(path: Path, session: PostgresClient) -> None:
    with open(path, "r", encoding="utf-8") as file:
        script = file.read()

    if script.strip() == "":
        return

    statements = parse_statements(path, script)

    results = execute_statements(statements, session)
    print(results)


def main(path: Path) -> None:
    all_files = get_all_files_in_path(path)

    with Session(client) as session:
        for file in all_files:
            lint_file(file, session)
