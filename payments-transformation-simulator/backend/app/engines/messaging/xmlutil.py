"""Small XML helpers for ISO 20022 message construction.

Uses the standard library only. Messages are built as element trees and
serialised with indentation so the Message Viewer can show readable XML.
"""

from __future__ import annotations

from decimal import Decimal
from xml.etree import ElementTree as ET

from app.domain.money import quantize, scale_for

DOCUMENT_TAG = "Document"


def document(namespace: str) -> ET.Element:
    root = ET.Element(DOCUMENT_TAG)
    root.set("xmlns", namespace)
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    return root


def sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, {k: v for k, v in attrs.items() if v is not None})
    if text is not None:
        element.text = str(text)
    return element


def maybe(parent: ET.Element, tag: str, text: str | None, **attrs: str) -> ET.Element | None:
    """Add an element only when there is a value — ISO 20022 omits empty optionals."""
    if text is None or str(text).strip() == "":
        return None
    return sub(parent, tag, str(text), **attrs)


def amount_text(value: Decimal | str | float | int, currency: str) -> str:
    digits = scale_for(currency)
    return f"{quantize(value, currency):.{digits}f}"


def amount(parent: ET.Element, tag: str, value: Decimal, currency: str) -> ET.Element:
    element = sub(parent, tag, amount_text(value, currency))
    element.set("Ccy", currency.upper())
    return element


def party(
    parent: ET.Element,
    tag: str,
    name: str | None,
    country: str | None = None,
    town: str | None = None,
    address_lines: list[str] | None = None,
) -> ET.Element:
    node = sub(parent, tag)
    maybe(node, "Nm", name)
    if country or town or address_lines:
        addr = sub(node, "PstlAdr")
        maybe(addr, "TwnNm", town)
        maybe(addr, "Ctry", country)
        for line in (address_lines or [])[:7]:
            maybe(addr, "AdrLine", line)
    return node


def account(parent: ET.Element, tag: str, iban: str | None, other: str | None = None, currency: str | None = None) -> ET.Element:
    node = sub(parent, tag)
    ident = sub(node, "Id")
    if iban:
        sub(ident, "IBAN", iban)
    else:
        other_node = sub(ident, "Othr")
        sub(other_node, "Id", other or "NOTPROVIDED")
    maybe(node, "Ccy", currency)
    return node


def agent(parent: ET.Element, tag: str, bic: str | None, name: str | None = None, country: str | None = None,
          clearing_code: str | None = None, clearing_system: str | None = None) -> ET.Element:
    node = sub(parent, tag)
    fi = sub(node, "FinInstnId")
    maybe(fi, "BICFI", bic)
    if clearing_code:
        cms = sub(fi, "ClrSysMmbId")
        if clearing_system:
            cs = sub(cms, "ClrSysId")
            sub(cs, "Cd", clearing_system)
        sub(cms, "MmbId", clearing_code)
    maybe(fi, "Nm", name)
    if country:
        addr = sub(fi, "PstlAdr")
        sub(addr, "Ctry", country)
    return node


def serialise(root: ET.Element) -> str:
    """Pretty-printed XML with declaration."""
    _indent(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _indent(element: ET.Element, level: int = 0) -> None:
    pad = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = pad + "  "
        for child in element:
            _indent(child, level + 1)
        if not element.tail or not element.tail.strip():
            element.tail = pad
        if not element[-1].tail or not element[-1].tail.strip():
            element[-1].tail = pad + "  "
        element[-1].tail = pad
    elif level and (not element.tail or not element.tail.strip()):
        element.tail = pad


def local_name(tag: str) -> str:
    """Strip any `{namespace}` prefix a parsed element carries."""
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def element_paths(root: ET.Element) -> dict[str, str]:
    """Flatten a message into {path: text} for the field-validation view.

    Paths are namespace-free (`FIToFICstmrCdtTrf/GrpHdr/MsgId`) so they read the
    same way the ISO 20022 message definition writes them.
    """
    out: dict[str, str] = {}

    def walk(node: ET.Element, prefix: str) -> None:
        for child in node:
            name = local_name(child.tag)
            path = f"{prefix}/{name}" if prefix else name
            if len(child):
                walk(child, path)
            else:
                out[path] = (child.text or "").strip()
            for attr, value in child.attrib.items():
                if attr.startswith("xmlns"):
                    continue
                out[f"{path}/@{local_name(attr)}"] = value

    for child in root:
        walk(child, local_name(child.tag))
    return out
