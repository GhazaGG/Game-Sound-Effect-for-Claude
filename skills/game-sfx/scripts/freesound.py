#!/usr/bin/env python3
"""Find and fetch CC0 recordings from Freesound. Python 3.8+ stdlib only.

  python freesound.py search "horse hooves gravel" [--n 15] [--max-duration 60] [--any-license]
  python freesound.py get 434804 631829 -o sfx/sources

Needs FREESOUND_API_KEY (free: https://freesound.org/apiv2/apply). `get` saves the
high-quality preview (OGG) as <id>_<name>.ogg and appends a line to CREDITS.md
in the output folder. CC0 needs no attribution, but the record keeps the source traceable.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://freesound.org/apiv2"
FIELDS = "id,name,duration,license,username,avg_rating,num_ratings,num_downloads,tags,previews,url"


def api_key():
    key = os.environ.get("FREESOUND_API_KEY")
    if not key and sys.platform == "win32":  # `setx` only reaches programs started afterwards
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, "FREESOUND_API_KEY")[0]
        except OSError:
            pass
    return key


def call(path, **params):
    key = api_key()
    if not key:
        sys.exit("FREESOUND_API_KEY is not set. Get a free key at https://freesound.org/apiv2/apply")
    req = urllib.request.Request(f"{API}{path}?{urllib.parse.urlencode(params)}", headers={"Authorization": "Token " + key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search(query, n=15, max_duration=60, any_license=False):
    flt = f"duration:[0 TO {max_duration}]" + ("" if any_license else ' license:"Creative Commons 0"')
    return call("/search/text/", query=query, filter=flt, fields=FIELDS, sort="score", page_size=n)["results"]


def get(ids, out):
    os.makedirs(out, exist_ok=True)
    credits = os.path.join(out, "CREDITS.md")
    paths = []
    for sid in ids:
        s = call(f"/sounds/{sid}/", fields=FIELDS)
        if "creativecommons.org/publicdomain/zero" not in s["license"]:
            print(f"warning: {sid} is not CC0 ({s['license']}): check the license terms before shipping it")
        slug = re.sub(r"[^A-Za-z0-9]+", "_", s["name"]).strip("_")[:40]
        path = os.path.join(out, f"{s['id']}_{slug}.ogg")
        urllib.request.urlretrieve(s["previews"]["preview-hq-ogg"], path)
        with open(credits, "a", encoding="utf-8") as f:
            f.write(f"- {os.path.basename(path)}: \"{s['name']}\" by {s['username']}, {s['url']} ({s['license']})\n")
        print("saved", path)
        paths.append(path)
    return paths


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--n", type=int, default=15)
    s.add_argument("--max-duration", type=float, default=60)
    s.add_argument("--any-license", action="store_true", help="include non-CC0 results (check terms yourself)")
    g = sub.add_parser("get")
    g.add_argument("ids", nargs="+")
    g.add_argument("-o", "--out", default="sfx/sources")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # titles carry emoji; Windows consoles can't print them

    if args.cmd == "search":
        for r in search(args.query, args.n, args.max_duration, args.any_license):
            lic = "CC0" if "zero" in r["license"] else r["license"].rstrip("/").split("/")[-2]
            print(f"{r['id']:>7}  {r['duration']:6.1f}s  {r['avg_rating']:.1f}*({r['num_ratings']})  {r['num_downloads']:>6}dl  {lic:<6} "
                  f"{r['name'][:55]}  [{', '.join(r['tags'][:6])}]")
    else:
        get(args.ids, args.out)


if __name__ == "__main__":
    main()
