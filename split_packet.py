#!/usr/bin/env python3
"""Split a Jersey City Council meeting packet PDF into individual PDFs per agenda item.

Usage:
    python3 split_packet.py <packet.pdf> <agenda_parsed.json> <output_dir>

Example:
    python3 split_packet.py 2026/02-11/packet.pdf 2026/02-11/agenda_parsed.json 2026/02-11/split/
"""

import sys
import os
import json
import re
import fitz  # PyMuPDF


# Map section types to output subdirectory names
SECTION_DIR_MAP = {
    "ordinance_first_reading": "ordinances",
    "ordinance_second_reading": "ordinances",
    "resolutions": "resolutions",
    "claims": "claims",
}


def sanitize_filename(s):
    """Replace characters that are problematic in filenames.
    'Ord. 26-006' -> 'Ord-26-006'
    """
    s = re.sub(r'\.\s*', '-', s)  # "Ord. " -> "Ord-"
    s = re.sub(r'\s+', '-', s)    # remaining spaces
    s = re.sub(r'[^\w\-]', '', s) # remove anything else
    s = re.sub(r'-+', '-', s)     # collapse multiple dashes
    return s.strip('-')


def build_filename(item):
    """Build output filename for an agenda item."""
    # Zero-pad item number: "3.1" -> "03.01", "10.22" -> "10.22"
    parts = item["item_number"].split(".")
    padded = f"{int(parts[0]):02d}.{int(parts[1]):02d}"

    itype = item["item_type"]
    file_num = item.get("file_number")

    if file_num:
        safe_num = sanitize_filename(file_num)
        return f"{padded}_{itype}_{safe_num}.pdf"
    else:
        return f"{padded}_{itype}.pdf"


def subdir_for_item(item, section_type):
    """Determine the output subdirectory for an item."""
    return SECTION_DIR_MAP.get(section_type, "other")


def validate_split(packet_doc, item, page_start_0, page_end_0):
    """Validate that the split pages match expected content.

    Checks the first content page (skipping cover page) for the expected
    file number (Ord./Res.) to confirm correct splitting.
    """
    file_number = item.get("file_number")
    if not file_number:
        return True  # No file number to validate against

    # Normalize for matching: "Ord. 26-006" -> "Ord. 26-006" or "Ord.26-006"
    norm = file_number.replace(" ", "")

    # Check first few pages of the range for the file number
    for pg in range(page_start_0, min(page_end_0 + 1, page_start_0 + 3)):
        text = packet_doc[pg].get_text("text")
        text_norm = text.replace(" ", "")
        if norm in text_norm:
            return True

    return False


def split_packet(packet_path, agenda_path, output_dir):
    """Split packet PDF based on agenda JSON."""
    with open(agenda_path) as f:
        agenda = json.load(f)

    packet = fitz.open(packet_path)
    total_packet_pages = len(packet)
    agenda_pages = agenda.get("agenda_pages", 9)

    print(f"Packet: {total_packet_pages} pages")
    print(f"Agenda: {agenda_pages} pages")

    # Collect all items that have page ranges
    items_to_split = []
    for section in agenda["sections"]:
        sec_type = section["type"]
        for item in section["items"]:
            if item["page_start"] is not None and item["page_end"] is not None:
                items_to_split.append((item, sec_type))

    # Sort by page_start
    items_to_split.sort(key=lambda x: x[0]["page_start"])

    # Create output directories
    os.makedirs(os.path.join(output_dir, "agenda"), exist_ok=True)
    for subdir in set(SECTION_DIR_MAP.values()):
        os.makedirs(os.path.join(output_dir, subdir), exist_ok=True)

    manifest_entries = []
    total_pages_split = 0
    warnings = []

    # 1. Extract the agenda itself (pages 1 through agenda_pages)
    agenda_out = fitz.open()
    agenda_out.insert_pdf(packet, from_page=0, to_page=agenda_pages - 1)
    agenda_file = os.path.join(output_dir, "agenda", "00.00_agenda.pdf")
    agenda_out.save(agenda_file)
    agenda_page_count = agenda_pages
    agenda_out.close()
    total_pages_split += agenda_page_count

    manifest_entries.append({
        "item_number": "0.0",
        "title": "Agenda",
        "item_type": "agenda",
        "file_number": None,
        "page_start": 1,
        "page_end": agenda_pages,
        "page_count": agenda_page_count,
        "output_file": os.path.join("agenda", "00.00_agenda.pdf"),
    })

    print(f"\nExtracted agenda: pages 1-{agenda_pages} ({agenda_page_count} pages)")

    # 2. Extract each agenda item
    for item, sec_type in items_to_split:
        page_start = item["page_start"]  # 1-indexed
        page_end = item["page_end"]      # 1-indexed

        # Convert to 0-indexed for PyMuPDF
        start_0 = page_start - 1
        end_0 = page_end - 1

        # Bounds check
        if start_0 < 0 or end_0 >= total_packet_pages:
            msg = f"WARNING: Item {item['item_number']} pages {page_start}-{page_end} out of bounds (packet has {total_packet_pages} pages)"
            warnings.append(msg)
            print(msg)
            continue

        # Validate content
        if not validate_split(packet, item, start_0, end_0):
            msg = f"WARNING: Item {item['item_number']} - file number '{item.get('file_number')}' not found in pages {page_start}-{page_end}"
            warnings.append(msg)
            print(msg)

        # Extract
        out_doc = fitz.open()
        out_doc.insert_pdf(packet, from_page=start_0, to_page=end_0)

        subdir = subdir_for_item(item, sec_type)
        filename = build_filename(item)
        rel_path = os.path.join(subdir, filename)
        full_path = os.path.join(output_dir, rel_path)

        out_doc.save(full_path)
        page_count = end_0 - start_0 + 1
        out_doc.close()
        total_pages_split += page_count

        manifest_entries.append({
            "item_number": item["item_number"],
            "title": item["title"],
            "item_type": item["item_type"],
            "file_number": item.get("file_number"),
            "page_start": page_start,
            "page_end": page_end,
            "page_count": page_count,
            "output_file": rel_path,
        })

        print(f"  {item['item_number']:6s} pages {page_start:3d}-{page_end:3d} ({page_count:3d} pp) -> {rel_path}")

    # 3. Write manifest
    manifest = {
        "meeting": agenda.get("meeting", {}),
        "packet_pages": total_packet_pages,
        "files_created": len(manifest_entries),
        "total_pages_split": total_pages_split,
        "warnings": warnings,
        "items": manifest_entries,
    }

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # 4. Summary
    print(f"\nSummary:")
    print(f"  Files created: {len(manifest_entries)}")
    print(f"  Total pages split: {total_pages_split}")
    if total_pages_split == total_packet_pages:
        print(f"  Coverage: COMPLETE ({total_packet_pages}/{total_packet_pages} pages)")
    else:
        print(f"  Coverage: {total_pages_split}/{total_packet_pages} pages ({total_packet_pages - total_pages_split} pages unaccounted)")
    if warnings:
        print(f"  Warnings: {len(warnings)}")
        for w in warnings:
            print(f"    {w}")

    print(f"  Manifest written to {manifest_path}")

    packet.close()


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <packet.pdf> <agenda_parsed.json> <output_dir>")
        sys.exit(1)

    packet_path = sys.argv[1]
    agenda_path = sys.argv[2]
    output_dir = sys.argv[3]

    split_packet(packet_path, agenda_path, output_dir)


if __name__ == "__main__":
    main()
