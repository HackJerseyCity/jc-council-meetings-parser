# Jersey City Council Meetings
This repository stores the agenda, agenda packet, minutes, and minutes packets
for Jersey City council meetings. It also includes scripts for parsing these
files into structured (e.g., JSON) representations.

## Dependencies

All three scripts require [PyMuPDF](https://pymupdf.readthedocs.io/):

```
pip install PyMuPDF
```

## Scripts

### 1. `parse_agenda.py` — Parse an agenda PDF into JSON

Reads a council meeting agenda PDF and extracts the meeting date/type, section
headers, and individual agenda items (with page ranges and file numbers where
available).

```
python3 parse_agenda.py <agenda.pdf> <output.json>
```

**Example:**

```
python3 parse_agenda.py 2026/02-11/agenda.pdf 2026/02-11/agenda_parsed.json
```

**Output structure:**

```json
{
  "meeting": { "type": "regular", "date": "2026-02-11" },
  "agenda_pages": 9,
  "sections": [
    {
      "number": 3,
      "title": "ORDINANCES ON FIRST READING",
      "type": "ordinance_first_reading",
      "items": [
        {
          "item_number": "3.1",
          "title": "An Ordinance amending...",
          "page_start": 10,
          "page_end": 13,
          "file_number": "Ord. 26-001",
          "item_type": "ordinance"
        }
      ]
    }
  ]
}
```

Each section is classified into a normalized type (`ordinance_first_reading`,
`ordinance_second_reading`, `resolutions`, `claims`, etc.) and each item is
tagged as `ordinance`, `resolution`, `claims`, or `other`.

---

### 2. `split_packet.py` — Split a packet PDF into per-item PDFs

Takes a full meeting packet PDF and the parsed agenda JSON from step 1, then
extracts each agenda item into its own PDF file. Also produces a
`manifest.json` summarizing what was created.

```
python3 split_packet.py <packet.pdf> <agenda_parsed.json> <output_dir>
```

**Example:**

```
python3 split_packet.py 2026/02-11/packet.pdf 2026/02-11/agenda_parsed.json 2026/02-11/split/
```

**What it creates:**

```
split/
  agenda/00.00_agenda.pdf
  ordinances/03.01_ordinance_Ord-26-001.pdf
  ordinances/04.02_ordinance_Ord-26-010.pdf
  resolutions/10.01_resolution_Res-26-100.pdf
  claims/09.01_claims.pdf
  manifest.json
```

Items are organized into subdirectories by type (`ordinances`, `resolutions`,
`claims`, `other`). The script validates each split by checking that the
expected file number appears in the extracted pages, and prints warnings for
any mismatches.

---

### 3. `parse_minutes.py` — Parse minutes for voting records

Reads the meeting minutes PDF (standalone or from a minutes packet) and
extracts per-item voting results — including the tally, individual council
member votes, and absences.

```
python3 parse_minutes.py <minutes.pdf> <output.json>
```

**Example:**

```
python3 parse_minutes.py 2026/01-28/minutes.pdf 2026/01-28/minutes_parsed.json
```

**Output structure:**

```json
{
  "meeting": { "type": "regular", "date": "2026-01-28" },
  "council_members": ["Ridley", "Lavarro", "Griffin", "Singh", "..."],
  "initial_absences": ["Gilmore"],
  "items": [
    {
      "item_number": "10.1",
      "title": "A Resolution authorizing...",
      "file_number": "Res. 26-100",
      "result": "approved",
      "vote_tally": "8-1",
      "votes": {
        "aye": ["Ridley", "Griffin", "Singh", "Brooks", "Zuppa", "Ephros", "Little"],
        "nay": ["Lavarro"],
        "abstain": [],
        "absent": ["Gilmore"]
      },
      "vote_detail": "Councilperson Lavarro: nay"
    }
  ]
}
```

The script auto-detects the council member roster from the minutes header and
only reads the first 20 pages (minutes text rarely exceeds this). It handles
items with results of `approved`, `introduced`, `withdrawn`, `defeated`,
`tabled`, and `postponed`.

## Typical workflow

```bash
# 1. Parse the agenda
python3 parse_agenda.py 2026/02-11/agenda.pdf 2026/02-11/agenda_parsed.json

# 2. Split the packet into per-item PDFs
python3 split_packet.py 2026/02-11/packet.pdf 2026/02-11/agenda_parsed.json 2026/02-11/split/

# 3. After the meeting, parse the minutes for votes
python3 parse_minutes.py 2026/02-11/minutes.pdf 2026/02-11/minutes_parsed.json
```

## License
Code and structured outputs are licensed under the MIT License. Council agendas
and minutes are provided under the terms of their respective licenses (explicit
or implicit).