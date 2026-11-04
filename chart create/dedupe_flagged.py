#!/usr/bin/env python3
"""Remove rows whose attribute cells are duplicated in the flagged position CSVs.

"Attribute cells" = all columns from `ais_position_course` onward (CSV index 6+),
including the flagged `[BAD]`-prefixed values. This keeps exactly one row per
unique attribute signature within each file and writes the result back
(in place: input overwrites itself) unless an output_file is provided.
"""
import csv
import os
from collections import OrderedDict


def deduplicate_flagged_csv(input_file, output_file=None):
    """Remove rows where the entire attribute cells (columns 6 onward) are
    duplicated from other rows, keeping the first occurrence of each.
    """
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        return

    output_file = output_file or input_file
    seen_rows = OrderedDict()
    original = 0

    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)

        for row in reader:
            if not row:
                continue
            original += 1
            data_key = tuple(row[6:]) if len(row) > 6 else tuple(row)
            if data_key not in seen_rows:
                seen_rows[data_key] = row

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if header is not None:
            writer.writerow(header)
        for row in seen_rows.values():
            writer.writerow(row)

    print(f"Processed {input_file}: {len(seen_rows)} unique rows kept "
          f"out of {original} data rows ({original - len(seen_rows)} removed).")


if __name__ == "__main__":
    deduplicate_flagged_csv('/home/haha/Downloads/flaggedpositioncells2024.csv')
    deduplicate_flagged_csv('/home/haha/Downloads/flaggedpositioncells2025.csv')
