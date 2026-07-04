import sys, re, collections
sys.stdout.reconfigure(encoding='utf-8')
text = open('README.md', encoding='utf-8').read()

imgs = re.findall(r'local-observability-lab/(\d+)[.]png', text)
nums = sorted(set(int(n) for n in imgs))
missing = [i for i in range(1, 52) if i not in nums]
print("=== SCREENSHOT AUDIT ===")
print("Total refs:", len(imgs), "| Unique:", len(nums), "| Range:", min(nums), "-", max(nums))
print("Missing:", missing if missing else "NONE")
dups = [n for n, c in collections.Counter(int(x) for x in imgs).items() if c > 1]
print("Duplicate refs:", dups if dups else "NONE")

print()
print("=== GROUP HEADERS ===")
expected = {"A": 7, "B": 2, "C": 4, "D": 10, "E": 2, "F": 2, "G": 7, "H": 5, "I": 12}
for g, cnt in expected.items():
    hdr = "#### " + g + "."
    status = "PRESENT" if hdr in text else "MISSING"
    print("  " + hdr + " (expected " + str(cnt) + " screenshots): " + status)

print()
print("=== KEY CHECKS ===")
checks = {
    "Tip A-F G H-I": "Start with **A" in text,
    "Contributing section": "## 13. Contributing" in text,
    "Enterprise production context section": "## 12. Enterprise production context" in text,
    "Production patterns table (Google SRE)": "Google SRE" in text,
    "Real production scenarios table": "Real production scenarios" in text,
    "Recommended permanent repo improvements": "Recommended permanent repo" in text,
    "Eval scoring section": "Eval scoring" in text,
    "Incremental adoption phases 1-5": ("Phase 1" in text and "Phase 5" in text),
}
for k, v in checks.items():
    print("  " + k + ": " + ("OK" if v else "MISSING"))

print()
print("Lines:", text.count("\n"))
hdrs = re.findall(r'^#{1,4} .+', text, re.MULTILINE)
dup_hdrs = [h for h, c in collections.Counter(hdrs).items() if c > 1]
print("Dup headings:", dup_hdrs if dup_hdrs else "NONE")
