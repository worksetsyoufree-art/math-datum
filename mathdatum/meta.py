"""Метаданные датума и контрольная сумма исходных данных.

Метаданные (DatumMeta) — необязательные: объект, организация, исполнитель, дата и время расчёта (UTC,
ISO 8601), версия библиотеки, идентификатор датума (UUID) и ревизия (новая ревизия ссылается на UUID
предыдущей), источник каталога пунктов, система ГНСС и оборудование, примечание. В старых JSON их нет.

Контрольная сумма inputs_sha256 — SHA-256 канонической записи входных пар и параметров localize
(Inputs), одинаковой в Python и Kotlin:

    mathdatum inputs v1
    gnss_datum="WGS-84"
    sigma_plan=0.02
    …                                  (поля Inputs по порядку; null — не задано)
    pair="R1";55.0527657163;…;"both";null;null      (name;B;L;h;x;y;H;use;sigma_plan;sigma_height)

Числа — как repr(float) в Python (кратчайшая точная запись), строки — в кавычках с экранированием
\\ и " и управляющих символов (\\u00XX); строки разделены \\n, в конце \\n; кодировка UTF-8.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone

VERSION = "0.9.0"
LIBRARY = f"mathdatum (Python) {VERSION}"
CANON_HEADER = "mathdatum inputs v1"


@dataclass
class DatumMeta:
    """Метаданные датума; все поля необязательны (None — не указано)."""

    object: str | None = None          # объект / наименование
    organization: str | None = None
    author: str | None = None          # исполнитель
    computed_at: str | None = None     # дата и время расчёта, UTC, ISO 8601: 2026-10-18T12:00:00Z
    library_version: str | None = None
    datum_id: str | None = None        # UUID датума
    revision: int | None = None        # ревизия: 1, 2, …
    previous_id: str | None = None     # UUID предыдущей ревизии
    catalog_source: str | None = None  # источник каталога пунктов
    gnss_equipment: str | None = None  # система ГНСС, оборудование, базовая станция
    note: str | None = None
    inputs_sha256: str | None = None   # SHA-256 канонической записи пар и параметров

    DESCRIPTIVE = ("object", "organization", "author", "catalog_source", "gnss_equipment")

    def next_revision(self, **overrides) -> "DatumMeta":
        """Метаданные следующей ревизии: описательные поля наследуются (кроме примечания),
        revision + 1, previous_id — UUID этой ревизии; id, время и сумма назначаются при расчёте."""
        if not self.datum_id:
            raise ValueError("У предыдущего датума нет идентификатора (datum_id): ревизию не связать.")
        base = DatumMeta(**{k: getattr(self, k) for k in self.DESCRIPTIVE})
        base.revision = (self.revision or 1) + 1
        base.previous_id = self.datum_id
        return replace(base, **overrides)

    @classmethod
    def from_dict(cls, d: dict | None) -> "DatumMeta | None":
        if d is None:
            return None
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Inputs:
    """Параметры localize, от которых зависит результат (вместе с парами — вход контрольной суммы).
    lat0, lon0, ellipsoid = None — по умолчанию (центр точек, эллипсоид системы ГНСС)."""

    gnss_datum: str = "WGS-84"
    sigma_plan: float = 0.02
    sigma_height: float = 0.03
    w_limit: float = 3.29
    max_scale_ppm: float = 200.0
    max_rotation_deg: float = 3.0
    height_model: str = "plane"              # запрошенная модель высоты
    geoid_sha256: str | None = None
    geoid_interpolation: str | None = None
    lat0: float | None = None
    lon0: float | None = None
    ellipsoid: str | None = None
    k0: float = 1.0
    x0: float = 0.0
    y0: float = 0.0

    @classmethod
    def from_dict(cls, d: dict | None) -> "Inputs | None":
        if d is None:
            return None
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(uuid.uuid4())


def _jstr(s: str) -> str:
    out = []
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _val(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, str):
        return _jstr(v)
    return repr(float(v))


def canonical(pairs, inputs: Inputs) -> str:
    """Каноническая запись пар и параметров (вход SHA-256)."""
    lines = [CANON_HEADER]
    lines += [f"{f.name}={_val(getattr(inputs, f.name))}" for f in fields(Inputs)]
    for p in pairs:
        lines.append("pair=" + ";".join([_jstr(p.name), *(_val(getattr(p, k)) for k in ("B", "L", "h", "x", "y", "H")),
                                         _jstr(p.use), _val(p.sigma_plan), _val(p.sigma_height)]))
    return "\n".join(lines) + "\n"


def inputs_checksum(pairs, inputs: Inputs) -> str:
    """SHA-256 (hex) канонической записи пар и параметров."""
    return hashlib.sha256(canonical(pairs, inputs).encode("utf-8")).hexdigest()


def as_dict(m) -> dict | None:
    return None if m is None else asdict(m)
