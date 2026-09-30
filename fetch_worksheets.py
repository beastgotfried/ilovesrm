#!/usr/bin/env python3
"""Fetch every published worksheet file for the semester-3 courses.

The portal has no student-visible file listing, so codes are probed:
<code> = <unit><session:02d><slo>  (e.g. 3081 = U3 S08 SLO1) under
uploads/data/coordinator/<COURSE>/slp/<code>.docx|pdf

Output: build/file_inventory.json + build/worksheets/<course>/<code>.<ext>
Re-runnable: existing files are skipped.
"""
import concurrent.futures, json, os, sys, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://dld.srmist.edu.in/etecurricula/server/uploads/data/coordinator/{c}/slp/{f}"

# course -> max sessions per unit (UHV has 9, others 12)
COURSES = {"21CSS201T": 12, "21CSC203P": 12, "21LEM202T": 9,
           "21CSC201J": 12, "21CSC202J": 12, "21MAB201T": 12}


def probe(job):
    c, code = job
    for ext in ("docx", "pdf"):
        req = urllib.request.Request(BASE.format(c=c, f=f"{code}.{ext}"),
                                     method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status == 200 and int(r.headers.get("Content-Length", 0)) > 1000:
                    return (c, code, ext)
        except Exception:
            pass
    return None


def dl(job):
    c, code, ext = job
    dst = os.path.join(ROOT, "build", "worksheets", c, f"{code}.{ext}")
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return True
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    urllib.request.urlretrieve(BASE.format(c=c, f=f"{code}.{ext}"), dst)
    return True


def main():
    jobs = [(c, f"{u}{s:02d}{sl}")
            for c, maxs in COURSES.items()
            for u in range(1, 6) for s in range(1, maxs + 1) for sl in (1, 2)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        found = [r for r in ex.map(probe, jobs) if r]

    inv = {}
    for c, code, ext in found:
        inv.setdefault(c, []).append({"code": code, "ext": ext})
    for c in inv:
        inv[c].sort(key=lambda x: x["code"])
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(os.path.join(ROOT, "build", "file_inventory.json"), "w") as f:
        json.dump(inv, f, indent=1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        n = sum(1 for _ in ex.map(dl, found))
    for c in sorted(inv):
        print(f"{c}: {len(inv[c])} files")
    print(f"total {n} files downloaded")


if __name__ == "__main__":
    main()
