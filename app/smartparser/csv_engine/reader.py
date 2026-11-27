"""Module D - deterministic CSV reading.

Every cell is kept exactly as read (string). No interpretation happens here
except header-row location and structural observations.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field

from ..models.results import ColumnProfile, CsvExtraction
from ..normalise import values as nv

PREAMBLE_SCAN_ROWS = 20


@dataclass
class RawRow:
    row_number: int        # 1-based index among data rows
    source_line: int       # physical line where the record starts
    cells: list[str]


@dataclass
class CsvTable:
    headers: list[str]            # trimmed, blank headers replaced by placeholders
    raw_headers: list[str]
    header_line: int
    rows: list[RawRow]
    preamble: list[str] = field(default_factory=list)
    empty_row_lines: list[int] = field(default_factory=list)
    ragged_row_lines: list[int] = field(default_factory=list)
    blank_header_indexes: list[int] = field(default_factory=list)
    duplicate_headers: list[str] = field(default_factory=list)
    error: str | None = None          # set when reading stopped early
    stopped_at_line: int | None = None

    def column_values(self, index: int) -> list[str]:
        return [r.cells[index] for r in self.rows if index < len(r.cells)]


class CsvReadError(Exception):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line


def _records(text: str, delimiter: str):
    """Yield (start_line, cells). Stops with CsvReadError on malformed quoting."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter,
                        quotechar='"', doublequote=True, strict=True)
    start = 1
    while True:
        try:
            cells = next(reader)
        except StopIteration:
            return
        except csv.Error as exc:
            raise CsvReadError(f"line {reader.line_num}: {exc}", reader.line_num) from exc
        yield start, cells
        start = reader.line_num + 1


def read_csv(data: bytes, encoding: str, delimiter: str) -> CsvTable:
    text = data.decode(encoding)
    if text.startswith("﻿"):
        text = text[1:]

    collected: list[tuple[int, list[str]]] = []
    error = stopped = None
    try:
        for line, cells in _records(text, delimiter):
            collected.append((line, cells))
    except CsvReadError as exc:
        error, stopped = str(exc), exc.line

    non_blank = [(ln, c) for ln, c in collected if any(x.strip() for x in c)]
    if not non_blank:
        raise CsvReadError(error or "No content rows found")

    # Header = first row (within the scan window) whose width equals the modal width.
    modal = Counter(len(c) for _, c in non_blank).most_common(1)[0][0]
    header_pos = next((i for i, (_, c) in enumerate(non_blank[:PREAMBLE_SCAN_ROWS])
                       if len(c) == modal), 0)
    header_line, raw_headers = non_blank[header_pos]
    preamble = [delimiter.join(c) for _, c in non_blank[:header_pos]]

    headers, blank_idx = [], []
    for i, h in enumerate(raw_headers):
        h2 = h.replace("﻿", "").strip()
        if not h2:
            blank_idx.append(i)
            h2 = f"__blank_column_{i + 1}"
        headers.append(h2)
    dup = [h for h, n in Counter(headers).items() if n > 1]

    table = CsvTable(headers=headers, raw_headers=list(raw_headers), header_line=header_line,
                     rows=[], preamble=preamble, blank_header_indexes=blank_idx,
                     duplicate_headers=dup, error=error, stopped_at_line=stopped)
    row_no = 0
    for line, cells in collected:
        if line <= header_line:
            continue
        if not any(x.strip() for x in cells):
            table.empty_row_lines.append(line)
            continue
        if len(cells) != len(headers):
            table.ragged_row_lines.append(line)
        row_no += 1
        table.rows.append(RawRow(row_no, line, cells))
    return table


def column_keys(headers: list[str]) -> list[str]:
    """Unique record keys for the columns of a table, by position (Phase 3B-7). The first occurrence of a header name
    keeps the name; a later column with the SAME name is keyed `name [col N]` (N = 1-based position), so a record never
    loses a cell when two columns share a name. Columns are identified by position, never by header text alone."""
    keys, seen = [], set()
    for i, h in enumerate(headers):
        k = h if h not in seen else f"{h} [col {i + 1}]"
        while k in seen:
            k = f"{k}*"
        seen.add(k)
        keys.append(k)
    return keys


# --------------------------------------------------------------------------- profiling

def infer_type(values: list[str]) -> str:
    vals = [v for v in values if v.strip()]
    if not vals:
        return "empty"
    sample = vals[:500]
    for name, fn in (
        ("integer", lambda v: nv.parse_integer(v).ok),
        ("decimal", lambda v: nv.parse_decimal(v).ok or nv.parse_decimal(v, ",").ok),
        ("date", lambda v: nv.parse_date(v).ok),
        ("datetime", lambda v: nv.parse_datetime(v).ok),
        ("boolean", lambda v: nv.parse_boolean(v).ok),
    ):
        if all(fn(v) for v in sample):
            return name
    return "string"


def profile(table: CsvTable) -> CsvExtraction:
    cols = []
    for i, name in enumerate(table.headers):
        vals = table.column_values(i)
        non_empty = [v for v in vals if v.strip()]
        cols.append(ColumnProfile(
            index=i, name=name, raw_name=table.raw_headers[i], inferred_type=infer_type(vals),
            non_empty_count=len(non_empty), empty_count=len(vals) - len(non_empty),
            sample_values=non_empty[:5],
        ))
    return CsvExtraction(
        headers=table.headers, raw_headers=table.raw_headers, header_line=table.header_line,
        data_row_count=len(table.rows), preamble_lines=table.preamble, columns=cols,
        empty_rows=table.empty_row_lines, ragged_rows=table.ragged_row_lines,
        stopped_at_line=table.stopped_at_line,
    )
