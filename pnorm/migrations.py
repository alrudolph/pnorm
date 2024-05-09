import inspect
import os
import sys
from datetime import datetime
from glob import glob
from importlib import import_module, reload
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from pnorm import PostgresClient, PostgresCredentials

from .model import Model, PnormConfig


class BaseUsers(BaseModel):
    username: str


class VersionChange(Model):
    pnorm_config: PnormConfig = PnormConfig(
        table_name="version_log",
        id_column="to_version",
    )

    from_version: int | None
    to_version: int
    update_type: Literal["upgrade", "downgrade"]
    updated_at: datetime
    description: str


class MigrationConfig(BaseModel):
    version: int
    description: str


class MigrationMetadata(BaseModel):
    path: Path
    config: MigrationConfig


class Exists(BaseModel):
    exists: bool


class VersionLogTable:

    def __init__(self, client: PostgresClient):
        self.client = client

    def handle_base_migration(self) -> None:
        if not self.table_exists:
            self.create_table()

    def get_current_version(self) -> VersionChange | None:
        return self.client.find(
            VersionChange,
            "select * from version_log order by updated_at desc limit 1",
        )

    @property
    def table_exists(self) -> bool:
        exists_check = self.client.find(
            Exists,
            "select exists ("
            "  select from information_schema.tables"
            "  where table_name = 'version_log'"
            ")",
        )

        return exists_check is not None and exists_check.exists

    def create_table(self) -> None:
        with self.client.start_transaction() as transaction:
            transaction.execute(
                "create table version_log ("
                "  from_version integer null"
                "  , to_version integer null"
                "  , description varchar"
                "  , update_type varchar not null"
                "  , updated_at timestamp not null"
                ")"
            )

            timestamp = datetime.now()

            vc = VersionChange(
                from_version=None,
                to_version=0,
                update_type="upgrade",
                updated_at=timestamp,
                description="Create version table",
            )

            vc.insert(self.client)


class Migration:
    def __init__(
        self,
        client: PostgresClient,
        version_number: int,
        version_description: str | None = None,
    ):
        self.client = client
        self.version_number = version_number
        self.version_description = version_description
        self.version_log_table = VersionLogTable(client)

    def upgrade(self, from_version: int | None) -> None:
        description = self.version_description

        if description is None:
            description = f"Upgrading from {from_version} to {self.version_number}"

        vc = VersionChange(
            from_version=from_version,
            to_version=self.version_number,
            update_type="upgrade",
            updated_at=datetime.now(),
            description=description,
        )

        vc.insert(self.client)

    def downgrade(self, to_version: int) -> None:
        vc = VersionChange(
            from_version=self.version_number,
            to_version=to_version,
            update_type="downgrade",
            updated_at=datetime.now(),
            description=f"Downgrading from {self.version_number} to {to_version}",
        )

        vc.insert(self.client)

    def run(self, current_version: VersionChange) -> None:
        if current_version.to_version > self.version_number:
            self.downgrade(current_version.to_version)
        elif current_version.to_version < self.version_number:
            self.upgrade(current_version.to_version)


def load_migration(migration: MigrationMetadata) -> type[Migration]:
    # sys.path.append(str(file_path.parent.parent))
    old_path = sys.path

    sys.path = [str(migration.path)]

    module = import_module("migration", migration.path.name)
    module = reload(module)
    classes = module.__dict__.values()

    output = None

    for cls in classes:
        if inspect.isclass(cls) and issubclass(cls, Migration) and cls != Migration:
            print("LOADING MODULE", cls.__name__, "FROM", migration.path)
            # sys.path.pop()
            # sys.path = old_path
            # return cls

            output = cls

    if output is not None:
        return output

    sys.path = old_path
    raise Exception()


def upgrade(
    session: PostgresClient,
    migrations: list[MigrationMetadata],
    previous_version: int,
    expected_version: int,
):
    versions_to_upgrade = [
        m for m in migrations if previous_version < m.config.version <= expected_version
    ]
    versions_to_upgrade = sorted(versions_to_upgrade, key=lambda x: x.config.version)

    print("VERSIONS TO UPGRADE", versions_to_upgrade)

    for version in versions_to_upgrade:
        print("from ", previous_version, "to ", version.config.version)
        migration = load_migration(version)
        migration(session, version.config.version, version.config.description).upgrade(
            previous_version
        )
        previous_version = version.config.version


def downgrade(
    session: PostgresClient,
    migrations: list[MigrationMetadata],
    previous_version: int,
    expected_version: int,
):
    versions_to_upgrade = [
        m
        for m in migrations
        if expected_version <= m.config.version <= previous_version
    ]
    versions_to_upgrade = sorted(versions_to_upgrade, key=lambda x: -x.config.version)
    print("------")
    print(versions_to_upgrade)

    for version, next_version in zip(versions_to_upgrade[:-1], versions_to_upgrade[1:]):
        migration = load_migration(version)
        migration(
            session, version.config.version, version.config.description
        ).downgrade(next_version.config.version)

    if expected_version == 0:
        version = versions_to_upgrade[-1]
        migration = load_migration(version)
        migration(
            session, version.config.version, version.config.description
        ).downgrade(0)


def main(folder_path: Path, credentials: PostgresCredentials):
    migrations: list[MigrationMetadata] = []

    with open(folder_path / "config.yaml", "r", encoding="utf-8") as file:
        file_contents = yaml.safe_load(file)

    expected_version = file_contents["version"]

    for migration_path in glob("*", root_dir=folder_path):
        if not os.path.isdir(folder_path / migration_path):
            continue

        with open(
            folder_path / migration_path / "migration.yaml",
            "r",
            encoding="utf-8",
        ) as file:
            file_contents = yaml.safe_load(file)

        migrations.append(
            MigrationMetadata(
                path=folder_path / migration_path,
                config=MigrationConfig(**file_contents),
            )
        )

    client = PostgresClient(credentials)
    with client.start_session() as session:
        version_log_table = VersionLogTable(session)
        version_log_table.handle_base_migration()

        current_version = version_log_table.get_current_version()

        if current_version is None:
            raise Exception()

    print("CURRENT VERSION", current_version, "\n\n------------")
    previous_version = current_version.to_version

    if expected_version > previous_version:
        upgrade(session, migrations, previous_version, expected_version)
    elif expected_version < previous_version:
        downgrade(session, migrations, previous_version, expected_version)
