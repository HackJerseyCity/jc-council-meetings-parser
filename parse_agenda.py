#!/usr/bin/env python3
"""Parse a Jersey City Council meeting agenda PDF into structured JSON.

Usage:
    python3 parse_agenda.py <agenda.pdf> <output.json>

Example:
    python3 parse_agenda.py 2026/02-11/agenda.pdf 2026/02-11/agenda_parsed.json
"""

import sys
import json
import re
import fitz  # PyMuPDF


def extract_meeting_info(text):
    """Extract meeting type and date from the first page text."""
    info = {"type": "regular", "date": None}

    date_match = re.search(
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+'
        r'((?:January|February|March|April|May|June|July|August|September|'
        r'October|November|December)\s+\d{1,2},\s+\d{4})',
        text
    )
    if date_match:
        from datetime import datetime
        try:
            dt = datetime.strptime(date_match.group(1), "%B %d, %Y")
            info["date"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            info["date"] = date_match.group(1)

    if "Special Meeting" in text:
        info["type"] = "special"
    elif "Regular Meeting" in text:
        info["type"] = "regular"

    return info


def classify_section(number, title):
    """Classify a section by its number and title into a normalized type."""
    title_lower = title.lower().strip()
    if "first reading" in title_lower:
        return "ordinance_first_reading"
    if "second reading" in title_lower or "hearing" in title_lower:
        return "ordinance_second_reading"
    if "claims" in title_lower:
        return "claims"
    if "resolution" in title_lower:
        return "resolutions"
    if "public request" in title_lower:
        return "public_hearing"
    if "petition" in title_lower or "communication" in title_lower:
        return "petitions_communications"
    if "officers" in title_lower:
        return "officers_communications"
    if "reports" in title_lower or "directors" in title_lower:
        return "reports_of_directors"
    if "regular meeting" in title_lower:
        return "regular_meeting"
    if "reception" in title_lower:
        return "reception_bid"
    if "deferred" in title_lower or "tabled" in title_lower:
        return "deferred"
    if "adjournment" in title_lower:
        return "adjournment"
    return "other"


def item_type_from_section(section_type):
    """Derive individual item type from section type."""
    if "ordinance" in section_type:
        return "ordinance"
    if "resolution" in section_type:
        return "resolution"
    if "claims" in section_type:
        return "claims"
    return "other"


def parse_agenda(pdf_path):
    """Parse agenda PDF and return structured data."""
    doc = fitz.open(pdf_path)

    # Extract all text from all pages
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + "\n"

    meeting_info = extract_meeting_info(full_text)
    total_pages = len(doc)

    lines = full_text.split("\n")

    # Regex patterns
    section_re = re.compile(r'^\s*(\d{1,2})\.\s+([A-Z][A-Z\s\-\(\),&]+)')

    # Pattern A: page range + item number + title all on one line
    # e.g., "130 - 136 10.1 A Resolution authorizing..."
    pattern_a = re.compile(
        r'^\s*(\d{1,3})\s*-\s*(\d{1,3})\s+'
        r'(\d{1,2}\.\d{1,2})\s+'
        r'(.+)'
    )

    # Pattern B: page range + item number on same line, title on next line(s)
    # e.g., "106 - 129 9.1 " then "Meeting Claims List"
    pattern_b_range_item = re.compile(
        r'^\s*(\d{1,3})\s*-\s*(\d{1,3})\s+'
        r'(\d{1,2}\.\d{1,2})\s*$'
    )

    # Pattern C: page range alone on one line, item number on next
    # e.g., "10 - 13" then "3.1" then "An Ordinance..."
    pattern_c_range = re.compile(r'^\s*(\d{1,3})\s*-\s*(\d{1,3})\s*$')

    # Item number alone on a line (may have title or not)
    # e.g., "3.1 " or "5.1 " (title on next line)
    item_number_alone = re.compile(r'^\s*(\d{1,2}\.\d{1,2})\s*$')

    # Item number with title on same line (no page range)
    # e.g., "5.10 Eve Taylor" or "8.13 Letter dated..."
    item_with_title = re.compile(r'^\s*(\d{1,2}\.\d{1,2})\s+(.+)')

    # File number pattern
    file_number_re = re.compile(r'((?:Ord|Res)\.\s*\d{2}-\d{3})')

    sections = []
    current_section = None

    # Parse into sections and items using a state machine
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check for section header
        sm = section_re.match(line)
        if sm:
            sec_num = int(sm.group(1))
            sec_title = sm.group(2).strip()
            sec_title = re.sub(r'\s+', ' ', sec_title).rstrip(' -,')
            sec_type = classify_section(sec_num, sec_title)

            if current_section:
                sections.append(current_section)

            current_section = {
                "number": sec_num,
                "title": sec_title,
                "type": sec_type,
                "items": [],
            }
            i += 1
            continue

        if current_section is None:
            i += 1
            continue

        sec_num = current_section["number"]
        sec_type = current_section["type"]
        itype = item_type_from_section(sec_type)

        # Pattern A: "130 - 136 10.1 A Resolution authorizing..."
        ma = pattern_a.match(line)
        if ma:
            candidate_item = ma.group(3)
            if candidate_item.startswith(f"{sec_num}."):
                page_start = int(ma.group(1))
                page_end = int(ma.group(2))
                item_number = candidate_item
                title_parts = [ma.group(4).strip()]
                i += 1
                # Gather continuation lines
                while i < len(lines):
                    nline = lines[i].strip()
                    if not nline:
                        i += 1
                        continue
                    if section_re.match(lines[i]):
                        break
                    if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                        break
                    if file_number_re.match(nline):
                        break
                    # Check if it's a new item number
                    if item_number_alone.match(lines[i]) or item_with_title.match(lines[i]):
                        test_m = item_with_title.match(lines[i]) or item_number_alone.match(lines[i])
                        if test_m and test_m.group(1).startswith(f"{sec_num}."):
                            break
                    title_parts.append(nline)
                    i += 1

                title = " ".join(title_parts)
                title = re.sub(r'\s*(?:Ord|Res)\.\s*\d{2}-\d{3}\s*-?\s*Pdf\s*$', '', title).strip()
                title = re.sub(r'\s+', ' ', title)

                # Look for file number in upcoming lines
                file_number = None
                for j in range(i, min(i + 3, len(lines))):
                    fm = file_number_re.search(lines[j])
                    if fm:
                        file_number = fm.group(1)
                        file_number = re.sub(r'(Ord|Res)\.\s*', r'\1. ', file_number)
                        i = j + 1
                        break

                current_section["items"].append({
                    "item_number": item_number,
                    "title": title,
                    "page_start": page_start,
                    "page_end": page_end,
                    "file_number": file_number,
                    "item_type": itype,
                })
                continue

        # Pattern B: "106 - 129 9.1" (item num on same line as range, no title)
        mb = pattern_b_range_item.match(line)
        if mb:
            candidate_item = mb.group(3)
            if candidate_item.startswith(f"{sec_num}."):
                page_start = int(mb.group(1))
                page_end = int(mb.group(2))
                item_number = candidate_item
                title_parts = []
                i += 1
                # Gather title lines
                while i < len(lines):
                    nline = lines[i].strip()
                    if not nline:
                        i += 1
                        continue
                    if section_re.match(lines[i]):
                        break
                    if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                        break
                    if file_number_re.match(nline):
                        break
                    if item_number_alone.match(lines[i]) or item_with_title.match(lines[i]):
                        test_m = item_with_title.match(lines[i]) or item_number_alone.match(lines[i])
                        if test_m and test_m.group(1).startswith(f"{sec_num}."):
                            break
                    title_parts.append(nline)
                    i += 1

                title = " ".join(title_parts)
                title = re.sub(r'\s*(?:Ord|Res)\.\s*\d{2}-\d{3}\s*-?\s*Pdf\s*$', '', title).strip()
                title = re.sub(r'\s+', ' ', title)

                file_number = None
                for j in range(i, min(i + 3, len(lines))):
                    fm = file_number_re.search(lines[j])
                    if fm:
                        file_number = fm.group(1)
                        file_number = re.sub(r'(Ord|Res)\.\s*', r'\1. ', file_number)
                        i = j + 1
                        break

                current_section["items"].append({
                    "item_number": item_number,
                    "title": title,
                    "page_start": page_start,
                    "page_end": page_end,
                    "file_number": file_number,
                    "item_type": itype,
                })
                continue

        # Pattern C: page range on its own, then item number on next line
        mc = pattern_c_range.match(line)
        if mc:
            page_start = int(mc.group(1))
            page_end = int(mc.group(2))
            i += 1
            # Skip blank lines
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                continue
            # Next non-blank should be the item number
            mi = item_number_alone.match(lines[i])
            mi2 = item_with_title.match(lines[i])
            if mi and mi.group(1).startswith(f"{sec_num}."):
                item_number = mi.group(1)
                i += 1
                # Gather title lines
                title_parts = []
                while i < len(lines):
                    nline = lines[i].strip()
                    if not nline:
                        i += 1
                        continue
                    if section_re.match(lines[i]):
                        break
                    if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                        break
                    if file_number_re.match(nline):
                        break
                    if item_number_alone.match(lines[i]) or item_with_title.match(lines[i]):
                        test_m = item_with_title.match(lines[i]) or item_number_alone.match(lines[i])
                        if test_m and test_m.group(1).startswith(f"{sec_num}."):
                            break
                    title_parts.append(nline)
                    i += 1

                title = " ".join(title_parts)
                title = re.sub(r'\s*(?:Ord|Res)\.\s*\d{2}-\d{3}\s*-?\s*Pdf\s*$', '', title).strip()
                title = re.sub(r'\s+', ' ', title)

                file_number = None
                for j in range(i, min(i + 3, len(lines))):
                    fm = file_number_re.search(lines[j])
                    if fm:
                        file_number = fm.group(1)
                        file_number = re.sub(r'(Ord|Res)\.\s*', r'\1. ', file_number)
                        i = j + 1
                        break

                current_section["items"].append({
                    "item_number": item_number,
                    "title": title,
                    "page_start": page_start,
                    "page_end": page_end,
                    "file_number": file_number,
                    "item_type": itype,
                })
                continue
            elif mi2 and mi2.group(1).startswith(f"{sec_num}."):
                # Item number + title on same line after page range
                item_number = mi2.group(1)
                title_parts = [mi2.group(2).strip()]
                i += 1
                while i < len(lines):
                    nline = lines[i].strip()
                    if not nline:
                        i += 1
                        continue
                    if section_re.match(lines[i]):
                        break
                    if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                        break
                    if file_number_re.match(nline):
                        break
                    if item_number_alone.match(lines[i]) or item_with_title.match(lines[i]):
                        test_m = item_with_title.match(lines[i]) or item_number_alone.match(lines[i])
                        if test_m and test_m.group(1).startswith(f"{sec_num}."):
                            break
                    title_parts.append(nline)
                    i += 1

                title = " ".join(title_parts)
                title = re.sub(r'\s*(?:Ord|Res)\.\s*\d{2}-\d{3}\s*-?\s*Pdf\s*$', '', title).strip()
                title = re.sub(r'\s+', ' ', title)

                file_number = None
                for j in range(i, min(i + 3, len(lines))):
                    fm = file_number_re.search(lines[j])
                    if fm:
                        file_number = fm.group(1)
                        file_number = re.sub(r'(Ord|Res)\.\s*', r'\1. ', file_number)
                        i = j + 1
                        break

                current_section["items"].append({
                    "item_number": item_number,
                    "title": title,
                    "page_start": page_start,
                    "page_end": page_end,
                    "file_number": file_number,
                    "item_type": itype,
                })
                continue

        # Items without page ranges

        # Item number alone on a line, title on next line(s)
        mi = item_number_alone.match(line)
        if mi and mi.group(1).startswith(f"{sec_num}."):
            item_number = mi.group(1)
            i += 1
            title_parts = []
            while i < len(lines):
                nline = lines[i].strip()
                if not nline:
                    i += 1
                    continue
                if section_re.match(lines[i]):
                    break
                if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                    break
                if file_number_re.match(nline):
                    break
                if item_number_alone.match(lines[i]):
                    test_m = item_number_alone.match(lines[i])
                    if test_m and test_m.group(1).startswith(f"{sec_num}."):
                        break
                if item_with_title.match(lines[i]):
                    test_m = item_with_title.match(lines[i])
                    if test_m and test_m.group(1).startswith(f"{sec_num}."):
                        break
                title_parts.append(nline)
                i += 1

            title = " ".join(title_parts)
            title = re.sub(r'\s+', ' ', title).strip()

            current_section["items"].append({
                "item_number": item_number,
                "title": title,
                "page_start": None,
                "page_end": None,
                "file_number": None,
                "item_type": itype,
            })
            continue

        # Item number with title on same line (no page range)
        mi2 = item_with_title.match(line)
        if mi2 and mi2.group(1).startswith(f"{sec_num}."):
            item_number = mi2.group(1)
            title_parts = [mi2.group(2).strip()]
            i += 1
            while i < len(lines):
                nline = lines[i].strip()
                if not nline:
                    i += 1
                    continue
                if section_re.match(lines[i]):
                    break
                if pattern_a.match(lines[i]) or pattern_b_range_item.match(lines[i]) or pattern_c_range.match(lines[i]):
                    break
                if file_number_re.match(nline):
                    break
                if item_number_alone.match(lines[i]):
                    test_m = item_number_alone.match(lines[i])
                    if test_m and test_m.group(1).startswith(f"{sec_num}."):
                        break
                if item_with_title.match(lines[i]):
                    test_m = item_with_title.match(lines[i])
                    if test_m and test_m.group(1).startswith(f"{sec_num}."):
                        break
                title_parts.append(nline)
                i += 1

            title = " ".join(title_parts)
            title = re.sub(r'\s+', ' ', title).strip()

            current_section["items"].append({
                "item_number": item_number,
                "title": title,
                "page_start": None,
                "page_end": None,
                "file_number": None,
                "item_type": itype,
            })
            continue

        i += 1

    # Finalize last section
    if current_section:
        sections.append(current_section)

    doc.close()

    return {
        "meeting": meeting_info,
        "agenda_pages": total_pages,
        "sections": sections,
    }


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <agenda.pdf> <output.json>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]

    result = parse_agenda(pdf_path)

    # Summary
    total_items = sum(len(s["items"]) for s in result["sections"])
    items_with_pages = sum(
        1 for s in result["sections"]
        for item in s["items"]
        if item["page_start"] is not None
    )
    print(f"Parsed {total_items} items across {len(result['sections'])} sections")
    print(f"  {items_with_pages} items have page ranges")

    # Detail per section
    for s in result["sections"]:
        if s["items"]:
            page_items = sum(1 for it in s["items"] if it["page_start"] is not None)
            print(f"  Section {s['number']}: {s['title']} - {len(s['items'])} items ({page_items} with pages)")

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
