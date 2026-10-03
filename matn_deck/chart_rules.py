"""Chart rules (design/chart_rules.json): the chart type, order, key point and callout are decided by code from the
table's data shape and the slide's cited facts. Values stay exactly as the table gives them; sorting only reorders
whole rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import re

from matn_contracts.domain import ChartSpec, Fact, Table

RULES_PATH = Path(__file__).resolve().parents[1] / "design" / "chart_rules.json"
_NUMBER = re.compile(r"(?P<sign>[-−])?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?P<pct>%)?")


class ChartDataError(ValueError):
    pass


@lru_cache(maxsize=2)
def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Series:
    name: str
    values: tuple[Decimal, ...]
    texts: tuple[str, ...]  # the cells as written


@dataclass(frozen=True)
class ChartDecision:
    shape: str  # time_series | part_to_whole | categorical | other
    kind: str  # line | column | bar | stacked_bar
    categories: tuple[str, ...]
    series: tuple[Series, ...]
    key: tuple[int, int]  # (series index, point index) of the focus point, in the decided order
    key_fact_id: str | None  # the cited number fact the key point equals, if any
    number_format: str
    sorted_rows: bool


def _decimal(match: re.Match) -> Decimal:
    value = Decimal(match["int"].replace(",", "") + "." + (match["frac"] or "0"))
    return -value if match["sign"] else value


def read_table(table: Table, spec: ChartSpec, series_fallback: str) -> tuple[list[str], list[Series], str]:
    """Categories, series and a number format, copied from the table cells (CHART_CELL_* errors on bad cells)."""
    cells = {(cell.row, cell.col): cell.text.strip() for cell in table.cells}
    rows = sorted({cell.row for cell in table.cells} - set(table.header_rows))

    def cell_text(row: int, col: int) -> str:
        text = cells.get((row, col), "")
        if not text:
            raise ChartDataError(f"CHART_CELL_MISSING:{table.table_id}:r{row}c{col}")
        return text

    parsed: list[re.Match] = []
    series = []
    for n, col in enumerate(spec.y_columns, start=1):
        header = " ".join(cells[(r, col)] for r in table.header_rows if cells.get((r, col)))
        values, texts = [], []
        for row in rows:
            text = cell_text(row, col)
            match = _NUMBER.fullmatch(text)
            if match is None:
                raise ChartDataError(f"CHART_CELL_NOT_NUMERIC:{table.table_id}:r{row}c{col}:{text!r}")
            parsed.append(match)
            values.append(_decimal(match))
            texts.append(text)
        series.append(Series(header or series_fallback.format(n=n), tuple(values), tuple(texts)))
    decimals = max(len(m["frac"] or "") for m in parsed)
    number_format = "#,##0" if any("," in m["int"] for m in parsed) else "0"
    number_format += ("." + "0" * decimals if decimals else "") + ('"%"' if any(m["pct"] for m in parsed) else "")
    return [cell_text(row, spec.x_column) for row in rows], series, number_format


def _time_key(label: str) -> tuple[int, ...]:
    """(year, quarter or month) from "2024", "2024-03" or "Q1 2024"."""
    numbers = [int(n) for n in re.findall(r"\d+", label)]
    years = [n for n in numbers if n >= 1900]
    return (years[0], *[n for n in numbers if n < 1900]) if years else tuple(numbers)


def data_shape(categories: list[str], series: list[Series], rules: dict) -> str:
    patterns = [re.compile(p) for p in rules["time_series"]["x_patterns"]]
    if len(categories) >= 2 and all(any(p.fullmatch(c) for p in patterns) for c in categories):
        keys = [_time_key(c) for c in categories]
        if all(a < b for a, b in zip(keys, keys[1:])):
            return "time_series"
    part = rules["part_to_whole"]
    if (len(series) == 1 and 2 <= len(categories) <= part["max_parts"] and all("%" in t for t in series[0].texts)
            and abs(sum(series[0].values) - part["total"]) <= Decimal(str(part["tolerance"]))):
        return "part_to_whole"
    if len(categories) <= rules["categorical"]["max_categories"]:
        return "categorical"
    return "other"


def _key_point(series: list[Series], cited: list[Fact]) -> tuple[tuple[int, int], str | None]:
    """The point a cited number fact equals (first fact, then first matching cell), otherwise the maximum of the
    last series."""
    for fact in cited:
        value = fact.number_value
        if value is None:
            continue
        match = _NUMBER.fullmatch(value.value_as_written.strip())
        if match is None:
            continue
        target = _decimal(match)
        for s_index in range(len(series) - 1, -1, -1):
            for p_index, v in enumerate(series[s_index].values):
                if v == target:
                    return (s_index, p_index), fact.fact_id
    last = len(series) - 1
    values = series[last].values
    return (last, values.index(max(values))), None


def decide(table: Table, spec: ChartSpec, cited: list[Fact], *, series_fallback: str = "Series {n}",
           rules: dict | None = None) -> ChartDecision:
    rules = rules or load_rules()
    categories, series, number_format = read_table(table, spec, series_fallback)
    shape = data_shape(categories, series, rules)
    sorted_rows = False
    if shape == "time_series":
        few = len(categories) <= rules["time_series"]["column_max_points"]
        kind = rules["time_series"]["type_few" if few else "type_many"]
    elif shape == "part_to_whole":
        kind = rules["part_to_whole"]["type"]
    elif shape == "categorical":
        kind = rules["categorical"]["type"]
        if rules["categorical"]["sort"] == "descending":
            key_values = series[-1].values
            order = sorted(range(len(categories)), key=lambda i: (-key_values[i], i))
            sorted_rows = order != list(range(len(categories)))
            categories = [categories[i] for i in order]
            series = [Series(s.name, tuple(s.values[i] for i in order), tuple(s.texts[i] for i in order))
                      for s in series]
    else:
        kind = rules["fallback"]
    key, key_fact = _key_point(series, cited)
    return ChartDecision(shape, kind, tuple(categories), tuple(series), key, key_fact, number_format, sorted_rows)
