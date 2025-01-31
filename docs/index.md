# FastSQLA

[![PyPI - Version](https://img.shields.io/pypi/v/FastSQLA?color=brightgreen)](https://pypi.org/project/FastSQLA/)
[![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/hadrien/fastsqla/ci.yml?branch=main&logo=github&label=CI)](https://github.com/hadrien/FastSQLA/actions?query=branch%3Amain+event%3Apush)
[![Codecov](https://img.shields.io/codecov/c/github/hadrien/fastsqla?token=XK3YT60MWK&logo=codecov)](https://codecov.io/gh/hadrien/FastSQLA)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-brightgreen.svg)](https://conventionalcommits.org)
[![GitHub License](https://img.shields.io/github/license/hadrien/fastsqla)](https://github.com/hadrien/FastSQLA/blob/main/LICENSE)

`FastSQLA` is an [`SQLAlchemy 2`](https://docs.sqlalchemy.org/en/20/) extension for
[`FastAPI`](https://fastapi.tiangolo.com/).

It streamlines the configuration and asynchronous connection to relational databases by
providing boilerplate and intuitive helpers. Additionally, it offers built-in
customizable pagination and automatically manages the `SQLAlchemy` session lifecycle
following [`SQLAlchemy`'s best practices](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#when-do-i-construct-a-session-when-do-i-commit-it-and-when-do-i-close-it).

## Installing

As advised on [`FastAPI` documentation](https://fastapi.tiangolo.com/virtual-environments/),
create and activate a virtual environment and then install `FastSQLA`.

Using [`uv`](https://docs.astral.sh/uv):

```bash
uv add fastsqla
```

Using [pip](https://pip.pypa.io/en/stable/):

```bash
pip install fastsqla
```

## Setup

### `fastsqla.lifespan`

::: fastsqla.lifespan
    options:
        heading_level: false
        show_source: false

### Get an async SQLAlchemy session


