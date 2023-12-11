import inspect
import os
import sys
from datetime import datetime
from glob import glob
from importlib import import_module
from pathlib import Path
from typing import Literal, Type, cast

import yaml
from pydantic import BaseModel

from pnorm.main import PostgresClient, PostgresCredentials, Session


class BaseUsers(BaseModel):
    username: str


class VersionChange(BaseModel):
    from_version: int | None
    to_version: int
    update_type: Literal["upgrade"] | Literal["downgrade"]
    updated_at: datetime
    description: str


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

    def upgrade(self, from_version: int | None):
        description = self.version_description

        if description is None:
            description = f"Upgrading from {from_version} to {self.version_number}"

        self.client.execute(
            "insert into version_log (from_version, to_version, description, update_type, updated_at) values (%(from_version)s, %(to_version)s, %(description)s, %(update_type)s, %(updated_at)s)",
            VersionChange(
                from_version=from_version,
                to_version=self.version_number,
                update_type="upgrade",
                updated_at=datetime.now(),
                description=description,
            ),
        )

    def downgrade(self, to_version: int):
        self.client.execute(
            "insert into version_log (from_version, to_version, description, update_type, updated_at) values (%(from_version)s, %(to_version)s, %(description)s, %(update_type)s, %(updated_at)s)",
            VersionChange(
                from_version=self.version_number,
                to_version=to_version,
                update_type="downgrade",
                updated_at=datetime.now(),
                description=f"Downgrading from {self.version_number} to {to_version}",
            ),
        )

    def run(self, current_version: VersionChange):
        if current_version.to_version > self.version_number:
            self.downgrade(current_version.to_version)
        elif current_version.to_version < self.version_number:
            self.upgrade(current_version.to_version)


class MigrationConfig(BaseModel):
    version: int
    description: str


class MigrationMetadata(BaseModel):
    path: Path
    config: MigrationConfig


class Exists(BaseModel):
    exists: bool


def base_migration(client: PostgresClient):
    exists_check = client.get(
        Exists,
        "select exists ("
        "  select from information_schema.tables"
        "  where table_name = 'version_log'"
        ")",
    )

    if exists_check is not None and exists_check.exists:
        return

    with client.transaction():
        client.execute(
            "create table version_log ("
            "  from_version integer null"
            "  , to_version integer null"
            "  , description varchar"
            "  , update_type varchar not null"
            "  , updated_at timestamp not null"
            ")"
        )

        timestamp = datetime.now()

        client.execute(
            "insert into version_log values ("
            "  null"
            "  , 0"
            "  , 'Create version table'"
            "  , 'upgrade'"
            f"  , '{timestamp}'"
            ")"
        )


def load_migration(migration: MigrationMetadata) -> Type[Migration]:
    # sys.path.append(str(file_path.parent.parent))
    sys.path.append(str(migration.path))
    module = import_module("migration")

    for cls in module.__dict__.values():
        if inspect.isclass(cls) and issubclass(cls, Migration) and cls != Migration:
            return cls


def main(folder_path: Path, credentials: PostgresCredentials):
    migrations: list[MigrationMetadata] = []

    with open(
        folder_path / "config.yaml",
        "r",
        encoding="utf-8",
    ) as file:
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

    with Session(PostgresClient(credentials)) as session:
        base_migration(session)

        current_version = session.get(
            VersionChange,
            "select * from version_log order by updated_at desc limit 1",
        )

        if current_version is None:
            raise Exception()

    if expected_version == current_version.to_version:
        return
    elif expected_version > current_version.to_version:
        versions_to_upgrade = [
            m
            for m in migrations
            if m.config.version > current_version.to_version
            and m.config.version <= expected_version
        ]
        versions_to_upgrade = sorted(
            versions_to_upgrade, key=lambda x: x.config.version
        )

        previous_version = current_version

        for version in versions_to_upgrade:
            migration = load_migration(version)
            migration(
                session, version.config.version, version.config.description
            ).upgrade(previous_version.to_version)
            previous_version = version
    elif expected_version < current_version.to_version:
        versions_to_upgrade = [
            m
            for m in migrations
            if m.config.version <= current_version.to_version
            and m.config.version >= expected_version
        ]
        versions_to_upgrade = sorted(
            versions_to_upgrade, key=lambda x: -x.config.version
        )

        for version, next_version in zip(
            versions_to_upgrade[:-1], versions_to_upgrade[1:]
        ):
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
