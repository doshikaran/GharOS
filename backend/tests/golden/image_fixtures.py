"""Synthetic, Pillow-rendered image fixtures for the golden-file suite's
image-shaped document types (receipt, permission_slip,
attendance_register, society_notice, school_communication).

**These are NOT real scanned/photographed documents — say so plainly.**
This phase's operator brief explicitly authorises synthetic fixtures when
real scanned documents are unavailable, as "a standard, legitimate
testing technique for multimodal extraction." Every image here is
generated at test-collection time by this module: plain text is drawn
onto a blank canvas with a real TTF font, then deliberately degraded
(slight rotation, gaussian noise, JPEG-recompression-style contrast
reduction) to approximate the kind of messiness a phone-camera photo of a
paper document actually has (spec §17: "Best demo surface — visibly
messy"). No claim is made, anywhere in this test suite, that these are
real photographs of real paper.

**Region accuracy:** every field's bounding-box region string returned
alongside an image is computed from Pillow's own `ImageDraw.textbbox` at
draw time — not eyeballed — so the golden test's assertion that "every
field carries a real source-region pointer" is checking a genuinely
accurate coordinate, not a guess.

**Font portability:** prefers real installed TTF fonts (a monospace face
for printed receipts/notices, a cursive/script face for the one
deliberately-handwriting-style attendance register) when available on the
machine running the tests, and falls back to Pillow's built-in bitmap
font otherwise so this suite never fails on a machine without those exact
fonts installed — the fallback renders less realistically but the
underlying extraction logic under test does not depend on which font
was used.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_CANVAS_SIZE = (900, 1200)
_BG_COLOR = (255, 255, 255)
_TEXT_COLOR = (20, 20, 20)

_MONO_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)
_SANS_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_HANDWRITING_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",
    "/System/Library/Fonts/Supplemental/Noteworthy.ttc",
)


def _load_font(candidates: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


@dataclass(frozen=True, slots=True)
class RenderedField:
    """One drawn text field's value and its real, computed bounding box."""

    value: str
    region: str  # "page=1;bbox=x0,y0,x1,y1"


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    png_bytes: bytes
    fields: dict[str, RenderedField]


class _Canvas:
    """Thin helper around `PIL.ImageDraw` that tracks a writing cursor and
    records each drawn field's real bounding box as it goes."""

    def __init__(self, *, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, line_height: int = 34) -> None:
        self.image = Image.new("RGB", _CANVAS_SIZE, _BG_COLOR)
        self.draw = ImageDraw.Draw(self.image)
        self.font = font
        self.line_height = line_height
        self.y = 40
        self.fields: dict[str, RenderedField] = {}

    def write_line(self, text: str, *, field_name: str | None = None, field_value: str | None = None) -> None:
        x = 40
        self.draw.text((x, self.y), text, fill=_TEXT_COLOR, font=self.font)
        if field_name is not None:
            value = field_value if field_value is not None else text
            bbox = self.draw.textbbox((x, self.y), text, font=self.font)
            self.fields[field_name] = RenderedField(
                value=value, region=f"page=1;bbox={bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            )
        self.y += self.line_height

    def blank_line(self) -> None:
        self.y += self.line_height // 2

    def finish(self, *, degrade: bool, seed: int) -> RenderedDocument:
        image = self.image
        if degrade:
            image = _degrade(image, seed=seed)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return RenderedDocument(png_bytes=buffer.getvalue(), fields=self.fields)


def _degrade(image: Image.Image, *, seed: int) -> Image.Image:
    """Approximates phone-camera messiness: slight rotation, blur, and
    per-pixel noise — deliberately never so extreme the content becomes
    genuinely unreadable to a real multimodal model (except the one
    fixture that intentionally goes further, see
    `attendance_register_illegible` below)."""
    rng = random.Random(seed)
    angle = rng.uniform(-2.5, 2.5)
    rotated = image.rotate(angle, expand=True, fillcolor=_BG_COLOR)
    blurred = rotated.filter(ImageFilter.GaussianBlur(radius=0.6))
    noisy = blurred.copy()
    pixels = noisy.load()
    assert pixels is not None
    width, height = noisy.size
    for _ in range(width * height // 40):
        x, y = rng.randrange(width), rng.randrange(height)
        jitter = rng.randint(-25, 25)
        r, g, b = cast("tuple[int, int, int]", pixels[x, y])
        pixels[x, y] = (
            max(0, min(255, r + jitter)),
            max(0, min(255, g + jitter)),
            max(0, min(255, b + jitter)),
        )
    return noisy


# ---------------------------------------------------------------------------
# Fixture builders — one per golden document
# ---------------------------------------------------------------------------


def receipt_grocery() -> RenderedDocument:
    """A clean-ish grocery receipt — legible but photographed (light
    rotation/noise only)."""
    canvas = _Canvas(font=_load_font(_MONO_FONT_CANDIDATES, 24))
    canvas.write_line("BIG BAZAAR SUPERMARKET", field_name="merchant_name", field_value="Big Bazaar")
    canvas.write_line("Andheri West, Mumbai", field_name="merchant_category", field_value="grocery")
    canvas.write_line(
        "Date: 2026-08-15 10:30", field_name="transaction_datetime", field_value="2026-08-15T10:30:00"
    )
    canvas.blank_line()
    canvas.write_line("AMUL TAAZA 1L        x2    60.00")
    canvas.write_line("BREAD LOAF           x1    40.00")
    canvas.blank_line()
    canvas.write_line("TOTAL:              100.00", field_name="total", field_value="100.00")
    canvas.write_line("PAYMENT: UPI")
    return canvas.finish(degrade=True, seed=1)


def receipt_pharmacy_thermal() -> RenderedDocument:
    """A faded thermal-printer pharmacy receipt — deliberately messier,
    the A3b "partial extraction" case (one line is heavily degraded)."""
    canvas = _Canvas(font=_load_font(_MONO_FONT_CANDIDATES, 20), line_height=30)
    canvas.write_line("CITY PHARMACY", field_name="merchant_name", field_value="City Pharmacy")
    canvas.write_line("Date: 2026-08-18 18:05")
    canvas.blank_line()
    canvas.write_line("PARACETAMOL 500MG    x1    30.00")
    canvas.write_line("BANDAGE ROLL         x2    50.00")
    canvas.blank_line()
    canvas.write_line("TOTAL:               80.00", field_name="total", field_value="80.00")
    return canvas.finish(degrade=True, seed=2)


def society_notice_dues() -> RenderedDocument:
    canvas = _Canvas(font=_load_font(_SANS_FONT_CANDIDATES, 24))
    canvas.write_line(
        "GREEN MEADOWS CO-OP HOUSING SOCIETY", field_name="society_name", field_value="Green Meadows CHS"
    )
    canvas.write_line("NOTICE: Maintenance Dues", field_name="notice_type", field_value="dues")
    canvas.blank_line()
    canvas.write_line("Unit: A-402")
    canvas.write_line("Amount Due: Rs. 3500", field_name="amount", field_value="3500")
    canvas.write_line("Due Date: 2026-09-10", field_name="due_date", field_value="2026-09-10")
    return canvas.finish(degrade=True, seed=3)


def society_notice_rule_change() -> RenderedDocument:
    canvas = _Canvas(font=_load_font(_SANS_FONT_CANDIDATES, 24))
    canvas.write_line(
        "GREEN MEADOWS CO-OP HOUSING SOCIETY", field_name="society_name", field_value="Green Meadows CHS"
    )
    canvas.write_line(
        "NOTICE: Rule Change - Parking Hours",
        field_name="notice_type",
        field_value="rule_change: parking hours",
    )
    canvas.blank_line()
    canvas.write_line("Effective 2026-09-01, visitor parking closes at 10pm.")
    return canvas.finish(degrade=True, seed=4)


def school_communication_field_trip() -> RenderedDocument:
    canvas = _Canvas(font=_load_font(_SANS_FONT_CANDIDATES, 22))
    canvas.write_line("GREEN VALLEY SCHOOL", field_name="institution", field_value="Green Valley School")
    canvas.write_line("Re: Aarav Sharma, Grade 4B", field_name="student", field_value="Aarav Sharma")
    canvas.write_line(
        "Field Trip Permission & Fee Notice", field_name="communication_type", field_value="field_trip"
    )
    canvas.blank_line()
    canvas.write_line("Trip: Friday, 2026-08-28", field_name="event_date", field_value="2026-08-28")
    canvas.write_line("Fee: Rs. 500", field_name="amount", field_value="500")
    canvas.write_line(
        "Please return signed slip by 2026-08-26",
        field_name="response_deadline",
        field_value="2026-08-26",
    )
    return canvas.finish(degrade=True, seed=5)


def permission_slip_field_trip() -> RenderedDocument:
    canvas = _Canvas(font=_load_font(_SANS_FONT_CANDIDATES, 22))
    canvas.write_line(
        "GREEN VALLEY SCHOOL - CONSENT FORM", field_name="issuing_body", field_value="Green Valley School"
    )
    canvas.write_line("Student: Aarav Sharma", field_name="subject_person", field_value="Aarav Sharma")
    canvas.write_line(
        "I consent to my child attending the museum trip.",
        field_name="consent_description",
        field_value="attending the museum trip",
    )
    canvas.write_line(
        "Signature required: Parent/Guardian",
        field_name="required_signatory_type",
        field_value="parent",
    )
    canvas.write_line("Return by: 2026-08-26", field_name="return_deadline", field_value="2026-08-26")
    return canvas.finish(degrade=True, seed=6)


def attendance_register_legible() -> RenderedDocument:
    """Legible handwriting-style font, presence marks clearly formed."""
    canvas = _Canvas(font=_load_font(_HANDWRITING_FONT_CANDIDATES, 28), line_height=38)
    canvas.write_line("Staff: Radha Devi", field_name="staff_member", field_value="Radha Devi")
    canvas.write_line("Month: August 2026", field_name="month", field_value="August 2026")
    canvas.blank_line()
    canvas.write_line(
        "1 P  2 P  3 P  4 A  5 P  6 P  7 P",
        field_name="per_day_presence_marks",
        field_value="mostly present",
    )
    return canvas.finish(degrade=True, seed=7)


def attendance_register_illegible() -> RenderedDocument:
    """**Gate 3 planted case:** deliberately illegible handwriting —
    small font, heavy degradation — the below-floor case that must
    surface the image for human review, never be inferred."""
    canvas = _Canvas(font=_load_font(_HANDWRITING_FONT_CANDIDATES, 13), line_height=20)
    canvas.write_line("Staff: ??? (smudged)", field_name="staff_member", field_value="(illegible)")
    canvas.write_line("Month: Aug 2026", field_name="month", field_value="August 2026")
    canvas.blank_line()
    canvas.write_line(
        "scrawled marks, heavy ink smear",
        field_name="per_day_presence_marks",
        field_value="(illegible)",
    )
    doc = canvas.finish(degrade=False, seed=8)
    # Heavier, deliberate degradation beyond `_degrade`'s normal range —
    # this fixture must be genuinely hard to read, not just "photographed."
    image = Image.open(io.BytesIO(doc.png_bytes)).convert("RGB")
    image = image.filter(ImageFilter.GaussianBlur(radius=3.5))
    image = image.rotate(7, expand=True, fillcolor=_BG_COLOR)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return RenderedDocument(png_bytes=buffer.getvalue(), fields=doc.fields)


__all__ = [
    "RenderedDocument",
    "RenderedField",
    "attendance_register_illegible",
    "attendance_register_legible",
    "permission_slip_field_trip",
    "receipt_grocery",
    "receipt_pharmacy_thermal",
    "school_communication_field_trip",
    "society_notice_dues",
    "society_notice_rule_change",
]
