"""
ACC → AJO DDL converter.

# ─────────────────────────────────────────────────────────────────────────────
# FORMAT ASSUMPTION (start)
# The input file is assumed to be Adobe Campaign Classic (ACC) XML schema format.
# Each table is defined as a <srcSchema> element with <element> and <attribute>
# children.  Multiple <srcSchema> elements can be present in one file, wrapped
# in any root element (e.g. <schemas>), or a single <srcSchema> can be the root.
#
# If the input format changes (e.g. to SQL DDL, JSON, or CSV), replace:
#   1. parse_acc_file()        – the entry-point that reads the raw bytes
#   2. _parse_schema()         – maps a single schema unit to our internal dict
#   3. _extract_columns()      – walks the format's field/attribute structure
#   4. ACC_TYPE_MAP             – source-type → PostgreSQL-type mapping table
#
# Everything below generate_ajo_ddl() is format-agnostic and need not change.
# ─────────────────────────────────────────────────────────────────────────────
# FORMAT ASSUMPTION (end)
"""

import logging
import xml.etree.ElementTree as ET
from typing import Optional

log = logging.getLogger("acc_backend.parser")

# ─────────────────────────────────────────────────────────────────────────────
# FORMAT ASSUMPTION: type mapping is specific to ACC XML attribute types.
# Key   = value of the `type` attribute on an ACC <attribute> element.
# Value = callable(length) → PostgreSQL type string.
# Add/change entries here if the source format uses different type names.
# ─────────────────────────────────────────────────────────────────────────────
ACC_TYPE_MAP: dict[str, callable] = {
    "string":   lambda length: f"VARCHAR({length or 255})",
    "long":     lambda _: "BIGINT",
    "int":      lambda _: "INTEGER",
    "integer":  lambda _: "INTEGER",
    "short":    lambda _: "SMALLINT",
    "byte":     lambda _: "SMALLINT",
    "double":   lambda _: "DOUBLE PRECISION",
    "float":    lambda _: "REAL",
    "boolean":  lambda _: "BOOLEAN",
    "datetime": lambda _: "TIMESTAMP",
    "date":     lambda _: "DATE",
    "time":     lambda _: "TIME",
    "memo":     lambda _: "TEXT",
    "text":     lambda _: "TEXT",
    "blob":     lambda _: "BYTEA",
    "uuid":     lambda _: "UUID",
}

# AJO requires these two columns on every table.
# They are appended if not already present in the source schema.
AJO_REQUIRED_COLUMNS: dict[str, str] = {
    "lastmodified":         "TIMESTAMP NOT NULL DEFAULT NOW()",
    "_change_request_type": "VARCHAR(10)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def parse_acc_file(xml_content: bytes) -> list[dict]:
    """
    # FORMAT ASSUMPTION: input bytes are ACC XML.
    # Replace this function if the source format changes.
    #
    # Returns a list of table-definition dicts, one per <srcSchema>.
    # Each dict: { table_name, columns, primary_keys, foreign_keys }
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    # Handle both a single <srcSchema> root and a wrapper containing many.
    if root.tag == "srcSchema":
        schema_elements = [root]
    else:
        schema_elements = root.findall(".//srcSchema")

    if not schema_elements:
        raise ValueError("No <srcSchema> elements found in the uploaded file.")

    log.info("Parsing %d schema(s) from ACC XML", len(schema_elements))
    return [_parse_schema(el) for el in schema_elements]


def generate_ajo_ddl(tables: list[dict]) -> str:
    """
    Convert parsed table definitions into AJO-compatible PostgreSQL DDL.
    Ensures each table has the AJO-required columns (lastmodified, _change_request_type).
    This function is format-agnostic — it works on the internal dict structure.
    """
    statements = []

    for table in tables:
        table_name = table["table_name"]
        columns: list[dict] = list(table["columns"])
        primary_keys: list[str] = table["primary_keys"]
        foreign_keys: list[dict] = table["foreign_keys"]

        existing_col_names = {c["name"].lower() for c in columns}

        # Inject AJO-required columns if missing
        for col_name, col_def in AJO_REQUIRED_COLUMNS.items():
            if col_name.lower() not in existing_col_names:
                columns.append({
                    "name": col_name,
                    "sql_type": col_def,
                    "not_null": False,
                    "_ajo_injected": True,
                })

        col_lines = []
        for col in columns:
            sql_type = col["sql_type"]
            line = f"    {col['name']} {sql_type}"
            if col.get("not_null") and "NOT NULL" not in sql_type:
                line += " NOT NULL"
            col_lines.append(line)

        if primary_keys:
            col_lines.append(f"    PRIMARY KEY ({', '.join(primary_keys)})")

        for fk in foreign_keys:
            if fk.get("dst_table") and fk.get("dst_field") and fk.get("src_field"):
                col_lines.append(
                    f"    FOREIGN KEY ({fk['src_field']}) "
                    f"REFERENCES {fk['dst_table']}({fk['dst_field']})"
                )

        stmt = (
            f"-- Table: {table_name}\n"
            f"CREATE TABLE {table_name} (\n"
            + ",\n".join(col_lines)
            + "\n);"
        )
        statements.append(stmt)

    return "\n\n".join(statements)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers  (FORMAT ASSUMPTION: all ACC XML specific)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_schema(schema_el: ET.Element) -> dict:
    """
    # FORMAT ASSUMPTION: schema_el is an ACC <srcSchema> XML element.
    # namespace + name attributes form the table name.
    """
    name = schema_el.get("name", "unknown")
    namespace = schema_el.get("namespace", "")
    table_name = f"{namespace}_{name}" if namespace else name

    # Collect enumerations defined in this schema
    enumerations: dict[str, list[str]] = {}
    for enum_el in schema_el.findall("enumeration"):
        enum_name = enum_el.get("name", "")
        values = [v.get("name") for v in enum_el.findall("value") if v.get("name")]
        if enum_name and values:
            enumerations[enum_name] = values

    # The primary data element has the same name as the schema
    main_el = schema_el.find(f"element[@name='{name}']")
    if main_el is None:
        main_el = schema_el.find("element")

    columns: list[dict] = []
    primary_keys: list[str] = []
    foreign_keys: list[dict] = []

    if main_el is not None:
        # Primary keys come from <key><keyfield xpath="@field"/></key>
        for key_el in main_el.findall("key"):
            for kf in key_el.findall("keyfield"):
                xpath = kf.get("xpath", "")
                if xpath.startswith("@"):
                    primary_keys.append(xpath[1:])

        # Columns — flatten nested <element> children with a prefix
        _extract_columns(main_el, columns, enumerations, prefix="")

        # Foreign keys come from <join xpath-src="..." xpath-dst="..."/>
        for join_el in main_el.findall(".//join"):
            src = join_el.get("xpath-src", "")
            dst = join_el.get("xpath-dst", "")
            if src and dst:
                dst_parts = dst.split("/@")
                foreign_keys.append({
                    "src_field": src.lstrip("@"),
                    "dst_table": dst_parts[0].lstrip("/") if dst_parts else "",
                    "dst_field": dst_parts[1] if len(dst_parts) > 1 else "",
                })

    log.debug("Parsed table '%s': %d columns, %d PKs", table_name, len(columns), len(primary_keys))
    return {
        "table_name": table_name,
        "columns": columns,
        "primary_keys": primary_keys,
        "foreign_keys": foreign_keys,
    }


def _extract_columns(element: ET.Element, columns: list, enumerations: dict, prefix: str):
    """
    # FORMAT ASSUMPTION: columns are ACC <attribute> elements; nested tables
    # are ACC <element> children (flattened with a name prefix).
    """
    for attr in element.findall("attribute"):
        col = _parse_attribute(attr, enumerations, prefix)
        if col:
            columns.append(col)

    for child_el in element.findall("element"):
        child_name = child_el.get("name", "")
        _extract_columns(child_el, columns, enumerations, prefix=f"{prefix}{child_name}_" if child_name else prefix)


def _parse_attribute(attr: ET.Element, enumerations: dict, prefix: str) -> Optional[dict]:
    """
    # FORMAT ASSUMPTION: field metadata comes from ACC <attribute> XML attributes:
    #   name, type, length/size, enum, required/notNull.
    """
    name = attr.get("name", "").strip()
    if not name:
        return None

    col_name = f"{prefix}{name}"
    acc_type = attr.get("type", "string").lower()
    length_raw = attr.get("length") or attr.get("size")
    length = int(length_raw) if length_raw and length_raw.isdigit() else None
    enum_name = attr.get("enum", "")
    not_null = (
        attr.get("required", "false").lower() == "true"
        or attr.get("notNull", "false").lower() == "true"
    )

    if enum_name and enum_name in enumerations:
        values_str = ", ".join(f"'{v}'" for v in enumerations[enum_name])
        sql_type = f"TEXT CHECK ({col_name} IN ({values_str}))"
    else:
        type_fn = ACC_TYPE_MAP.get(acc_type)
        if type_fn is None:
            log.warning("Unknown ACC type '%s' for column '%s' — defaulting to TEXT", acc_type, col_name)
            sql_type = "TEXT"
        else:
            sql_type = type_fn(length)

    return {"name": col_name, "sql_type": sql_type, "not_null": not_null}
