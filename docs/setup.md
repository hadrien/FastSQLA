# Setup

## `fastsqla.lifespan`

::: fastsqla.lifespan
    options:
        heading_level: false
        show_source: false

## Configuration

Configuration is done exclusively via environment variables, adhering to the
[**Twelve-Factor App methodology**](https://12factor.net/config).

The only required key is **`SQLALCHEMY_URL`**, which defines the database URL. It
specifies the database driver in the URL's scheme and allows embedding driver parameters
in the query string. Example:

    sqlite+aiosqlite:////tmp/test.db?check_same_thread=false

All parameters of [`sqlalchemy.create_engine`][] can be configured by setting environment
variables, with each parameter name prefixed by **`SQLALCHEMY_`**.

!!! note

    FastSQLA is **case-insensitive** when reading environment variables, so parameter
    names prefixed with **`SQLALCHEMY_`** can be provided in any letter case.

### Examples

1.  :simple-postgresql: PostgreSQL url using
    [`asyncpg`][sqlalchemy.dialects.postgresql.asyncpg] driver with a
    [`pool_recycle`][sqlalchemy.create_engine.params.pool_recycle] of 30 minutes:

    ```bash
    export SQLALCHEMY_URL=postgresql+asyncpg://postgres@localhost/postgres
    export SQLALCHEMY_POOL_RECYCLE=1800
    ```

2.  :simple-sqlite: SQLite db file using
    [`aiosqlite`][sqlalchemy.dialects.sqlite.aiosqlite] driver with a
    [`pool_size`][sqlalchemy.create_engine.params.pool_size] of 50:

    ```bash
    export sqlalchemy_url=sqlite+aiosqlite:///tmp/test.db?check_same_thread=false
    export sqlalchemy_pool_size=10
    ```

3.  :simple-mariadb: MariaDB url using [`aiomysql`][sqlalchemy.dialects.mysql.aiomysql]
    driver with [`echo`][sqlalchemy.create_engine.params.echo] parameter set to `True`

    ```bash
    export sqlalchemy_url=mysql+aiomysql://bob:password!@db.example.com/app
    export sqlalchemy_echo=true
    ```
