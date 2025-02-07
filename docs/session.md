# `SQLAlchemy` Session

## Lifecycle

[`SQLAlchemy` documentation](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#when-do-i-construct-a-session-when-do-i-commit-it-and-when-do-i-close-it)
recommends the following:

*  Keep the lifecycle of the session **separate and external** from functions and
    objects that access and/or manipulate database data.
*  Make sure you have a clear notion of where transactions begin and end, and keep
    transactions **short**, meaning, they end at the series of a sequence of operations,
    instead of being held open indefinitely.

`FastSQLA` automatically manages the session lifecycle:

* If the request is successful, the session is committed.
* If the request fails, the session is rolled back.
* In all cases, at the end of the request, the session is closed and the associated
  connection is returned to the connection pool.


To learn more about `SQLAlchemy` sessions:

* [Session Basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#)


## Session dependency

::: fastsqla.Session
    options:
        heading_level: false
        show_source: false

## Session context manager

::: fastsqla.open_session
    options:
        heading_level: false
        show_source: false
