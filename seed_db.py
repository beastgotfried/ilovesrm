"""One-time seeder: converts existing answers_*.py modules into
data/<COURSE>/unit-N/<code>/boilerplate.json."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))

SOURCES = {
    "21LEM202T": ["answers_uhv", "answers_uhv345"],          # UHV U1-U5
    "21CSC203P": ["answers_app", "answers_app3"],            # APP U1-U3(S1-7)
    "21CSS201T": ["answers_u1_a", "answers_u1_b", "answers_u2", "answers_u3"],  # COA U1-U3
}

def get_W(mod):
    for attr in ("W", "W2"):
        if hasattr(mod, attr):
            return getattr(mod, attr)
    raise AttributeError(mod.__name__)

def main():
    total = 0
    for course, mods in SOURCES.items():
        W = {}
        for m in mods:
            W.update(get_W(__import__(m)))
        for code, entry in W.items():
            outdir = os.path.join(ROOT, "data", course, f"unit-{code[0]}", code)
            os.makedirs(outdir, exist_ok=True)
            with open(os.path.join(outdir, "boilerplate.json"), "w") as f:
                json.dump(entry, f, indent=1)
            total += 1
        print(course, len(W), "worksheets")
    print("TOTAL", total)

if __name__ == "__main__":
    main()
