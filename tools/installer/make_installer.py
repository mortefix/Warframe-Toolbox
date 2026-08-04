"""Generate the Discord-able installer from the template + a GitHub token.

    python tools/installer/make_installer.py github_pat_XXX [-o out.bat]

The token is a fine-grained PAT (repo-scoped, Contents: Read-only, no
expiry). It is embedded in the clone URL, so the app itself never touches
credentials - revoking the token on GitHub is the kill switch."""
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "install-template.bat"
PLACEHOLDER = "__GITHUB_TOKEN__"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("token")
    ap.add_argument("-o", "--out",
                    default=str(HERE / "Install Warframe Toolbox.bat"))
    args = ap.parse_args()
    if not args.token.startswith("github_pat_"):
        raise SystemExit("that does not look like a fine-grained PAT "
                         "(expected github_pat_...)")
    text = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        raise SystemExit("placeholder missing from template")
    Path(args.out).write_text(text.replace(PLACEHOLDER, args.token),
                              encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
