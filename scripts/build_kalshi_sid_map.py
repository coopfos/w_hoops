import csv
import re
from collections import defaultdict, Counter
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TICKERS_CSV = ROOT / "kalshi" / "tickers.csv"
SCHOOL_ID_CSV = ROOT / "school_id.csv"
OUT_CODES = ROOT / "kalshi_codes.csv"
OUT_MAP = ROOT / "kalshi_sid_map.csv"


def split_title(title: str):
    if not title:
        return None
    t = title.strip()
    # Remove trailing question marks and common suffix
    t = re.sub(r"\s*Winner\?\s*$", "", t, flags=re.IGNORECASE)
    # Handle common separators
    for sep in [" at ", " vs ", " vs. ", " vs ", " vs. "]:
        parts = re.split(sep, t, flags=re.IGNORECASE)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    # Fallback: try hyphen
    parts = re.split(r"\s*-\s*", t)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return None


_PAREN_RE = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    # Drop parentheticals first (e.g., "(NY)")
    s = _PAREN_RE.sub("", s)
    # Unify common variants
    s = s.replace("&", " and ")
    # Expand St. / St
    s = re.sub(r"\bst\.?\b", "saint", s)
    # Normalize cal state variants
    s = s.replace("california", "cal")
    s = s.replace("uc ", "uc ")  # noop for clarity
    # Remove punctuation/spaces
    s = _NON_ALNUM.sub("", s)
    return s


def load_school_index(path: Path):
    schools = []
    norm_index = {}
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            school = row.get("School") or row.get("school") or row.get("name")
            sid = row.get("sid")
            if not school or not sid:
                continue
            schools.append((school, sid))
            n = normalize_name(school)
            # If collision, keep first but we will still consider all during fuzzy search
            norm_index.setdefault(n, []).append((school, sid))
    return schools, norm_index


def best_match(name: str, schools, norm_index):
    # Try exact (case-insensitive) first
    for school, sid in schools:
        if school.lower() == name.lower():
            return {
                "school_guess": school,
                "sid_guess": sid,
                "match_type": "exact",
                "match_score": 1.0,
            }
    # Try normalized exact
    n = normalize_name(name)
    if n in norm_index:
        lst = norm_index[n]
        # If multiple, pick the first but flag ambiguity via score 0.99
        school, sid = lst[0]
        return {
            "school_guess": school,
            "sid_guess": sid,
            "match_type": "normalized",
            "match_score": 0.99 if len(lst) > 1 else 1.0,
        }
    # Fuzzy fallback
    best = None
    best_score = -1.0
    for school, sid in schools:
        score = SequenceMatcher(None, n, normalize_name(school)).ratio()
        if score > best_score:
            best_score = score
            best = (school, sid)
    if best is None:
        return {
            "school_guess": "",
            "sid_guess": "",
            "match_type": "none",
            "match_score": 0.0,
        }
    school, sid = best
    return {
        "school_guess": school,
        "sid_guess": sid,
        "match_type": "fuzzy",
        "match_score": round(best_score, 4),
    }


def main():
    if not TICKERS_CSV.exists():
        raise SystemExit(f"Missing tickers csv: {TICKERS_CSV}")
    if not SCHOOL_ID_CSV.exists():
        raise SystemExit(f"Missing school_id csv: {SCHOOL_ID_CSV}")

    # Map code -> occurrence count, and code -> team name frequency
    code_counts = Counter()
    code_team_counts = defaultdict(Counter)

    with TICKERS_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker") or ""
            title = row.get("title") or ""
            if not ticker:
                continue
            # Extract code after last dash
            if "-" not in ticker:
                continue
            code = ticker.rsplit("-", 1)[-1].strip()
            if not code:
                continue
            code_counts[code] += 1
            names = split_title(title)
            if names:
                a, b = names
                if a:
                    code_team_counts[code][a] += 1
                if b:
                    code_team_counts[code][b] += 1

    # Build canonical name guesses per code
    code_name = {}
    for code, counts in code_team_counts.items():
        if counts:
            name, _ = counts.most_common(1)[0]
            code_name[code] = name
        else:
            code_name[code] = ""

    # Load school ids
    schools, norm_index = load_school_index(SCHOOL_ID_CSV)

    # Write unique code list
    with OUT_CODES.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["kalshi_code", "occurrences", "kalshi_name_guess"])
        for code in sorted(code_counts.keys()):
            writer.writerow([code, code_counts[code], code_name.get(code, "")])

    # Common title aliases to canonical school names
    title_alias = {
        "BYU": "Brigham Young",
        "Ole Miss": "Mississippi",
        "UConn": "Connecticut",
        "USC": "Southern California",
        "UNLV": "Nevada-Las Vegas",
        "Long Beach St.": "Long Beach State",
        "San Diego St.": "San Diego State",
        "San Jose St.": "San Jose State",
        "Boise St.": "Boise State",
        "Fresno St.": "Fresno State",
        "Colorado St.": "Colorado State",
        "Penn St.": "Penn State",
        "Portland St.": "Portland State",
        "Wichita St.": "Wichita State",
        # Saint variants occasionally appear shortened; keep as-is or handled by fuzzy
    }

    # Write mapping attempts
    with OUT_MAP.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "kalshi_code",
            "occurrences",
            "kalshi_name",
            "school_guess",
            "sid_guess",
            "match_type",
            "match_score",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for code in sorted(code_counts.keys()):
            kname = code_name.get(code, "")
            # Apply title alias if available
            if kname in title_alias:
                kname_for_match = title_alias[kname]
            else:
                kname_for_match = kname
            match = best_match(kname, schools, norm_index) if kname else {
                "school_guess": "",
                "sid_guess": "",
                "match_type": "none",
                "match_score": 0.0,
            }
            row = {
                "kalshi_code": code,
                "occurrences": code_counts[code],
                "kalshi_name": kname_for_match if kname_for_match != kname else kname,
                **(best_match(kname_for_match, schools, norm_index) if kname_for_match else match),
            }
            writer.writerow(row)

    print(f"Wrote {OUT_CODES} and {OUT_MAP}")


if __name__ == "__main__":
    main()
