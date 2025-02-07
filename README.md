# Postgres Not an ORM

A simple library that helps you interact with Postgres databases 

* Write raw SQL queries
* Marshall queries into Pydantic models for type safety
* Manage sessions and transactions using simple context api
* Automatically create Open Telemetry spans for monitoring

## Basic Examples

```python
from pydantic import BaseModel

from pnorm import AsyncPostgresClient, PostgresCredentials

creds = PostgresCredentials(host="", port=5432, user="", password="", dbname="")
client = AsyncPostgresClient(creds)

class User(BaseModel):
    name: str
    age: int

# If we expect there to be exactly one "john"
john = await client.get(User, "select * from users where name = %(name)s", {"name": "john"})
# join: User or throw exception

# Get the first "mike" or return None
mike = await client.find(Users, "select * from users where name = %(name)s", {"name": "mike"})
# mike: User | None

# Get all results
adults = await client.select(User, "select * from users where age >= 18")
# adults: tuple[User, ...]

await client.execute("delete from users where age >= 18")
```

## Keep connection alive

```python
async with client.start_session(schema="admin") as session:
    # Connection end
    # > Set the search path to "admin"

    await session.execute("create table users (name varchar, age integer)")
    await session.execute(
        "insert into users (name, age) values (%(name)s, %(age)s),
        User(name="sally", age=20),
    )
    
    # Connection end
```

## Create a transaction

This example, retrieves a user from the users table, deletes the user, in python increments the user's age, then inserts the user back into the DB. Because this is in a transaction, the user will exist in the database with it's previous age (in case of a failure) or exist in the database with their new age.

```python
async with client.create_transaction() as transaction:
    # Transaction start

    await transaction.execute("delete from users where name = %(name)s", {"name": "mike"})
    person.age += 1
    await transaction.execute("insert into users (name, age) (%(name)s, %(age)s))", person)
   
    # Transaction end
```

Inspired by
* [sqlx](https://github.com/jmoiron/sqlx)
* [The Vietnam of Computer Science](https://odbms.org/wp-content/uploads/2013/11/031.01-Neward-The-Vietnam-of-Computer-Science-June-2006.pdf)
