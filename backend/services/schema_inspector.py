"""
Parse ACC srcSchema XML into a structured JSON matching the XDM inspection format.
"""

import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _bool(val: str | None) -> bool:
    return (val or "0") == "1" or (val or "").lower() == "true"


def parse_schema_to_xdm(xml_text: str, namespace: str, name: str) -> dict:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    # Find schema/srcSchema element
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

    full_name = f"{namespace}:{name}"
    schema_type = _local(schema_el.tag)  # srcSchema or schema

    # Find main element (child with same name as schema)
    main_el = schema_el
    for child in schema_el:
        if _local(child.tag) == "element" and child.get("name") == name:
            main_el = child
            break

    # ── source ───────────────────────────────────────────────────────────────
    source = {
        "schemaType":     f"xtk:{schema_type}",
        "fullName":       full_name,
        "namespace":      namespace,
        "name":           name,
        "rawXmlCaptured": True,
    }

    # ── schema ────────────────────────────────────────────────────────────────
    schema = {
        "mainPageName":   schema_el.get("img"),
        "label":          schema_el.get("label"),
        "labelSingular":  schema_el.get("labelSingular") or schema_el.get("labelsingular"),
        "description":    schema_el.get("desc"),
        "mappingType":    schema_el.get("mappingType") or "sql",
        "entitySchema":   schema_el.get("entitySchema") or schema_el.get("xtkschema"),
        "type":           schema_el.get("type") or "sql",
        "view":           _bool(schema_el.get("view")),
        "library":        _bool(schema_el.get("library")),
        "extendedSchema": schema_el.get("extends"),
        "implements":     schema_el.get("implements"),
        "doNotPersist":   _bool(schema_el.get("doNotPersist")),
        "genAccessors":   schema_el.get("genAccessors"),
    }

    # ── rootElement ───────────────────────────────────────────────────────────
    sub_elements = [c for c in main_el if _local(c.tag) == "element"]
    collections  = [c for c in main_el if _local(c.tag) == "element" and c.get("unbound") == "true"]
    hier_rels = []
    for c in main_el:
        if _local(c.tag) == "element" and c.get("type") == "link":
            hier_rels.append(c.get("name"))

    root_element = {
        "name":         main_el.get("name") or name,
        "label":        main_el.get("label") or schema_el.get("label"),
        "sqlTable":     schema_el.get("sqltable") or schema_el.get("sqltablename"),
        "isRootEntity": True,
        "hierarchy": {
            "hasSubElements":        len(sub_elements) > 0,
            "hasCollections":        len(collections) > 0,
            "hierarchicalRelations": hier_rels,
        },
    }

    # ── elements ──────────────────────────────────────────────────────────────
    elements = []
    for el in main_el:
        if _local(el.tag) != "element" or el.get("type") == "link":
            continue
        elem_attrs = []
        for a in el:
            if _local(a.tag) == "attribute":
                elem_attrs.append(a.get("name"))
        elem_links = []
        for a in el:
            if _local(a.tag) == "element" and a.get("type") == "link":
                elem_links.append(a.get("name"))
        elements.append({
            "name":    el.get("name"),
            "label":   el.get("label"),
            "xpath":   f"@{el.get('name')}",
            "type":    el.get("type") or "element",
            "storage": {
                "xml": _bool(el.get("xml")),
                "sql": not _bool(el.get("xml")),
            },
            "children":   [],
            "attributes": elem_attrs,
            "links":      elem_links,
        })

    # ── attributes ────────────────────────────────────────────────────────────
    attributes = []
    for attr in main_el:
        if _local(attr.tag) != "attribute":
            continue
        attributes.append({
            "name":         attr.get("name"),
            "label":        attr.get("label"),
            "xpath":        f"@{attr.get('name')}",
            "type":         attr.get("type") or "string",
            "length":       attr.get("length"),
            "sqlName":      attr.get("sqlname") or attr.get("sqlfieldname") or attr.get("name"),
            "description":  attr.get("desc"),
            "required":     _bool(attr.get("required")),
            "nullable":     not _bool(attr.get("notNull")),
            "notNull":      _bool(attr.get("notNull")),
            "defaultValue": attr.get("default"),
            "expression":   attr.get("expr"),
            "isCalculated": attr.get("expr") is not None,
            "enumReference": attr.get("enum"),
            "xml":          _bool(attr.get("xml")),
            "behavior": {
                "availableBehavior": [],
                "dataPolicy":   attr.get("dataPolicy"),
                "readOnly":     _bool(attr.get("readOnly")),
                "persistent":   not _bool(attr.get("doNotPersist")),
                "templateRef":  attr.get("template"),
            },
        })

    # ── keys ─────────────────────────────────────────────────────────────────
    primary_keys = []
    logical_keys = []
    unique_keys  = []

    for key_el in main_el:
        if _local(key_el.tag) != "key":
            continue
        fields = [kf.get("xpath", "").lstrip("@")
                  for kf in key_el if _local(kf.tag) == "keyfield"]
        key_entry = {
            "name":     key_el.get("name"),
            "internal": _bool(key_el.get("internal")),
            "fields":   fields,
        }
        if _bool(key_el.get("internal")):
            primary_keys.append(key_entry)
        elif _bool(key_el.get("noDbIndex")):
            logical_keys.append(key_entry)
        else:
            unique_keys.append(key_entry)

    keys = {
        "autoPk": {
            "enabled": _bool(schema_el.get("autopk")),
            "field":   schema_el.get("pkSequence"),
        },
        "primaryKeys":          primary_keys,
        "logicalKeys":          logical_keys,
        "uniqueKeys":           unique_keys,
        "compositeKeys":        [],
        "authorKeys":           [],
        "foreignKeyStructures": [],
    }

    # ── linksAndJoins ─────────────────────────────────────────────────────────
    links = []
    for el in main_el:
        if _local(el.tag) != "element" or el.get("type") != "link":
            continue
        src = dst = ""
        for join in el:
            if _local(join.tag) == "join":
                src = join.get("xpath-src", "").lstrip("@")
                dst = join.get("xpath-dst", "").lstrip("@")
        links.append({
            "name":            el.get("name"),
            "label":           el.get("label"),
            "targetSchema":    el.get("target"),
            "reverseLinkName": el.get("revLink"),
            "sourceLinkName":  el.get("name"),
            "join": {
                "sourceField":      src,
                "destinationField": dst,
                "composite":        False,
            },
            "cardinality":      el.get("cardinality") or "N:1",
            "integrity":        el.get("integrity"),
            "reverseIntegrity": el.get("reverseIntegrity"),
            "sourceLabel":      el.get("label"),
            "destinationLabel": el.get("revLabel"),
        })

    # ── enums ─────────────────────────────────────────────────────────────────
    enums = []
    for en in schema_el:
        if _local(en.tag) != "enumeration":
            continue
        values = []
        for v in en:
            if _local(v.tag) == "value":
                values.append({
                    "name":  v.get("name"),
                    "value": v.get("value"),
                    "label": v.get("label") or v.get("name"),
                })
        enums.append({
            "name":        en.get("name"),
            "type":        en.get("type") or "systemEnum",
            "description": en.get("desc"),
            "values":      values,
        })

    return {
        "source":       source,
        "schema":       schema,
        "rootElement":  root_element,
        "elements":     elements,
        "attributes":   attributes,
        "keys":         keys,
        "linksAndJoins": links,
        "enums":        enums,
        "extractionNotes": {
            "fromSrcSchemaOnly": True,
            "compiledSchemaRequiredForGeneratedDefaults": True,
            "databaseMetadataRequiredForPhysicalIndexesAndRealFKs": True,
        },
    }
