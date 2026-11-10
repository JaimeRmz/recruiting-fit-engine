"""
Roster parser for the Fit-Match model's program-side dataset.

Handles the two dominant NCAA athletics CMS templates:
  1. WMT Digital  (card-style blocks: jersey / pos+name / height-weight-class / hometown / major)
  2. Sidearm Sports (renders a clean markdown table when fetched as text)

Also handles the /staff-directory page both platforms serve (a different page
type from the roster -- see parse_sidearm_staff_directory / parse_wmt_staff_directory
below), which real fetches showed splits into (at least) two rendering shapes:
  A. card blocks under a "### <Department>" heading (Sidearm: Indiana, Wake Forest,
     Maryland; confirmed by direct fetch)
  B. one long markdown table with department names as plain-text "header" rows
     inside it, no dedicated separator (Sidearm: Georgetown; WMT: Stanford --
     confirmed by direct fetch, not assumed to match Sidearm's shape)

Usage:
    from parser import parse_wmt, parse_sidearm_table, parse_sidearm_staff_directory
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


# --- Staff directory (coach-email dataset) ----------------------------------
# A different page type from the roster: one department listing per sport
# rather than one row per player, and it goes stale on a different clock
# (coaching turnover, not eligibility years) -- see data/coach_directory.csv.

# Matches a department "header" -- whether that's a "### " markdown heading
# (card format) or a plain-text first cell in a table row (table format) --
# that STARTS with a soccer department label. Deliberately only anchored at
# the start (re.match, no trailing $): real pages trail all kinds of things
# after the label -- phone/fax/address (most sites), a twitter-handle link
# (Hofstra: "Men's Soccer [@hofstramsoc](url)") -- and none of it needs
# validating, only the label itself. Anchoring the START is what still
# rejects Denver's and Rutgers's schedule/news headings like "Completed
# Event: Men's Soccer at Cal Baptist on ..." -- those don't start with the
# label, "Completed Event:" does, so they never match. The four
# gender-suffix branches (parens/comma/hyphen/bare) are not redundant --
# real fetches turned up all four as genuinely different sites' spelling of
# the same thing: Wake Forest uses "SOCCER (MEN'S)", Maryland "SOCCER,
# MEN'S", SMU "SOCCER, MEN" (no apostrophe), Johns Hopkins "Soccer (M)", and
# Rutgers "Soccer-Men" -- on top of the plain "Men's Soccer" / "MEN'S
# SOCCER" prefix form most other sites use.
_SOCCER_DEPARTMENT_RE = re.compile(
    r"^\s*(?:"
    r"(?P<pre>MEN'S|WOMEN'S)\s+SOCCER\b"                              # Men's Soccer / MEN'S SOCCER
    r"|SOCCER\s*\(\s*(?P<par>MEN'S|WOMEN'S|MEN|WOMEN|M|W)\.?\s*\)"    # Soccer (Men's) / Soccer (M)
    r"|SOCCER\s*,\s*(?P<comma>MEN'S|WOMEN'S|MEN|WOMEN)\b"             # Soccer, Men's / Soccer, Men
    r"|SOCCER\s*-\s*(?P<hyph>MEN'S|WOMEN'S|MEN|WOMEN)\b"              # Soccer-Men / Soccer-Women
    r"|SOCCER\b(?P<none>)"                                            # bare "Soccer", no gender split
    r")",
    re.IGNORECASE,
)


def _soccer_department_gender(header_text):
    """('Men's Soccer - Phone: ...') -> ('M', True); (unrelated header) -> (None, False).

    Second return value is whether this was a soccer department at all (vs.
    some other sport/admin department, which callers must skip rather than
    treat as gender-unknown soccer)."""
    m = _SOCCER_DEPARTMENT_RE.match(header_text.strip())
    if not m:
        return None, False
    gender_word = m.group("pre") or m.group("par") or m.group("comma") or m.group("hyph")
    if not gender_word:
        return None, True  # a school with one combined "Soccer" department, no gender split
    gender_word = gender_word.upper().rstrip("'S")  # MEN'S/WOMEN'S -> MEN/WOMEN; M/W untouched
    return ("M" if gender_word.startswith("M") else "W"), True


def _extract_email(cells):
    """First real email address found across a row's cells, lowercased, or None.

    Scans every cell rather than a fixed column index because the two real
    table layouts found (Georgetown/Sidearm vs. Stanford/WMT) don't agree on
    column order or count, and some rows carry extra cross-listed-sport cells
    others don't."""
    for cell in cells:
        m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", cell)
        if m:
            return m.group(0).lower()
    return None


def _parse_staff_cards(md, school, division, sport):
    """Card-format staff directory: '### <Department>' heading, then repeated
    blocks of '[#### Name](url)' / title / optional phone / optional email /
    'Full Bio' link. Confirmed structure on Indiana, Wake Forest, Maryland,
    Creighton, Syracuse, and Denver's Sidearm staff-directory pages."""
    rows = []
    sections = re.split(r"(?m)^### (.+)$", md)
    for i in range(1, len(sections), 2):
        gender, is_soccer = _soccer_department_gender(sections[i])
        if not is_soccer:
            continue
        body = sections[i + 1]
        cards = re.split(r"\[####\s*([^\]]+)\]\([^)]+\)", body)
        for j in range(1, len(cards), 2):
            name = cards[j].strip()
            # A card's own content ends at its "Full Bio" link; without this cut,
            # scanning for title/email would drift into the NEXT person's block
            # whenever a field this person doesn't have (e.g. no phone) is absent.
            card_text = cards[j + 1].split("Full Bio")[0]
            title_match = re.search(r"\n\n([^\n\[][^\n]*)\n", card_text)
            title = title_match.group(1).strip() if title_match else None
            email_match = re.search(r"\[([\w.+-]+@[\w.-]+)\]\(mailto:", card_text)
            rows.append({
                "school": school, "division": division, "sport": sport,
                "gender": gender, "coach_name": name or None, "coach_title": title,
                "coach_email": email_match.group(1).lower() if email_match else None,
            })
    return rows


def _parse_staff_table(md, school, division, sport):
    """Table-format staff directory: one long markdown table where a
    department name appears as a plain-text (no markdown link) first cell,
    with real staff rows following until the next department cell.
    Confirmed structure on Georgetown (Sidearm) and Stanford (WMT); real
    fetches of more schools turned up several further wrinkles handled here:

    - No header-row text is trustworthy enough to locate the table by: it's
      usually "Name | Title | Email Address | ..." (Georgetown, Stanford),
      but Southeastern Nova and Saint Xavier's actual header cells all just
      say "Staff Photo" (an image-column label repeated across every
      column), with no "Name"/"Email" text anywhere. So every '|'-prefixed
      line in the document is scanned rather than searching for a header to
      anchor on -- correctness comes entirely from the department-gating
      state machine below (a row only counts once a real soccer department
      label was seen), not from finding the "right" table first.
    - Houston and Rutgers repeat a literal "| Name | Title | ... |" row at
      the start of EVERY department's own sub-table, not just once at the
      top. Treating a repeat as an unrecognized department (falling through
      to _soccer_department_gender) would wrongly reset in_soccer right
      after a real "Men's Soccer" header -- so repeats are recognized and
      skipped without touching department state.
    - Grand Valley State's name cell is plain text with the '[Name](url)'
      link one cell over, not inline in cell 0 like every other school
      tested -- so the link is searched for across all cells, not cell 0
      specifically, with the title read from whichever cell follows it.

    Column order/count also isn't consistent across schools (extra
    cross-listed-sport columns appear on some rows and not others), so email
    is found by scanning every cell (_extract_email) rather than indexing a
    fixed column."""
    lines = [l for l in md.split("\n") if l.strip().startswith("|")]
    rows = []
    current_gender, in_soccer = None, False
    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or re.fullmatch(r"-{2,}", cells[0]):
            continue  # markdown separator row (some sites emit one per department)
        if cells[0].strip().lower() in ("name", "staff photo"):
            continue  # a repeated/generic header row, not a department label
        link_idx, link_match = None, None
        for idx, cell in enumerate(cells):
            m = re.search(r"\[([^\]]+)\]\(", cell)
            if m:
                link_idx, link_match = idx, m
                break
        # A department row has no real content (title, phone...) beyond its own
        # label -- true even when that label itself contains a decorative link
        # (Hofstra: "Men's Soccer [@hofstramsoc](url)" with every other cell
        # blank). So "no link anywhere" alone isn't the right test; what matters
        # is whether any cell OTHER than the link cell actually holds content.
        has_other_content = link_match is not None and any(
            c.strip() for i, c in enumerate(cells) if i != link_idx
        )
        if not has_other_content:
            current_gender, in_soccer = _soccer_department_gender(cells[0])
            continue
        if not in_soccer:
            continue
        title = cells[link_idx + 1].strip() if link_idx + 1 < len(cells) else ""
        rows.append({
            "school": school, "division": division, "sport": sport,
            "gender": current_gender, "coach_name": link_match.group(1).strip() or None,
            "coach_title": title or None,
            "coach_email": _extract_email(cells),
        })
    return rows


def parse_sidearm_staff_directory(markdown_text, school, division, sport="soccer"):
    """Parse a Sidearm /staff-directory page, filtered to the department(s)
    matching `sport`. Handles both real sub-templates found by fetching
    actual Sidearm sites: a single big table (Georgetown) and repeated card
    blocks under a heading (everyone else tested). Tries the table shape
    first since it's unambiguous to detect; falls back to cards.
    """
    table_rows = _parse_staff_table(markdown_text, school, division, sport)
    if table_rows:
        return pd.DataFrame(table_rows)
    return pd.DataFrame(_parse_staff_cards(markdown_text, school, division, sport))


def parse_wmt_staff_directory(markdown_text, school, division, sport="soccer"):
    """Parse a WMT Digital /staff-directory page. Confirmed by direct fetch
    (Stanford) to be the same single-big-table-with-department-labels shape
    as Georgetown's Sidearm page, NOT the card format the roster templates
    might suggest -- this was verified rather than assumed, since WMT's
    roster template (card-style, see parse_wmt) has nothing to do with how
    its staff directory happens to render.
    """
    return pd.DataFrame(_parse_staff_table(markdown_text, school, division, sport))


if __name__ == "__main__":
    raw = open("data/raw_stanford_wmt.txt").read()
    df = parse_wmt(raw, school="Stanford", division="D1", gender="M")
    print(df.to_string(index=False))
    df.to_csv("data/stanford_parsed.csv", index=False)
    print(f"\nParsed {len(df)} players -> data/stanford_parsed.csv")
