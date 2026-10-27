import csv
import logging
from io import StringIO

logger = logging.getLogger(__name__)


def _build_header_mapping(csv_headers):
    """
    Build a mapping from actual CSV headers to internal field names.

    Supports three header formats from GAM CSV_DUMP exports:
    1. Prefixed canonical: "Dimension.DATE", "Column.AD_EXCHANGE_..."
    2. Unprefixed canonical: "DATE", "AD_EXCHANGE_..."
    3. Display names: "Ad unit 1", "Ad unit", "Date", "Custom criteria", etc.
    """
    # Canonical column name -> internal field name
    # Only AD_EXCHANGE columns are fetched; they map directly to final field names
    canonical_mapping = {
        "DATE": "date",
        "AD_UNIT_NAME": "domain",
        "CUSTOM_CRITERIA": "custom_criteria",
        "CHILD_NETWORK_CODE": "child_network_code",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS": "impressions",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS": "clicks",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE": "revenue",
        "AD_EXCHANGE_LINE_ITEM_LEVEL_AVERAGE_ECPM": "ecpm",
    }

    # Display name -> internal field name (GAM sometimes returns human-readable headers)
    display_name_mapping = {
        "date": "date",
        "ad unit 1": "domain",
        "ad unit": "domain",
        "ad unit name": "domain",
        "custom criteria": "custom_criteria",
        "child network code": "child_network_code",
        "ad exchange impressions": "impressions",
        "ad exchange clicks": "clicks",
        "ad exchange revenue": "revenue",
        "ad exchange average ecpm": "ecpm",
    }

    header_mapping = {}
    for csv_header in csv_headers:
        # 1. Try canonical match (with optional prefix stripping)
        stripped = csv_header
        if '.' in csv_header:
            stripped = csv_header.split('.', 1)[1]

        if stripped in canonical_mapping:
            header_mapping[csv_header] = canonical_mapping[stripped]
            continue

        # 2. Try display name match (case-insensitive)
        lower_header = csv_header.strip().lower()
        if lower_header in display_name_mapping:
            header_mapping[csv_header] = display_name_mapping[lower_header]

    return header_mapping


def csvToJson(lines):
    """Converte um arquivo CSV em JSON usando headers customizados."""
    if not lines or len(lines) < 2:
        logger.info("csvToJson: received empty or single-line CSV, returning []")
        return []

    # --- TEMPORARY DEBUG: log raw CSV headers ---
    raw_header_line = lines[0] if lines else "<EMPTY>"
    logger.info(f"CSV HEADERS RAW: {raw_header_line}")
    if len(lines) > 1:
        logger.info(f"CSV FIRST DATA ROW RAW: {lines[1]}")
    # --- END TEMPORARY DEBUG ---

    # Campos de metricas que precisam de conversao numerica
    metric_fields = ['impressions', 'clicks', 'revenue', 'ecpm']

    # Campos monetarios que vem em micro-unidades (dividir por 1.000.000)
    micro_fields = ['ecpm', 'revenue']

    csv_reader = csv.DictReader(StringIO('\n'.join(lines)))

    # Build header mapping dynamically from actual CSV headers
    csv_headers = csv_reader.fieldnames or []
    header_mapping = _build_header_mapping(csv_headers)

    if not header_mapping:
        logger.warning(
            f"No CSV headers matched the expected mapping. "
            f"CSV headers found: {csv_headers}"
        )
        return []

    logger.info(f"CSV header mapping resolved: {header_mapping}")
    unmapped = [h for h in csv_headers if h not in header_mapping]
    if unmapped:
        logger.info(f"CSV headers NOT mapped (ignored): {unmapped}")

    json_data = []
    for row in csv_reader:
        mapped_row = {}

        for original_header, value in row.items():
            if original_header in header_mapping:
                new_header = header_mapping[original_header]
                mapped_row[new_header] = value

        # Trata custom_criteria separadamente (utm_campaign = key-value)
        if 'custom_criteria' in mapped_row:
            custom_criteria = mapped_row.pop('custom_criteria')
            if '=' in custom_criteria:
                parts = custom_criteria.split('=', 1)
                mapped_row['custom_key'] = parts[0].strip()
                mapped_row['custom_value'] = parts[1].strip()
            else:
                mapped_row['custom_key'] = custom_criteria.strip()
                mapped_row['custom_value'] = ''

        # Converte e formata valores numericos
        for field in metric_fields:
            if field in mapped_row:
                try:
                    value = float(mapped_row[field])

                    if field in micro_fields:
                        value = value / 1000000
                        mapped_row[field] = round(value, 6)
                    else:
                        mapped_row[field] = int(value)

                except ValueError:
                    pass

        json_data.append(mapped_row)

    logger.info(f"csvToJson: parsed {len(json_data)} records from {len(lines) - 1} CSV data lines")
    if json_data:
        logger.info(f"csvToJson: SAMPLE first record: {json_data[0]}")

    return json_data
