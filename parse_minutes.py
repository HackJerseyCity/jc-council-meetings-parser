#!/usr/bin/env python3
"""Parse Jersey City Council meeting minutes to extract voting breakdowns.

Accepts either the standalone minutes.pdf or the full minutes-packet.pdf
(only the first ~15 pages are read for vote data).

Usage:
    python3 parse_minutes.py <minutes.pdf> <output.json>

Example:
    python3 parse_minutes.py 2026/01-28/minutes.pdf 2026/01-28/minutes_parsed.json
    python3 parse_minutes.py 2026/01-28/minutes-packet.pdf 2026/01-28/minutes_parsed.json
"""

import sys
import json
import re
import fitz  # PyMuPDF


# Council members by last name (used to build the default full roster)
# This is extracted from the header of the minutes document itself at runtime.
DEFAULT_MEMBERS = [
    "Ridley", "Lavarro", "Griffin", "Singh",
    "Brooks", "Zuppa", "Ephros", "Little", "Gilmore",
]


def extract_meeting_info(text):
    """Extract meeting type, date, and council member roster."""
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


def extract_roster(text):
    """Extract council member names from the header of the minutes.

    Returns a list of last-name strings used throughout the votes
    (e.g., 'Lavarro' not 'Lavarro, Jr.').
    """
    members = []
    # Pattern: "FirstName [MI.] LastName[, Jr.], Councilperson"
    # We need to extract the last name before any ", Jr." or ", Councilperson"
    for m in re.finditer(
        r'^(.+?),?\s+Councilperson',
        text[:3000], re.MULTILINE
    ):
        full = m.group(1).strip()
        # Remove trailing ", Jr." or similar suffixes
        full_clean = re.sub(r',\s*Jr\.?\s*$', '', full).strip()
        # Last name is the last word
        parts = full_clean.split()
        if parts:
            last = parts[-1].rstrip(',.')
            # Skip false positives (common words that aren't names)
            if last.lower() in ('of', 'the', 'a', 'and', 'acting', 'jr',
                                'large', 'ward', 'council', 'pro', 'tempore',
                                'present', 'absent', 'members', 'nine', 'eight'):
                continue
            if last not in members:
                members.append(last)
    return members if members else DEFAULT_MEMBERS


def find_minutes_end(lines):
    """Find the line index where minutes content ends.

    The minutes section ends at the DEFERRED/ADJOURNMENT section
    or at a line like 'Reviewed and found to be correct'.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "Reviewed and found to be correct" in stripped:
            return i
        if re.match(r'^\s*12\.\s+ADJOURNMENT', stripped):
            return i + 10  # include a few lines after
    return len(lines)


def parse_vote_tally(tally_str):
    """Parse a vote tally string like '9-0', '8-1', '7-0-2', '6-3'.

    Returns (ayes, nays, abstentions) as integers.
    """
    parts = tally_str.strip().split('-')
    ayes = int(parts[0]) if len(parts) > 0 else 0
    nays = int(parts[1]) if len(parts) > 1 else 0
    abstentions = int(parts[2]) if len(parts) > 2 else 0
    return ayes, nays, abstentions


def extract_named_members(text, roster):
    """Extract council member last names mentioned in a vote detail line.

    Handles patterns like:
    - 'Councilperson Lavarro: nay'
    - 'Councilperson Singh and Councilperson Little: Abstain'
    - 'Council president pro temp Gilmore, Councilperson Lavarro, and Councilperson Griffin: nay'
    """
    found = []
    # Match "Councilperson <Name>" or "Council president pro temp <Name>"
    for m in re.finditer(
        r'(?:Councilperson|Council\s+president\s+pro\s+temp)\s+([A-Z][a-z]+)',
        text, re.IGNORECASE
    ):
        name = m.group(1)
        # Match against roster
        for member in roster:
            if member.lower() == name.lower():
                found.append(member)
                break
        else:
            found.append(name)
    return found


def build_vote_breakdown(result, tally_str, detail_text, roster):
    """Build the full vote breakdown dict from parsed components."""
    ayes_count, nays_count, abstain_count = parse_vote_tally(tally_str)

    votes = {
        "aye": [],
        "nay": [],
        "abstain": [],
        "absent": [],
    }

    # Determine which members voted nay or abstained from the detail text
    named_nay = []
    named_abstain = []

    if detail_text:
        detail_lower = detail_text.lower()
        named = extract_named_members(detail_text, roster)
        if 'nay' in detail_lower:
            named_nay = named
        elif 'abstain' in detail_lower:
            named_abstain = named

    # Build lists
    # Start by assuming everyone voted aye, then adjust
    accounted = set()
    for name in named_nay:
        votes["nay"].append(name)
        accounted.add(name)
    for name in named_abstain:
        votes["abstain"].append(name)
        accounted.add(name)

    # Total members present = ayes + nays + abstentions
    total_present = ayes_count + nays_count + abstain_count
    total_roster = len(roster)
    absent_count = total_roster - total_present

    # The remaining roster members who aren't named as nay/abstain
    # and aren't absent voted aye
    remaining = [m for m in roster if m not in accounted]

    # If we need absent members but don't have names, we can't assign them.
    # However: if total_present < total_roster, some are absent.
    # We won't have their names here unless we parsed the roll call.
    # For now, mark as aye if present.
    if absent_count > 0 and len(remaining) > ayes_count:
        # We have more remaining members than aye votes - some must be absent.
        # Without named absences, we can only list the aye count.
        votes["aye"] = remaining[:ayes_count]
        votes["absent"] = remaining[ayes_count:]
    else:
        votes["aye"] = remaining

    return votes


def parse_minutes(pdf_path, max_pages=20):
    """Parse minutes PDF and extract voting breakdowns."""
    doc = fitz.open(pdf_path)

    # Only read the first max_pages pages (minutes text is typically < 15 pages)
    pages_to_read = min(len(doc), max_pages)
    full_text = ""
    for i in range(pages_to_read):
        full_text += doc[i].get_text("text") + "\n"

    meeting_info = extract_meeting_info(full_text)
    roster = extract_roster(full_text)

    lines = full_text.split("\n")
    end_idx = find_minutes_end(lines)
    lines = lines[:end_idx]

    # Parse roll call for absences
    roll_call_absent = []
    for line in lines[:100]:
        # "Councilperson Gilmore was absent."
        m = re.search(r'Councilperson\s+(\w+)\s+was\s+absent', line, re.IGNORECASE)
        if m:
            roll_call_absent.append(m.group(1))

    # Regex patterns
    section_re = re.compile(r'^\s*(\d{1,2})\.\s*$|^\s*(\d{1,2})\.\s+([A-Z])')
    item_re = re.compile(r'^\s*(\d{1,2}\.\d{1,2})\s')
    file_number_re = re.compile(r'((?:Ord|Res)\.\s*\d{2}-\d{3})')

    # Vote result patterns
    # "Introduced 9-0", "Approved 9-0", "Withdrawn 9-0", "Withdrawn", "Approved 8-1  detail"
    vote_re = re.compile(
        r'^\s*(Introduced|Approved|Withdrawn|Defeated|Tabled|Postponed)'
        r'(?:\s*[-–]?\s*(\d+-\d+(?:-\d+)?))?'
        r'(?:\s{2,}(.+))?',
        re.IGNORECASE
    )

    items = []
    current_section = None
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track current section (handles both "10. RESOLUTIONS" on one line
        # and "10.\n RESOLUTIONS" split across lines)
        sm = re.match(r'^\s*(\d{1,2})\.\s+([A-Z][A-Z\s\-\(\),&]+)', line)
        if not sm:
            # Check for section number alone on a line: "10. " or "10."
            sm2 = re.match(r'^\s*(\d{1,2})\.\s*$', line)
            if sm2:
                # Peek at next non-blank line for section title
                peek = i + 1
                while peek < len(lines) and not lines[peek].strip():
                    peek += 1
                if peek < len(lines) and re.match(r'^[A-Z][A-Z\s\-\(\),&]+', lines[peek].strip()):
                    sm = sm2
        if sm:
            sec_num = int(sm.group(1))
            current_section = sec_num
            i += 1
            continue

        # Look for item numbers
        im = item_re.match(line)
        if im:
            item_number = im.group(1)
            sec_prefix = item_number.split('.')[0]

            # Only process ordinances (3, 4) and resolutions (10), claims (9)
            if sec_prefix not in ('3', '4', '9', '10'):
                i += 1
                continue

            # Gather all lines for this item until we hit the next item or section
            item_lines = [line]
            i += 1
            while i < len(lines):
                nline = lines[i]
                nstripped = nline.strip()

                # Stop if we hit a new item in the same or different section
                if item_re.match(nline):
                    nm = item_re.match(nline)
                    # Make sure it's actually a new item, not a "Block 4801, Lot 1" etc.
                    candidate = nm.group(1)
                    candidate_sec = candidate.split('.')[0]
                    if candidate_sec in ('3', '4', '5', '6', '7', '8', '9', '10', '11', '12'):
                        break

                # Stop if we hit a new section header
                if re.match(r'^\s*(\d{1,2})\.\s+([A-Z][A-Z\s\-\(\),&]+)', nline):
                    break
                # Also stop at standalone section number: "10. " or "9. "
                if re.match(r'^\s*(\d{1,2})\.\s*$', nline):
                    break

                item_lines.append(nline)
                i += 1

            # Parse the item: extract title, vote, and file number
            title_parts = []
            vote_result = None
            vote_tally = None
            vote_detail_parts = []
            file_number = None
            found_vote = False

            for j, iline in enumerate(item_lines):
                istripped = iline.strip()

                # Check for file number
                fm = file_number_re.search(istripped)
                if fm:
                    file_number = fm.group(1)
                    file_number = re.sub(r'(Ord|Res)\.\s*', r'\1. ', file_number)

                # Check for vote line
                vm = vote_re.match(istripped)
                if vm:
                    vote_result = vm.group(1).capitalize()
                    if vm.group(2):
                        vote_tally = vm.group(2)
                    if vm.group(3):
                        vote_detail_parts.append(vm.group(3).strip())
                    found_vote = True
                    # Check if detail continues on next line(s)
                    for k in range(j + 1, len(item_lines)):
                        kstripped = item_lines[k].strip()
                        if not kstripped:
                            continue
                        # Continuation of vote detail (e.g., "Councilperson Lavarro, and...")
                        if re.match(r'^(?:Councilperson|Council\s+president|and\s+Councilperson)', kstripped, re.IGNORECASE):
                            vote_detail_parts.append(kstripped)
                        else:
                            break
                    continue

                # If we haven't found the vote yet, this is title text
                if not found_vote and istripped:
                    # Skip the item number from first line
                    if j == 0:
                        # Remove the item number prefix
                        title_text = re.sub(r'^\s*\d{1,2}\.\d{1,2}\s+', '', iline).strip()
                        if title_text:
                            title_parts.append(title_text)
                    else:
                        # Skip pure file number lines and "Withdrawn - Pdf" lines
                        if file_number_re.match(istripped):
                            continue
                        if re.match(r'^Withdrawn\s*-?\s*Pdf\s*$', istripped):
                            continue
                        # Skip lines that are just "Res. - Pdf" (no number)
                        if re.match(r'^(?:Ord|Res)\.\s*-?\s*Pdf\s*$', istripped):
                            continue
                        title_parts.append(istripped)

            # Handle items with inline votes: "Meeting Claims List: Approved-9-0"
            # Also handles ": -9-0" (missing result keyword, treat as approved)
            if not found_vote:
                combined = " ".join(il.strip() for il in item_lines)
                cm = re.search(r'(Approved|Withdrawn|Defeated)\s*[-–]?\s*(\d+-\d+(?:-\d+)?)', combined, re.IGNORECASE)
                if cm:
                    vote_result = cm.group(1).capitalize()
                    vote_tally = cm.group(2)
                elif sec_prefix == '9':
                    # Claims sometimes have just ": -9-0" with no keyword
                    cm2 = re.search(r':\s*-?\s*(\d+-\d+(?:-\d+)?)', combined)
                    if cm2:
                        vote_result = "Approved"
                        vote_tally = cm2.group(1)

            title = " ".join(title_parts)
            title = re.sub(r'\s+', ' ', title).strip()
            # Clean trailing file number references from title
            title = re.sub(r'\s*(?:Ord|Res)\.\s*(?:\d{2}-\d{3})?\s*-?\s*(?:Pdf|Withdrawn\s*-?\s*Pdf)?\s*$', '', title).strip()
            title = re.sub(r'\s*Withdrawn\s*-?\s*Pdf\s*$', '', title).strip()
            # Remove inline file numbers that leaked into title text
            title = re.sub(r'\s*(?:Ord|Res)\.\s*\d{2}-\d{3}\s*-?\s*', ' ', title).strip()
            title = re.sub(r'\s+', ' ', title)
            # Remove inline vote tallies from claims titles
            title = re.sub(r':\s*(?:Approved|Withdrawn|Defeated)\s*-?\s*\d+-\d+(?:-\d+)?', '', title, flags=re.IGNORECASE).strip()

            vote_detail = " ".join(vote_detail_parts)

            # Build vote breakdown
            if vote_result:
                if vote_result.lower() == 'withdrawn' and not vote_tally:
                    # Withdrawn without tally
                    votes = {
                        "aye": [],
                        "nay": [],
                        "abstain": [],
                        "absent": [],
                    }
                elif vote_tally:
                    votes = build_vote_breakdown(
                        vote_result, vote_tally, vote_detail, roster
                    )
                else:
                    votes = None
            else:
                votes = None

            item_data = {
                "item_number": item_number,
                "title": title if title else None,
                "file_number": file_number,
                "result": vote_result.lower() if vote_result else None,
                "vote_tally": vote_tally,
            }
            if votes is not None:
                item_data["votes"] = votes
            if vote_detail:
                item_data["vote_detail"] = vote_detail

            items.append(item_data)
            continue

        i += 1

    doc.close()

    return {
        "meeting": meeting_info,
        "council_members": roster,
        "initial_absences": roll_call_absent,
        "items": items,
    }


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <minutes.pdf> <output.json>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2]

    result = parse_minutes(pdf_path)

    total = len(result["items"])
    voted = sum(1 for it in result["items"] if it["result"])
    print(f"Parsed {total} items with votes/actions")
    print(f"  {voted} have recorded results")

    # Count by result type
    results = {}
    for it in result["items"]:
        r = it.get("result") or "no_action"
        results[r] = results.get(r, 0) + 1
    for r, count in sorted(results.items()):
        print(f"    {r}: {count}")

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"Output written to {output_path}")


if __name__ == "__main__":
    main()
