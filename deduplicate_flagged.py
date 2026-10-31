#!/usr/bin/env python3
import csv
import os
from collections import OrderedDict

def deduplicate_flagged_csv(input_file, output_file):
    """
    Remove rows where entire attribute cells are duplicate from other rows.
    Keep only one instance of each unique full row (based on all columns from ais_position_course onward).
    """
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        return
    
    seen_rows = OrderedDict()
    
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        for row in reader:
            if not row:
                continue
            # Use all columns from index 6 onward (ais_position_course and beyond) as the key
            # These are the actual attribute values
            data_key = tuple(row[6:]) if len(row) > 6 else tuple(row)
            if data_key not in seen_rows:
                seen_rows[data_key] = row
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in seen_rows.values():
            writer.writerow(row)
    
    print(f"Processed {input_file}: {len(seen_rows)} unique rows (out of original)")

# Process both files
deduplicate_flagged_csv('/tmp/attachments/workspace_e36f4467-c355-4d96-b3af-35ff76176958/1be735fd-d9fa-4be6-ad7e-8269d85bb681/79a8183c-d62b-4960-bf2a-dea10a76735b/c6061cfc-bd9d-4115-a46f-0aa9d5ec84cf.csv', 
                       '/workspace/app/flaggedpositioncells2024_dedup.csv')
deduplicate_flagged_csv('/tmp/attachments/workspace_e36f4467-c355-4d96-b3af-35ff76176958/1be735fd-d9fa-4be6-ad7e-8269d85bb681/79a8183c-d62b-4960-bf2a-dea10a76735b/0946e4c1-dd1f-4796-82dd-783e0e0ca611.csv', 
                       '/workspace/app/flaggedpositioncells2025_dedup.csv')
