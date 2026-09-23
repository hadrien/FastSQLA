import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, TypedDict
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException, Query
from fastapi.exceptions import RequestValidationError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    TypeAdapter,
    ValidationError,
    model_validator,
)
from sqlalchemy import Select
from sqlalchemy.dialects import mysql
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import Label, UnaryExpression
from sqlalchemy.sql.selectable import Join

import fastsqla

__all__ = ["Meta", "Page", "Paginate", "PaginateType", "new_pagination"]


class Meta(RootModel[dict[str, str | None]]):
    root: dict[str, str | None] = Field(
        min_length=1, max_length=1, description="One named cursor, or null at the end."
    )

    @property
    def next_cursor(self) -> str | None:
        return next(iter(self.root.values()))


class Page[T](fastsqla.Collection[T]):
    """Forward page with a continuation cursor or null at the end."""

    meta: Meta


type PaginateType[T] = Callable[[Select], Awaitable[Page[T]]]


class _NamedCursor(TypedDict):
    name: str
    value: str | None


class _NamedLimit(TypedDict):
    name: str
    value: int | None


class _Parameters(TypedDict):
    cursor: _NamedCursor
    limit: _NamedLimit


type _Value = int | str | UUID | datetime | date | Decimal


@dataclass(frozen=True)
class _OrderTerm:
    column: sa.Column
    descending: bool


type _Order = list[_OrderTerm]


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    v: int = Field(ge=1, le=1)
    order: list[tuple[str, str, bool, str]]
    values: list[int | str]


def _sources(stmt: Select) -> list[sa.FromClause]:
    if not isinstance(stmt, Select) or any(
        getattr(stmt, name) is not None
        for name in ("_limit_clause", "_offset_clause", "_fetch_clause")
    ):
        raise ValueError("Cursor pagination requires an unlimited Select")
    if stmt._distinct or stmt._group_by_clauses or stmt._having_criteria:
        raise ValueError("Cursor pagination does not support DISTINCT or aggregation")
    if any(
        not isinstance(col.element if isinstance(col, Label) else col, sa.Column)
        for col in stmt.selected_columns
    ):
        raise ValueError("Cursor pagination requires entity or column selections")
    sources = stmt.get_final_froms()
    if any(
        isinstance(node, Join) and (node.isouter or node.full)
        for source in sources
        for node in visitors.iterate(source)
    ):
        raise ValueError("Cursor pagination does not support outer joins")
    return sources


def _order(stmt: Select) -> _Order:
    sources = _sources(stmt)
    order = []
    for expression in stmt._order_by_clauses:
        descending = False
        if isinstance(expression, UnaryExpression) and expression.modifier in (
            operators.asc_op,
            operators.desc_op,
        ):
            descending = expression.modifier is operators.desc_op
            expression = expression.element
        if (
            not isinstance(expression, sa.Column)
            or not isinstance(expression.table, sa.Table)
            or expression.nullable
            or not any(source.is_derived_from(expression.table) for source in sources)
        ):
            raise ValueError("Cursor ordering requires non-null columns from the query")
        if not isinstance(
            expression.type,
            (sa.Integer, sa.String, sa.Uuid, sa.DateTime, sa.Date, sa.Numeric),
        ) or expression.type.python_type not in (int, str, UUID, datetime, date, Decimal):
            raise ValueError("Unsupported cursor column type")
        order.append(_OrderTerm(expression, descending))
    if not order:
        raise ValueError("Cursor pagination requires an explicit unique ordering")
    return order


def _schema(order: _Order) -> list[tuple[str, str, bool, str]]:
    return [
        (
            term.column.table.fullname,
            term.column.name,
            term.descending,
            term.column.type.python_type.__name__,
        )
        for term in order
    ]


def _encode(order: _Order, values: tuple[_Value, ...]) -> str:
    key_types = tuple(term.column.type.python_type for term in order)
    adapter = TypeAdapter(tuple[key_types])
    encoded = adapter.dump_python(adapter.validate_python(values, strict=True), mode="json")
    payload = _Payload(v=1, order=_schema(order), values=encoded)
    return base64.urlsafe_b64encode(payload.model_dump_json().encode()).decode().rstrip("=")


def _decode_payload(cursor: str) -> _Payload:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        return _Payload.model_validate_json(decoded)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error


def _integer_bounds(column_type: sa.Integer, dialect: str) -> tuple[int, int]:
    if dialect == "sqlite":
        return -(2**63), 2**63
    widths = (
        (mysql.TINYINT, 8),
        (mysql.MEDIUMINT, 24),
        (sa.SmallInteger, 16),
        (sa.BigInteger, 64),
    )
    bits = next((width for kind, width in widths if isinstance(column_type, kind)), 32)
    if getattr(column_type, "unsigned", False):
        return 0, 2**bits
    return -(2 ** (bits - 1)), 2 ** (bits - 1)


def _validate_value(column: sa.Column, value: _Value, dialect: str):
    if isinstance(value, int):
        lower, upper = _integer_bounds(column.type, dialect)
        if not lower <= value < upper:
            raise ValueError("Integer key out of range")
    if isinstance(value, Decimal) and (
        value.as_tuple().exponent < -16383
        or value.adjusted() >= (column.type.precision or 131072) - (column.type.scale or 0)
    ):
        raise ValueError("Decimal key out of range")
    if dialect != "postgresql":
        return
    if isinstance(value, str) and "\0" in value:
        raise ValueError("Text key contains NUL")
    if isinstance(value, datetime):
        aware = value.utcoffset() is not None
        if aware != column.type.timezone:
            raise ValueError("Datetime key timezone does not match the column")


def _decode(cursor: str, order: _Order, dialect: str) -> list[_Value]:
    payload = _decode_payload(cursor)
    if payload.order != _schema(order) or len(payload.values) != len(order):
        raise HTTPException(status_code=422, detail="Invalid cursor")
    values = []
    for term, value in zip(order, payload.values, strict=True):
        value_type = term.column.type.python_type
        encoded_type = int if value_type is int else str
        if type(value) is not encoded_type:
            raise HTTPException(status_code=422, detail="Invalid cursor")
        try:
            parsed = TypeAdapter(value_type).validate_json(json.dumps(value), strict=True)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail="Invalid cursor") from error
        try:
            _validate_value(term.column, parsed, dialect)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Invalid cursor") from error
        values.append(parsed)
    return values


def _condition(
    order: _Order, values: list[_Value], dialect: str
) -> sa.ColumnElement[bool]:
    first = order[0]
    same_direction = all(term.descending == first.descending for term in order)
    if same_direction and dialect in ("postgresql", "sqlite", "mysql"):
        keys = sa.tuple_(*(term.column for term in order))
        return keys < tuple(values) if first.descending else keys > tuple(values)
    terms, prefix = [], []
    for term, value in zip(order, values, strict=True):
        column = term.column
        comparison = column < value if term.descending else column > value
        terms.append(sa.and_(*prefix, comparison))
        prefix.append(column == value)
    bound = first.column <= values[0] if first.descending else first.column >= values[0]
    return sa.and_(bound, sa.or_(*terms))


def new_pagination[T](
    default_page_size: int = 10,
    max_page_size: int = 100,
    *,
    parameters_dependency: Callable[..., _Parameters | Awaitable[_Parameters]] | None = None,
    row_mapper: Callable[[sa.Row], T] = lambda row: row[0],
) -> Any:
    """Create a generic pagination dependency: `Paginate = new_pagination(...)`.

    Annotate the endpoint argument as `Paginate[T]`. Pagination fields come from
    query parameters unless a custom extraction dependency is supplied.

    Args:
        default_page_size: Default limit when the client omits it.
        max_page_size: Maximum accepted limit.
        parameters_dependency: Sync or async FastAPI dependency returning named
            cursor and limit values. A `None` limit uses `default_page_size`.
        row_mapper: Maps each original result row to exactly one response item.

    Returns:
        Generic annotated dependency with a one-row-to-one-item mapper.

    Raises:
        ValueError: Page-size bounds or the supplied Select are unsupported.
    """
    if (
        type(default_page_size) is not int
        or type(max_page_size) is not int
        or not 1 <= default_page_size <= max_page_size
    ):
        raise ValueError("Require 1 <= default_page_size <= max_page_size")
    class CursorParameter(BaseModel):
        model_config = ConfigDict(strict=True)

        name: str = Field(min_length=1)
        value: str | None = Field(None, min_length=1)

    class LimitParameter(BaseModel):
        model_config = ConfigDict(strict=True)

        name: str = Field(min_length=1)
        value: int | None = Field(None, ge=1, le=max_page_size)

    class Parameters(BaseModel):
        model_config = ConfigDict(strict=True)

        cursor: CursorParameter
        limit: LimitParameter

        @model_validator(mode="after")
        def distinct_names(self):
            names = (self.cursor.name, self.limit.name)
            if any(name != name.strip() for name in names):
                raise ValueError("Parameter names cannot have surrounding whitespace")
            if self.cursor.name == self.limit.name:
                raise ValueError("Cursor and limit parameter names must differ")
            return self

    async def query_parameters(
        cursor: str | None = Query(None, min_length=1, alias="next_cursor"),
        limit: int = Query(default_page_size, ge=1, le=max_page_size),
    ) -> _Parameters:
        return {
            "cursor": {"name": "next_cursor", "value": cursor},
            "limit": {"name": "limit", "value": limit},
        }

    if parameters_dependency is None:
        parameters_dependency = query_parameters

    async def dependency(
        session: fastsqla.Session,
        parameters: Annotated[_Parameters, fastsqla.Depends(parameters_dependency)],
    ) -> PaginateType[T]:
        try:
            validated = Parameters.model_validate(parameters)
        except ValidationError as error:
            raise RequestValidationError(
                error.errors(include_url=False, include_input=False)
            ) from error
        cursor_name = validated.cursor.name
        cursor = validated.cursor.value
        limit = validated.limit.value or default_page_size

        async def paginate(stmt: Select) -> Page[T]:
            order = _order(stmt)
            dialect = session.get_bind(clause=stmt).dialect.name
            if dialect == "sqlite" and any(
                term.column.type.python_type is Decimal for term in order
            ):
                raise ValueError("SQLite decimal ordering cannot preserve cursor precision")
            columns = [term.column for term in order]
            if cursor is not None:
                values = _decode(cursor, order, dialect)
                stmt = stmt.where(_condition(order, values, dialect))
            stmt = stmt.add_columns(*(col.label(None) for col in columns)).limit(limit + 1)
            result = await session.execute(stmt)
            width = len(result.keys()) - len(columns)
            frozen = result.freeze()
            rows = frozen().all()
            next_cursor = None
            if len(rows) > limit:
                boundary = rows[limit - 1]
                cursor_values = boundary[-len(columns) :]
                next_cursor = _encode(order, cursor_values)
            original = frozen().columns(*range(width)).all()
            data = [row_mapper(row) for row in original[:limit]]
            return Page(data=data, meta=Meta({cursor_name: next_cursor}))

        return paginate

    return Annotated[PaginateType[T], fastsqla.Depends(dependency)]


Paginate = new_pagination()
"""Inject a forward paginator accepting next_cursor and limit query parameters."""
