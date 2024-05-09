# (Postgres) Not an ORM

This library helps you interact with a Postgres database in Python, by writing raw SQL. 

https://www.odbms.org/wp-content/uploads/2013/11/031.01-Neward-The-Vietnam-of-Computer-Science-June-2006.pdf
https://blog.codinghorror.com/object-relational-mapping-is-the-vietnam-of-computer-science/
https://news.ycombinator.com/item?id=7310077

## Basic Examples

```python
from pydantic import BaseModel

from pnorm import PostgresClient, PostgresCredentials

creds = PostgresCredentials(host="", port=5432, user="", password="", dbname="")

client = PostgresClient(creds)

class User(BaseModel):
    name: str
    age: int

# If we *know* there is exactly one "john"
john: User = client.get(User, "select * from users where name = %(name)s", {"name": "john"})

# Get the first "mike" or return None
mike: User | None = client.find(Users, "select * from users where name = %(name)s, {"name": "mike"})

# Get all results
adults: list[User] = client.select(User, "select * from users where age >= 18")

# delete adults
client.execute("delete from users where age >= 18")

# insert into table
client.execute_values(
    "insert into users (name, age) values (%(name)s, %(age)s),
    [
        User(name="sally", age=20),
        User(name="daniel", age=21)
    ]
)
```

## Keep connection alive

```python
with client.start_session(schema="admin") as session:
    # Connection end
    # > Set the default schema to "admin"

    session.execute("create table users (name varchar, age integer)")
    client.execute_values(
    "insert into users (name, age) values (%(name)s, %(age)s),
        [
            User(name="sally", age=20),
            User(name="daniel", age=21)
        ]
    )
    
    # Connection end
```

## Create a transaction

This example, retrieves a user from the users table, deletes the user, in python increments the user's age, then inserts the user back into the DB. Because this is in a transaction, the user will exist in the database with it's previous age (in case of a failure) or exist in the database with their new age.

```python
person = transaction.get(User, "select * from users where name = %(name)s", {"name": "mike"})

with client.create_transaction() as transaction:
    # Transaction start

    transaction.execute("delete from users where name = %(name)s", {"name": "mike"})
    person.age += 1
    transaction.execute("insert into users (name, age) (%(name)s, %(age)s))", person)
   
    # Transaction end
```

Of course you could do this all in SQL with an update statement.


Inspired by
https://github.com/jmoiron/sqlx


https://github.com/dagster-io/dagster/blob/master/python_modules/libraries/dagster-aws/dagster_aws/redshift/resources.py
https://github.com/jmoiron/sqlx
https://jmoiron.github.io/sqlx/
