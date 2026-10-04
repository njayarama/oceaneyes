#!../.oceaneyes/bin/python3
"""
favsync.py - Add / delete radio favourites from a flat-file manifest.

Each line in the manifest is one action:

  ADD/REPLACE (upsert at a specific preset slot):
      favid, Station Name, Stream URL [, country [, genre]]

  DELETE:
      -favid

Country and genre may be given as:
  - Skytune codes, e.g.  3;17;-1  (Europe;United Kingdom;England)  and  2;14 (Music)
  - human-readable text, e.g. "United Kingdom" or "Asian Music" (encoded via lookup tables)
  - blank  -> defaults 3;17;-1  (United Kingdom)  and  2;68 (Various)

Examples:
  # put these two stations at preset 25 and 26
  25,Jazz FM,http://edge-bauerall-01-gos2.sharp-stream.com/jazz.mp3,United Kingdom,Jazz
  26,Vivaldi,https://stream.0nlineradio.com/vivaldi,United Kingdom,Classical Opera and Culture
  # replace whatever is at preset 16
  16,Telugu Music UK,https://c8.radioboss.fm:18033/stream,United Kingdom,Asian Music
  # remove presets 30 and 31
  -30
  -31

Lines starting with '#' and blank lines are ignored.
Fields are comma separated; do not put commas inside names/urls.

Usage:
  .oceaneyes/bin/python3 favsync.py manifest.txt [--device 1] [--dry-run]
"""
import argparse, re, sys, time
import oceaneyes as oe

# Default codes used when country / genre are left blank
DEF_COUNTRY = "3;17;-1"   # Europe ; United Kingdom
DEF_GENRE   = "2;68"      # Music ; Various

CODE_RE = re.compile(r"^-?\d+(?:;-?\d+){0,2}$")


def init_codec_tables():
    """decode_* populate the module-level tables used by encode_*."""
    oe.decode_genre(1, 11)
    oe.decode_country(1, 1, 75)


def looks_like_codes(text):
    return bool(CODE_RE.match(text.strip()))


def resolve_country(text):
    text = (text or "").strip()
    if not text:
        return DEF_COUNTRY
    if looks_like_codes(text):
        return text
    code, result = oe.encode_country(text)
    return result if code == 200 else DEF_COUNTRY


def resolve_genre(text):
    text = (text or "").strip()
    if not text:
        return DEF_GENRE
    if looks_like_codes(text):
        return text
    code, result = oe.encode_genre(text)
    return result if code == 200 else DEF_GENRE


def parse_manifest(path):
    actions = []
    with open(path) as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-"):
                favid = line[1:].strip()
                if favid.isnumeric():
                    actions.append(("delete", int(favid)))
                    continue
                print(f"[warn] line {lineno}: malformed delete: {line!r}")
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3 or not parts[0].isnumeric():
                print(f"[warn] line {lineno}: malformed add, need favid,name,url: {line!r}")
                continue
            favid = int(parts[0])
            chname = parts[1]
            churl = parts[2]
            if not chname or "http" not in churl:
                print(f"[warn] line {lineno}: bad name/url: {line!r}")
                continue
            actions.append(("add", favid, chname, churl,
                            parts[3] if len(parts) > 3 else "",
                            parts[4] if len(parts) > 4 else ""))
    return actions


def do_delete(device, favid):
    total = oe.get_total(device, "fav")
    if favid > total:
        return f"DEL {favid:3} skipped : no preset at that id (total={total})"
    if oe.delete(device, str(favid)):
        return f"DEL {favid:3} OK     "
    return f"DEL {favid:3} FAILED : device returned an error"


def do_add(device, favid, chname, churl, chcountry, chgenre):
    total = oe.get_total(device, "fav")
    if favid > total + 1:
        return (f"ADD {favid:3} skipped : slot beyond current end (total={total}), "
                f"add in order or fill intermediate slots")
    replaced = favid <= total
    if replaced:
        oe.delete(device, str(favid))
        time.sleep(2)  # let the device compact the list

    ccountry = resolve_country(chcountry)
    cgenre = resolve_genre(chgenre)
    code, station = oe.add(device, chname, churl, ccountry, cgenre, False)
    if code != 200:
        return f"ADD {favid:3} FAILED ({code}) {station}"

    newtotal = oe.get_total(device, "fav")
    if newtotal != favid:
        mcode, mmsg = oe.move(device, str(newtotal), str(favid))
        if mcode != 200:
            return (f"ADD {favid:3} added at {newtotal} but move failed "
                    f"({mcode}) {mmsg}")
    tag = "replace" if replaced else "append"
    return f"ADD {favid:3} OK     : {chname} [{tag}] {churl}"


def main():
    ap = argparse.ArgumentParser(description="Add/delete radio favourites from a flat file")
    ap.add_argument("manifest", help="path to the flat-file manifest")
    ap.add_argument("--device", type=int, default=1, help="device index (default 1)")
    ap.add_argument("--dry-run", action="store_true", help="print actions without touching the radio")
    args = ap.parse_args()

    init_codec_tables()
    actions = parse_manifest(args.manifest)
    if not actions:
        print("[i] No actions found in manifest.")
        return

    device = args.device
    print(f"[i] Device {device} - {len(actions)} action(s) from {args.manifest} "
          f"({'DRY RUN' if args.dry_run else 'LIVE'})")

    # Resolve country/genre for display/commit: resolve_* are local dict lookups, safe for dry-run
    planned = []
    for act in actions:
        if act[0] == "delete":
            planned.append(("delete", act[1]))
        else:
            ccountry = resolve_country(act[4])
            cgenre = resolve_genre(act[5])
            planned.append(("add", act[1], act[2], act[3], ccountry, cgenre,
                            "replace" if act[1] <= oe.get_total(device, "fav") else "append"))

    ok = 0
    for p in planned:
        if p[0] == "delete":
            print(f"  {p[1]:3} DELETE")
        else:
            print(f"  {p[1]:3} ADD {p[2]} ({p[4]} / {p[5]}) [{p[6]}]")
    if args.dry_run:
        print("[i] Dry run only - nothing changed.")
        return

    print()
    for act in actions:
        if act[0] == "delete":
            try:
                print(f"  {do_delete(device, act[1])}")
                ok += 1
            except Exception as e:
                print(f"  DEL {act[1]:3} ERROR : {e}")
        else:
            try:
                print(f"  {do_add(device, act[1], act[2], act[3], act[4], act[5])}")
                ok += 1
            except Exception as e:
                print(f"  ADD {act[1]:3} ERROR : {e}")
        time.sleep(2)  # play it safe between device mutations

    print(f"\n[i] Done ({ok}/{len(actions)} executed). "
          f"Total favourites now: {oe.get_total(device, 'fav')}")


if __name__ == "__main__":
    main()