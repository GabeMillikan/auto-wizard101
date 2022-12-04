from dataclasses import dataclass, field
import bisect
from typing import Type, Any

from .. import util


@dataclass
class DatabaseColumns:
    @dataclass(frozen=True)
    class Column:
        name: str
        python_type: type
        database_type: str

        @staticmethod
        def get_database_type(python_type: Type[Any]) -> str | None:
            return {int: "INTEGER", float: "REAL", str: "TEXT"}.get(python_type)  # type: ignore - idk why I can't do this

    columns: list[Column] = field(default_factory=list)

    def merge(self, name: str, database_columns: "DatabaseColumns") -> None:
        for column in database_columns.columns:
            self.add(f"{name}_{column.name}", column.python_type)

    def add(self, name: str, python_type: type) -> None:
        if issubclass(python_type, DatabasePersistable) and python_type is not DatabasePersistable:
            return self.merge(name, python_type._database_columns)

        database_type = DatabaseColumns.Column.get_database_type(python_type)
        if not database_type:
            raise TypeError(f"Field `{name}` of must be an int, str, or float, but got `{python_type!r}` instead.")

        column = DatabaseColumns.Column(name=name, python_type=python_type, database_type=database_type)
        bisect.insort(self.columns, column, key=lambda column: column.name)


class DatabasePersistable:
    _database_columns: DatabaseColumns

    def __init_subclass__(cls):
        cls._database_columns = DatabaseColumns()
        for name, python_type in cls.__annotations__.items():
            cls._database_columns.add(name, python_type)


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
    damage_percent: SchoolBasedStat
    damage_flat: SchoolBasedStat

    resist_percent: SchoolBasedStat
    resist_flat: SchoolBasedStat

    critical_rating: SchoolBasedStat
    critical_block_rating: SchoolBasedStat

    pierce_percent: SchoolBasedStat

    shadow_pip_rating: float

    power_pip_percent: float

    accuracy_percent: SchoolBasedStat

    health: float
    mana: float


@dataclass
class Item(DatabasePersistable):
    page_url: str
    image_url: str

    name: str
    category: str
    stats: Stats

    CATEGORIES = "Hats", "Robes", "Boots", "Athames", "Amulets", "Rings", "Decks", "Mounts", "Jewels"


database = util.database_resource("central.sqlite")

database.executescript(
    """
    CREATE TABLE IF NOT EXISTS cached_item_url (
        url TEXT PRIMARY KEY,
        category TEXT NOT NULL
    ) WITHOUT ROWID;

    CREATE INDEX IF NOT EXISTS cached_item_url_category_index ON cached_item_url (category);
    """
)
