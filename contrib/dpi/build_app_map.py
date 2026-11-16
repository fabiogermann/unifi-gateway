#!/usr/bin/env python3
"""Build the Zenarmor -> TDTS (UniFi USG DPI) application id map.

Inputs:
  --tdts     UGW3 firmware TDTS signature db (etc/ubnt/tdts/rule.xml)
  --zenarmor Zenarmor app taxonomy (db/webui/apps.json from OPNsense)
  --out      output map JSON

Output: {zenarmor_app_id: {zenarmor_name, zenarmor_cat, tdts_app_id,
                           tdts_cat_id, tdts_name, match: exact|first-segment|
                           containment|fuzzy}}

Matching strategy (in order): normalized exact, first segment of slashed
TDTS names, containment (min 4 chars), fuzzy (difflib >= 0.88, first-letter
bucketed). Unmapped apps are listed on stderr with exit code 2 for CI use.

Known hard gaps in TDTS v1.404 (frozen 2023-01, last USG firmware): TikTok,
Reddit, Telegram, Discord do not exist as apps. Newer TDTS dbs ship in
UXG/UDM firmware images if higher fidelity is needed.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.88


def norm(s):
    s = unicodedata.normalize("NFKD", s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def load_tdts(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    apps = []
    for m in re.finditer(
            r'<application cat_id="(\d+)" app_id="(\d+)" name="([^"]+)"', text):
        cat, app, name = m.groups()
        apps.append({"app_id": int(app), "cat_id": int(cat), "name": name})
    if not apps:
        raise SystemExit(f"no TDTS applications found in {path}")
    return apps


def build_indexes(tdts):
    by_name = defaultdict(list)
    by_first_letter = defaultdict(list)
    for t in tdts:
        n = norm(t["name"])
        by_name[n].append(t)
        first = norm(t["name"].split("/")[0])
        if first != n:
            by_name[first].append(t)
        by_first_letter[n[:1]].append((n, t))
    return by_name, by_first_letter


def match(zname, by_name, by_first_letter):
    n = norm(zname)
    if n in by_name:
        return by_name[n][0], "exact"
    # containment: full scan (cheap), longest overlap wins
    best = None
    for entries in by_first_letter.values():
        for nt, t in entries:
            if len(nt) >= 4 and (nt in n or n in nt):
                d = abs(len(nt) - len(n))
                if best is None or d < best[0]:
                    best = (d, t)
    if best:
        return best[1], "containment"
    # fuzzy within the first-letter bucket
    bt, bs = None, 0.0
    for nt, t in by_first_letter.get(n[:1], []):
        s = SequenceMatcher(None, n, nt).ratio()
        if s > bs:
            bt, bs = t, s
    if bs >= FUZZY_THRESHOLD:
        return bt, "fuzzy"
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tdts", required=True)
    ap.add_argument("--zenarmor", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tdts = load_tdts(args.tdts)
    by_name, by_first_letter = build_indexes(tdts)
    zapps = json.load(open(args.zenarmor))["apps"]

    mapping, unmatched, stats = {}, [], defaultdict(int)
    for app in zapps:
        t, how = match(app["name"], by_name, by_first_letter)
        if not t:
            unmatched.append(app["name"])
            continue
        stats[how] += 1
        mapping[str(app["id"])] = {
            "zenarmor_name": app["name"],
            "zenarmor_cat": app["category"],
            "tdts_app_id": t["app_id"],
            "tdts_cat_id": t["cat_id"],
            "tdts_name": t["name"],
            "match": how,
        }

    json.dump(mapping, open(args.out, "w"), indent=1, sort_keys=True)
    total = len(zapps)
    print(f"TDTS apps: {len(tdts)} | Zenarmor apps: {total}")
    print(f"mapped: {len(mapping)}/{total} ({100*len(mapping)/total:.1f}%) "
          f"[{dict(stats)}]")
    print(f"unmapped: {len(unmatched)}", file=sys.stderr)
    if unmatched:
        print("unmapped sample: " + ", ".join(unmatched[:25]), file=sys.stderr)


if __name__ == "__main__":
    main()
