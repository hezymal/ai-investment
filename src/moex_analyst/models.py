"""Versioned research input; facts retain scope, units and provenance."""
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def now() -> datetime:
    return datetime.now(timezone.utc)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(Model):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str = Field(min_length=1)
    retrieved_at: datetime
    published_on: date | None = None
    period: str | None = None
    sha256: str | None = None


class Entity(Model):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    inn: str | None = None
    sector: Literal["nonfinancial", "bank", "insurance", "other_financial"] = "nonfinancial"
    role: Literal["issuer", "group", "guarantor"] = "issuer"


class Metric(Model):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    value: float | None
    period_start: date
    period_end: date
    period_kind: Literal["instant", "FY", "H1", "Q1", "9M", "TTM"]
    standard: Literal["IFRS", "RAS", "management", "market", "regulatory"]
    entity_id: str
    scope: Literal["consolidated", "standalone"]
    unit: Literal["currency", "percent", "ratio", "shares", "units"] = "currency"
    currency: str | None = "RUB"
    scale: float = Field(default=1, gt=0)
    source_ids: list[str] = Field(min_length=1)
    locator: str = Field(min_length=1, description="Page/table/row or API field")
    note: str = ""

    @model_validator(mode="after")
    def coherent(self):
        if self.period_end < self.period_start:
            raise ValueError("period_end precedes period_start")
        if self.unit == "currency" and not self.currency:
            raise ValueError("currency is required for monetary metrics")
        if self.period_kind == "instant" and self.period_start != self.period_end:
            raise ValueError("instant metric must have one date")
        return self


class Finding(Model):
    text: str = Field(min_length=1)
    kind: Literal["fact", "interpretation", "assumption"]
    source_ids: list[str] = Field(default_factory=list)


class Analysis(Model):
    schema_version: Literal[1] = 1
    query: str = Field(min_length=1)
    entity: Entity
    related_entities: list[Entity] = Field(default_factory=list)
    instrument: str | None = None
    asset_type: Literal["issuer", "bond", "equity"] = "issuer"
    as_of: date
    status: Literal["complete", "partial"] = "partial"
    sources: list[Source] = Field(min_length=1)
    metrics: list[Metric] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conclusion: str = Field(min_length=1)
    bond: dict | None = None
    equity: dict | None = None
    methodology_version: str = "0.1.0"

    @model_validator(mode="after")
    def references(self):
        sources = {s.id for s in self.sources}
        if len(sources) != len(self.sources):
            raise ValueError("duplicate source ids")
        entities = [self.entity.id] + [e.id for e in self.related_entities]
        if len(set(entities)) != len(entities):
            raise ValueError("duplicate entity ids")
        keys = set()
        for m in self.metrics:
            if m.entity_id not in entities or not set(m.source_ids) <= sources:
                raise ValueError("metric references unknown entity or source")
            key = metric_key(m)
            if key in keys:
                raise ValueError("duplicate metric for the same period and scope")
            keys.add(key)
        for finding in self.findings:
            if not set(finding.source_ids) <= sources:
                raise ValueError("finding references unknown source")
            if finding.kind == "fact" and not finding.source_ids:
                raise ValueError("facts require sources")
        if self.status == "complete" and (self.gaps or any(m.value is None for m in self.metrics)):
            raise ValueError("analysis with missing data must be partial")
        if self.bond is not None:
            from .finance import BondInput
            bond = BondInput.model_validate(self.bond)
            if self.asset_type != "bond" or self.instrument != bond.instrument:
                raise ValueError("bond input must match analysis asset type and instrument")
        if self.equity is not None:
            from .finance import EquityInput
            EquityInput.model_validate(self.equity)
            if self.asset_type != "equity":
                raise ValueError("equity input requires equity asset type")
        return self


def metric_key(m: Metric) -> tuple:
    return (m.name, m.entity_id, m.standard, m.scope, m.period_kind,
            m.period_start.isoformat(), m.period_end.isoformat(), m.unit, m.currency)
