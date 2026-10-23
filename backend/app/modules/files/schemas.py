from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FileFormat = Literal[
    "docx",
    "pptx",
    "xlsx",
    "pdf",
    "txt",
    "md",
    "csv",
    "html",
    "json",
    "xml",
    "yaml",
    "svg",
    "py",
    "js",
    "ts",
    "css",
    "sql",
]
CellValue = str | float | bool | None


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["heading", "paragraph", "bullet", "numbered", "table", "page_break"]
    text: str = Field(default="", max_length=20000)
    level: int = Field(default=1, ge=1, le=4)
    rows: list[list[str]] = Field(default_factory=list, max_length=300)


class SlideColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=80)
    points: list[str] = Field(default_factory=list, max_length=30)


class SlideStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(max_length=80, description="真实日期、阶段名或步骤标题，不得编造日期")
    text: str = Field(default="", max_length=3000)


class ChartSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=80)
    values: list[float] = Field(min_length=1, max_length=12)


class SlideChart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["bar", "column", "line"] = "bar"
    categories: list[str] = Field(default_factory=list, max_length=12)
    series: list[ChartSeries] = Field(default_factory=list, max_length=4)
    unit: str = Field(default="", max_length=30)
    value_format: Literal["number", "percent"] = "number"

    @model_validator(mode="after")
    def check_data(self) -> SlideChart:
        if bool(self.categories) != bool(self.series):
            raise ValueError("Chart categories and series must be supplied together")
        if any(len(series.values) != len(self.categories) for series in self.series):
            raise ValueError("Chart values must match categories")
        if any(not category.strip() or len(category) > 40 for category in self.categories):
            raise ValueError("Chart categories must be short, non-empty labels")
        return self


class Slide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=120)
    layout: Literal[
        "auto",
        "cover",
        "section",
        "bullets",
        "comparison",
        "timeline",
        "process",
        "quote",
        "table",
        "summary",
        "chart",
    ] = Field(default="auto", description="按内容选择版式，不要将整份演示都写成项目列表")
    subtitle: str = Field(default="", max_length=240)
    points: list[str] = Field(default_factory=list, max_length=30)
    columns: list[SlideColumn] = Field(default_factory=list, max_length=2)
    steps: list[SlideStep] = Field(default_factory=list, max_length=20)
    quote: str = Field(default="", max_length=10000)
    attribution: str = Field(default="", max_length=200)
    rows: list[list[str]] = Field(default_factory=list, max_length=100)
    chart: SlideChart = Field(default_factory=SlideChart)
    source: str = Field(default="", max_length=1000, description="本页已有来源及版本；无来源则留空")
    notes: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def check_layout(self) -> Slide:
        structured = {
            "comparison": bool(self.columns),
            "process": bool(self.steps),
            "quote": bool(self.quote),
            "table": bool(self.rows),
            "chart": bool(self.chart.series),
        }
        if sum(structured.values()) > 1 or (any(structured.values()) and self.points):
            raise ValueError("Use one slide content structure without duplicate points")
        expected = "process" if self.layout == "timeline" else self.layout
        if self.layout != "auto":
            if expected in structured and not structured[expected]:
                raise ValueError("Slide layout requires its matching content")
            if any(present and kind != expected for kind, present in structured.items()):
                raise ValueError("Slide content does not match its layout")
        if self.columns and len(self.columns) != 2:
            raise ValueError("Comparison slides require exactly two columns")
        if self.attribution and not self.quote:
            raise ValueError("Attribution requires quote content")
        if self.rows:
            width = len(self.rows[0])
            if not 1 <= width <= 6 or any(len(row) != width for row in self.rows):
                raise ValueError("Slide tables require one to six consistent columns")
            if any(len(cell) > 4000 for row in self.rows for cell in row):
                raise ValueError("Slide table cell exceeds limits")
        return self


class Sheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Sheet1", min_length=1, max_length=31)
    rows: list[list[CellValue]] = Field(min_length=1, max_length=1000)
    formulas: dict[str, str] = Field(default_factory=dict, max_length=1000)

    @model_validator(mode="after")
    def check_sheet(self) -> Sheet:
        if (
            re.search(r"[\\/*?:\[\]]", self.name)
            or self.name.startswith("'")
            or self.name.endswith("'")
        ):
            raise ValueError("Invalid worksheet name")
        if any(len(row) > 50 for row in self.rows):
            raise ValueError("Too many worksheet columns")
        if any(
            isinstance(cell, str)
            and (len(cell) > 32767 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", cell))
            for row in self.rows
            for cell in row
        ):
            raise ValueError("Worksheet cell content exceeds limits")
        allowed = {
            "SUM",
            "AVERAGE",
            "MIN",
            "MAX",
            "ROUND",
            "IF",
            "COUNT",
            "COUNTA",
            "SUMIF",
            "SUMIFS",
            "COUNTIF",
            "ABS",
            "ROUNDUP",
            "ROUNDDOWN",
        }
        for address, formula in self.formulas.items():
            if not re.fullmatch(r"[A-Z]{1,2}[1-9][0-9]{0,2}", address):
                raise ValueError("Invalid formula address")
            if len(formula) > 1000 or not formula.startswith("="):
                raise ValueError("Invalid formula")
            if not re.fullmatch(r"[=\w$:+*/().,<>!% \-'\"]+", formula):
                raise ValueError("Unsupported formula characters")
            functions = re.findall(r"([A-Za-z_][A-Za-z_0-9.]*)\s*\(", formula)
            if any(function.upper() not in allowed for function in functions):
                raise ValueError("Unsupported formula function")
        return self


class FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: FileFormat
    name: str = Field(min_length=1, max_length=150)
    title: str = Field(default="", max_length=200)
    blocks: list[Block] = Field(default_factory=list, max_length=300)
    slides: list[Slide] = Field(default_factory=list, max_length=80)
    sheets: list[Sheet] = Field(default_factory=list, max_length=20)
    text: str = Field(default="", max_length=100000)

    @model_validator(mode="after")
    def check_content(self) -> FileSpec:
        if self.format in {"docx", "pdf"} and not self.blocks:
            raise ValueError("Document blocks are required")
        if self.format == "pptx" and not self.slides:
            raise ValueError("Presentation slides are required")
        if self.format in {"xlsx", "csv"} and not self.sheets:
            raise ValueError("Worksheet rows are required")
        if self.format == "csv" and len(self.sheets) != 1:
            raise ValueError("CSV requires exactly one sheet")
        if self.format not in {"docx", "pdf", "pptx", "xlsx", "csv"} and not self.text.strip():
            raise ValueError("Text content is required")
        if any(
            len(row) > 12 or any(len(cell) > 4000 for cell in row)
            for block in self.blocks
            for row in block.rows
        ):
            raise ValueError("Document table exceeds limits")
        if any(block.kind == "table" and not block.rows for block in self.blocks):
            raise ValueError("Table rows are required")
        names = [sheet.name.casefold() for sheet in self.sheets]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate worksheet names")
        return self


class GenerateFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[FileSpec] = Field(min_length=1, max_length=5)
    archive_name: str | None = Field(default=None, max_length=150)


class GeneratedFileView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    mime_type: str
    size: int
    created_at: datetime
