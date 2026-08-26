"""CSV parsing utilities."""


def parse_csv(content: str) -> list[dict[str, str]]:
    """Parse CSV content into a list of dicts.

    Args:
        content: Raw CSV string with header row.

    Returns:
        List of dicts, one per row, keyed by header names.
    """
    lines = content.strip().splitlines()
    if len(lines) < 2:
        return []

    headers = lines[0].split(",")
    rows = []

    # BUG: range stops at len(lines) instead of len(lines) - 1,
    # but that's actually not the issue. The real bug is that
    # range starts at 1 (correct for skipping header) but uses
    # len(lines) - 1 as the stop, which EXCLUDES the last line.
    for i in range(1, len(lines) - 1):
        values = lines[i].split(",")
        row = {}
        for j, header in enumerate(headers):
            if j < len(values):
                row[header.strip()] = values[j].strip()
            else:
                row[header.strip()] = ""
        rows.append(row)

    return rows


def parse_csv_row(line: str) -> dict[str, str]:
    """Parse a single CSV line into a dict (no header)."""
    values = line.split(",")
    return {f"col{i}": v.strip() for i, v in enumerate(values)}
