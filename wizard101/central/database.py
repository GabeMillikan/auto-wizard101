"""
This file defines all of the database structures that are used in the wizard101.central module.
It also includes a couple utilities that make it easier to query the database without using raw SQL.
(i.e. `WearableItem.where(category='robes')`)

I slowly added features to this file and eventually ended up with a copy of SQLAlchemy
but I am now too lazy to refactor it to _actually_ use SQLAlchemy. Oh well.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import re
from typing import (
    Type,
    Any,
    ClassVar,
    get_origin,
    get_args,
    get_type_hints,
    Union,
    TypeVar,
    Generator,
    Iterable,
)
from types import UnionType

from .. import util
from .constants import *


@dataclass
class DatabaseColumns:
    @dataclass(frozen=True)
    class Column:
        name: str
        python_type: type
        database_type: str
        nullable: bool

        def with_prefix(self, name: str) -> "DatabaseColumns.Column":
            return DatabaseColumns.Column(
                name=f"{name}_{self.name}",
                python_type=self.python_type,
                database_type=self.database_type,
                nullable=self.nullable,
            )

        @staticmethod
        def extract_optional(annotation: Type[Any]) -> tuple[Type[Any], bool]:
            origin, args = get_origin(annotation), list(get_args(annotation))

            # this handles both `Union[int, None]` and `int | None`
            # note that `Optional[int]` is an alias for `Union[int, None]`
            if origin is Union or origin is UnionType:
                nullable = type(None) in args
                while type(None) in args:
                    args.remove(type(None))

                if not args:
                    return type(None), nullable

                resulting_type = args.pop()
                while args:
                    resulting_type |= args.pop()

                return resulting_type, nullable

            return annotation, False

        @classmethod
        def get_database_type(cls, python_type: Type[Any]) -> str | None:
            t, optional = cls.extract_optional(python_type)

            database_types: dict[type, str] = {int: "INTEGER", float: "REAL", str: "TEXT"}
            return database_types.get(t)

        @classmethod
        def get_nullability(cls, python_type: Type[Any]) -> bool:
            t, optional = cls.extract_optional(python_type)
            return optional

    direct: list[Column] = field(default_factory=list)
    references: dict[str, Type["DatabasePersistable"]] = field(default_factory=dict)

    all: list[Column] = field(default_factory=list)

    def add(self, name: str, python_type: Type[Any]) -> None:
        if (
            isinstance(python_type, type)
            and issubclass(python_type, DatabasePersistable)
            and python_type is not DatabasePersistable
        ):
            self.references[name] = python_type
            for col in python_type._columns.all:
                self.all.append(col.with_prefix(name))
            return

        database_type = DatabaseColumns.Column.get_database_type(python_type)
        nullable = DatabaseColumns.Column.get_nullability(python_type)
        if not database_type:
            raise TypeError(f"Field `{name}` of must be an int, str, or float, but got `{python_type!r}` instead.")

        column = DatabaseColumns.Column(
            name=name, python_type=python_type, database_type=database_type, nullable=nullable
        )
        self.direct.append(column)
        self.all.append(column)


InheritsDatabasePersistable = TypeVar("InheritsDatabasePersistable", bound="DatabasePersistable")


@dataclass
class DatabasePersistable:
    _columns: ClassVar[DatabaseColumns]
    table_name: ClassVar[str]
    pk: ClassVar[str]

    def __init_subclass__(cls):
        type_hints = {
            name: annotation
            for name, annotation in get_type_hints(cls).items()
            if annotation is not ClassVar and get_origin(annotation) is not ClassVar
        }
        assert type_hints, "a class cannot be DatabasePersistable if it does not have any fields"

        cls.table_name = getattr(cls, "table_name", re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower())
        cls.pk = getattr(cls, "pk", list(type_hints.keys())[0])

        cls._columns = DatabaseColumns()
        for name, python_type in type_hints.items():
            cls._columns.add(name, python_type)

    @classmethod
    def get_table_structure(cls) -> str:
        column_definitions = ",\n".join(
            f"{col.name} {col.database_type} {'PRIMARY KEY' if col.name == cls.pk else ''} {'DEFAULT NULL' if col.nullable else 'NOT NULL'}"
            for col in cls._columns.all
        )

        return f"""
        CREATE TABLE IF NOT EXISTS {cls.table_name} (
            {column_definitions}
        ) WITHOUT ROWID;
        """

    @classmethod
    def build(cls: Type[InheritsDatabasePersistable], *column_values: Any) -> InheritsDatabasePersistable:
        values = list(column_values)
        assert len(values) == len(
            cls._columns.all
        ), f"This class has {len(cls._columns.all)} columns, but you provided {len(values)} values."

        args = {}
        for col in cls._columns.direct:
            value = values.pop(0)
            args[col.name] = value

        for name, ref in cls._columns.references.items():
            args[name] = ref.build(*values[: len(ref._columns.all)])
            del values[: len(ref._columns.all)]

        return cls(**args)

    @classmethod
    def raw_fetch(
        cls: Type[InheritsDatabasePersistable], sql: str, parameters: Iterable[Any] = ()
    ) -> Generator[InheritsDatabasePersistable, None, None]:
        for row in _active_cursors[-1].execute(sql, tuple(parameters)):
            assert len(row) == len(
                cls._columns.all
            ), f"Your query selects {len(row)} columns, but this class contains {len(cls._columns.all)} columns. You must `SELECT` exactly the right number of columns."

            yield cls.build(*row)

    @classmethod
    def where_sql(
        cls: Type[InheritsDatabasePersistable],
        sql: str,
        parameters: Iterable[Any] = (),
        limit: int | None = None,
        offset: int | None = None,
    ) -> Generator[InheritsDatabasePersistable, None, None]:
        return cls.raw_fetch(
            (
                f"SELECT {', '.join(col.name for col in cls._columns.all)}"
                + (f" FROM {cls.table_name}")
                + (f" WHERE ({sql})")
                + (f" LIMIT {limit:d}" if limit is not None else "")
                + (f" OFFSET {offset:d}" if offset is not None else "")
            ),
            parameters,
        )

    @classmethod
    def parse_sql_condition(cls, attribute: str, value: Any) -> tuple[str, list[Any]]:
        column = attribute
        parameters = [value]
        condition = f"{column} = ?"

        if "__" in attribute:
            *column, modifier = attribute.split("__")
            column = "__".join(column)

            match modifier:
                case "not":
                    condition = f"{column} != ?"
                case "in":
                    assert isinstance(value, Iterable), "You can't use `__in` without an iterable."
                    value = list(value)
                    condition = f"{column} IN ({','.join('?' * len(value))})"
                    parameters = value
                case "not_in":
                    assert isinstance(value, Iterable), "You can't use `__not_in` without an iterable."
                    value = list(value)
                    condition = f"{column} NOT IN ({','.join('?' * len(value))})"
                    parameters = value
                case _:
                    raise ValueError(f"Unknown modifier {f'__{modifier}'!r}")

        if column not in (col.name for col in cls._columns.all):
            raise ValueError(f"Unknown column {column!r}")

        return condition, parameters

    @classmethod
    def where(
        cls: Type[InheritsDatabasePersistable], _limit: int | None = None, _offset: int | None = None, **attributes
    ) -> Generator[InheritsDatabasePersistable, None, None]:
        conditions = []
        parameters = []
        for attribute, value in attributes.items():
            condition, parameter = cls.parse_sql_condition(attribute, value)
            conditions.append(condition)
            parameters.extend(parameter)

        return cls.where_sql(
            " AND ".join(conditions).strip() or "TRUE",
            parameters,
            limit=_limit,
            offset=_offset,
        )

    @classmethod
    def find_by(cls: Type[InheritsDatabasePersistable], **attributes) -> InheritsDatabasePersistable | None:
        for record in cls.where(_limit=1, **attributes):
            return record

    @classmethod
    def find(cls: Type[InheritsDatabasePersistable], **attributes) -> InheritsDatabasePersistable:
        record = cls.find_by(**attributes)
        if record is None:
            raise LookupError("Could not find the specified record.")

        return record

    @classmethod
    def all(cls: Type[InheritsDatabasePersistable]) -> Generator[InheritsDatabasePersistable, None, None]:
        return cls.where()

    def assign_attributes(self, **attributes) -> None:
        for key in attributes.keys():
            if not hasattr(self, key):
                raise ValueError(f"Unknown attribute {key!r}")

        for key, value in attributes.items():
            setattr(self, key, value)

    def update(self, **attributes) -> None:
        self.assign_attributes(**attributes)
        self.save()

    def get_ordered_column_values(self) -> list[Any]:
        cls = self.__class__
        return [getattr(self, col.name) for col in cls._columns.direct] + [
            value
            for ref_name in cls._columns.references.keys()
            for value in getattr(self, ref_name).get_ordered_column_values()
        ]

    def save(self):
        cls = self.__class__
        sql = f"""
        INSERT INTO {self.table_name} ({', '.join(col.name for col in cls._columns.all)})
        VALUES ({', '.join('?' * len(cls._columns.all))})
        ON CONFLICT({cls.pk}) DO UPDATE SET {", ".join(f"{col.name} = ?" for col in cls._columns.all)}
        """

        _active_cursors[-1].execute(sql, self.get_ordered_column_values() * 2)

    def delete(self):
        cls = self.__class__
        _active_cursors[-1].execute(f"DELETE FROM {cls.table_name} WHERE {cls.pk} = ?", (getattr(self, cls.pk),))


@dataclass
class SchoolBasedStat(DatabasePersistable):
    universal: float = 0.0

    fire: float = 0.0
    ice: float = 0.0
    storm: float = 0.0

    myth: float = 0.0
    life: float = 0.0
    death: float = 0.0

    balance: float = 0.0

    sun: float = 0.0
    moon: float = 0.0
    star: float = 0.0

    def total(self, school: str | None) -> float:
        x = self.universal

        for k, v in self.__dict__.items():
            if k == school:
                x += v

        return x


@dataclass
class Stats(DatabasePersistable):
    damage_percent: SchoolBasedStat = field(default_factory=SchoolBasedStat)
    damage_flat: SchoolBasedStat = field(default_factory=SchoolBasedStat)

    resist_percent: SchoolBasedStat = field(default_factory=SchoolBasedStat)
    resist_flat: SchoolBasedStat = field(default_factory=SchoolBasedStat)

    critical_rating: SchoolBasedStat = field(default_factory=SchoolBasedStat)
    critical_block_rating: SchoolBasedStat = field(default_factory=SchoolBasedStat)

    pierce_percent: SchoolBasedStat = field(default_factory=SchoolBasedStat)

    shadow_pip_rating: float = 0.0

    power_pip_percent: float = 0.0

    accuracy_percent: SchoolBasedStat = field(default_factory=SchoolBasedStat)

    health: float = 0.0
    mana: float = 0.0


@dataclass
class RawSiteData(DatabasePersistable):
    page_url: str = ""

    category: str = "N/A"
    page_source: str | None = None


@dataclass
class WearableItem(DatabasePersistable):
    CATEGORIES: ClassVar[tuple[str]] = tuple({*CATEGORIES} - {"jewels", "talents"})

    page_url: str = ""

    name: str = "N/A"
    category: str = "N/A"
    stats: Stats = field(default_factory=Stats)


@dataclass
class PetAbility(DatabasePersistable):
    page_url: str = ""

    name: str = "N/A"
    stats: Stats = field(default_factory=Stats)


@dataclass
class Jewel(DatabasePersistable):
    page_url: str = ""

    name: str = "N/A"
    shape: str = "N/A"
    stats: Stats = field(default_factory=Stats)
    pet_ability_page_url: str | None = None


connection = util.database_resource("central.sqlite")
connection.executescript(
    f"""
    {RawSiteData.get_table_structure()};
    CREATE INDEX IF NOT EXISTS {RawSiteData.table_name}_category_index ON {RawSiteData.table_name} (category);
    
    {WearableItem.get_table_structure()};
    CREATE INDEX IF NOT EXISTS {WearableItem.table_name}_category_index ON {WearableItem.table_name} (category);
    CREATE INDEX IF NOT EXISTS {WearableItem.table_name}_name_index ON {WearableItem.table_name} (name);
    
    {PetAbility.get_table_structure()};
    CREATE INDEX IF NOT EXISTS {PetAbility.table_name}_name_index ON {PetAbility.table_name} (name);
    
    {Jewel.get_table_structure()};
    CREATE INDEX IF NOT EXISTS {Jewel.table_name}_name_index ON {Jewel.table_name} (name);
    CREATE INDEX IF NOT EXISTS {Jewel.table_name}_shape_index ON {Jewel.table_name} (shape);
    CREATE INDEX IF NOT EXISTS {Jewel.table_name}_pet_ability_page_url_index ON {Jewel.table_name} (pet_ability_page_url);
    """
)
connection.commit()


_active_cursors = [connection.cursor()]


@contextmanager
def cursor(commit=True):
    cur = connection.cursor()
    _active_cursors.append(cur)
    yield cur
    _active_cursors.pop()

    if commit:
        connection.commit()
