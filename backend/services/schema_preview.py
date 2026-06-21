"""
Lightweight XML parser for schema preview in the UI.
Only extracts field names, types, labels, and key info — no XDM mapping or payload building.
The full parse_schema_to_xdm conversion is reserved for the migration extraction job.
"""

import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _bool(val: str | None) -> bool:
    return (val or "0") == "1" or (val or "").lower() == "true"


def parse_schema_preview(xml_text: str, namespace: str, name: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    # Find the schema/srcSchema element
    schema_el = None
    for el in root.iter():
        tag = _local(el.tag)
        if tag in ("schema", "srcSchema"):
            if el.get("namespace") == namespace and el.get("name") == name:
                schema_el = el
                break
    if schema_el is None:
        for el in root.iter():
            if _local(el.tag) in ("schema", "srcSchema"):
                schema_el = el
                break
    if schema_el is None:
        return {}

    # Find the main element (child with same name as schema)
    main_el = schema_el
    for child in schema_el:
        if _local(child.tag) == "element" and child.get("name") == name:
            main_el = child
            break

    # Attributes (columns)
    attributes = []
    for attr in main_el:
        if _local(attr.tag) != "attribute":
            continue
        attributes.append({
            "name":  attr.get("name"),
            "type":  attr.get("type") or "string",
            "label": attr.get("label"),
        })

    # Keys — just enough for the PK badge in the UI
    primary_keys = []
    unique_keys = []
    for key_el in main_el:
        if _local(key_el.tag) != "key":
            continue
        fields = [
            kf.get("xpath", "").lstrip("@")
            for kf in key_el if _local(kf.tag) == "keyfield"
        ]
        if _bool(key_el.get("internal")):
            primary_keys.append({"fields": fields})
        else:
            unique_keys.append({"fields": fields})

    return {
        "namespace": namespace,
        "name": name,
        "label": schema_el.get("label"),
        "attributes": attributes,
        "keys": {
            "autoPk": {
                "enabled": _bool(schema_el.get("autopk")),
                "field": schema_el.get("pkSequence"),
            },
            "primaryKeys": primary_keys,
            "uniqueKeys": unique_keys,
        },
    }
