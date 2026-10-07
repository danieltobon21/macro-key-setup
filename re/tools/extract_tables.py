#!/usr/bin/env python3
"""
Extract the key-code tables from the decompiled vendor app (ilspycmd output).

Input : HIDTester/*.cs   (decompiled C#)
Output: tables/*.json    (machine readable) + printed markdown summary

Encoding discovered in the RE (see docs/PROTOCOL.md):
  Data_Send_Buff[KeyType_Num=1]   key type nibble (|1 basic, |2 ctrl-shift-alt, 3 mouse, 8 led)
  Data_Send_Buff[KeyGroupCharNum=2] number of entries in the sequence (protocol 1)
  Data_Send_Buff[KeySet_KeyValNum=3] (protocol 0)
  Data_Send_Buff[Key_Fun_Num=4]   first slot of the "new" (protocol 3) layout
  Data_Send_Buff[KEY_Char_Num=5]  first slot of the legacy layout: (code, mod) pairs
  modifiers: 1=Ctrl 2=Shift 4=Alt 8=Win 16=RCtrl 32=RShift 64=RAlt 128=RWin
"""
import json
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "HIDTester")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "tables")
OUT.mkdir(parents=True, exist_ok=True)

METHOD_RE = re.compile(r"private void (\w+)_Click\(object sender, EventArgs e\)\s*\{", re.M)
ASSIGN_RE = re.compile(
    r"Data_Send_Buff\[FormMain\.KeyParam\.(\w+)(?:\s*([+-])\s*(\d+))?\]\s*(?:\|=|=)\s*([^;]+);"
)
TEXT_RE = re.compile(r'\(\(Control\)(\w+)\)\.Text = "([^"]*)"')


def split_methods(text):
    """Yield (method_name, body) for every private void X_Click(...) in the file."""
    marks = [(m.start(), m.group(1)) for m in METHOD_RE.finditer(text)]
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        yield name, text[pos:end]


def const_of(expr):
    expr = expr.strip()
    if expr == "byte.MaxValue":
        return 255
    if expr.startswith("0x") or expr.startswith("0X"):
        return int(expr, 16)
    try:
        return int(expr)
    except ValueError:
        return None


def parse(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    labels = dict(TEXT_RE.findall(text))  # control name -> displayed text
    rows = {}
    for name, body in split_methods(text):
        ctl = name.split("_Click")[0]
        writes = []
        for slot, op, off, val in ASSIGN_RE.findall(body):
            v = const_of(val)
            if v is None:
                continue
            writes.append({"slot": slot, "op": op or "=", "offset": int(off or 0), "val": v})
        if writes:
            rows[ctl] = {"label": labels.get(ctl, ctl), "writes": writes}
    return rows


def main():
    out = {}
    for f in sorted(SRC.glob("*.cs")):
        if not f.name.endswith("Keys.cs") and f.name not in (
            "MULKey.cs",
            "MouseKey.cs",
            "LEDkey.cs",
            "FunKey.cs",
        ):
            continue
        rows = parse(f)
        if rows:
            out[f.stem] = rows
            print(f"# {f.name}: {len(rows)} entries")

    (OUT / "keytables.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    # readable summary: one line per entry -> target slot:value list
    lines = []
    for fname, rows in out.items():
        lines.append(f"\n## {fname}")
        for ctl, info in sorted(rows.items()):
            w = " ".join(
                f"{x['slot']}[{'+' if x['op'] == '|=' else '='}{x['offset']}]={x['val']}"
                for x in info["writes"]
            )
            lines.append(f"- {info['label']:<24} {w}")
    (OUT / "keytables.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote {OUT/'keytables.json'} and {OUT/'keytables.md'}")


if __name__ == "__main__":
    main()
