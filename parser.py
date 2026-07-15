"""
Roster parser for the Fit-Match model's program-side dataset.

Handles the two dominant NCAA athletics CMS templates:
  1. WMT Digital  (card-style blocks: jersey / pos+name / height-weight-class / hometown / major)
  2. Sidearm Sports (renders a clean markdown table when fetched as text)

Usage:
    from parser import parse_wmt, parse_sidearm_table
    rows = parse_wmt(open('data/raw_stanford_wmt.txt').read(), school='Stanford', division='D1')
"""
import re
import pandas as pd

HEIGHT_RE = re.compile(r"(\d)′(\d{1,2})″")
CLASS_MAP = {
    "freshman": "Fr", "fr": "Fr", "r-fr": "Fr", "redshirt freshman": "Fr",
    "sophomore": "So", "so": "So", "r-so": "So", "redshirt sophomore": "So",
    "junior": "Jr", "jr": "Jr", "r-jr": "Jr", "redshirt junior": "Jr",
    "senior": "Sr", "sr": "Sr", "r-sr": "Sr", "redshirt senior": "Sr", "gr": "Sr",
}


def _norm_class(raw):
    key = raw.strip().lower()
    return CLASS_MAP.get(key, raw.strip())


def _height_to_inches(h):
    m = HEIGHT_RE.search(h)
    if not m:
        return None
    feet, inches = int(m.group(1)), int(m.group(2))
    return feet * 12 + inches


def parse_wmt(raw_text, school, division, gender="M"):
    """Parse WMT Digital card-style roster text into structured rows."""
    # Each player block: jersey, then **POS**[Name](url), then physical/class line, then Hometown, then Major
    blocks = re.split(r"\n\*\*(\d+)\*\*\n\n", raw_text)[1:]  # drop preamble
    rows = []
    for i in range(0, len(blocks) - 1, 2):
        jersey = blocks[i].strip()
        body = blocks[i + 1]

        pos_name = re.search(r"\*\*([A-Z/]+)\*\*\[([^\]]+)\]", body)
        position = pos_name.group(1) if pos_name else None
        name = pos_name.group(2) if pos_name else None

        phys_class = re.search(r"\n\n([^\n]*(?:Freshman|Sophomore|Junior|Senior)[^\n]*)\n", body)
        phys_line = phys_class.group(1) if phys_class else ""
        height_in = _height_to_inches(phys_line)
        class_match = re.search(r"(Redshirt )?(Freshman|Sophomore|Junior|Senior)", phys_line)
        class_year = _norm_class((class_match.group(1) or "") + class_match.group(2)) if class_match else None

        hometown = re.search(r"\*\*Hometown\*\*([^\n]+)", body)
        hometown = hometown.group(1).strip() if hometown else None

        major = re.search(r"\*\*Major\*\*([^\n]+)", body)
        major = major.group(1).strip() if major else None

        rows.append({
            "school": school, "division": division, "gender": gender,
            "jersey": jersey, "name": name, "position": position,
            "class_year": class_year, "height_in": height_in,
            "hometown": hometown, "major": major, "club_team": None,
        })
    return pd.DataFrame(rows)


def parse_sidearm_table(markdown_table_text, school, division, gender="W"):
    """Parse the clean markdown table Sidearm Sports pages emit on fetch."""
    lines = [l for l in markdown_table_text.strip().split("\n") if l.strip().startswith("|")]
    header = [h.strip() for h in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:  # skip header + separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rec = dict(zip(header, cells))
        name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", rec.get("Full Name", ""))
        hometown_raw = rec.get("Hometown/Previous School", "")
        hometown = hometown_raw.split("/")[0].strip().rstrip("/").strip() if hometown_raw else None
        height_ft = re.search(r"(\d)'\s*(\d{1,2})?", rec.get("Ht.", "") or "")
        height_in = (int(height_ft.group(1)) * 12 + int(height_ft.group(2) or 0)) if height_ft else None
        rows.append({
            "school": school, "division": division, "gender": gender,
            "jersey": rec.get("#"), "name": name.strip() or None,
            "position": rec.get("Pos."), "class_year": rec.get("Academic Year"),
            "height_in": height_in, "hometown": hometown,
            "major": rec.get("Major") or None, "club_team": rec.get("Club Team") or None,
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    raw = open("data/raw_stanford_wmt.txt").read()
    df = parse_wmt(raw, school="Stanford", division="D1", gender="M")
    print(df.to_string(index=False))
    df.to_csv("data/stanford_parsed.csv", index=False)
    print(f"\nParsed {len(df)} players -> data/stanford_parsed.csv")
