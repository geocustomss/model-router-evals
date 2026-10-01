# Demo and screenshot plan

## 1. Record a GIF / Loom of the whole flow
```bash
bash demo.sh       # prints each command, pauses, runs it (PAUSE=0 bash demo.sh for an instant run)
```
Record it with any of: Loom (also good for the walkthrough video), [asciinema](https://asciinema.org) + `agg` to make a GIF,
[ScreenToGif](https://www.screentogif.com) (Windows) or [Kap](https://getkap.co) (macOS). Terminal tips: dark theme,
font size 18+, ~100 columns wide, short prompt (`export PS1='$ '`), and no personal paths or API keys on screen.

## 2. Hero screenshot
Capture the report table from `python -m router eval ...` (pass rate, latency, cost per model), cropped to include the 'Recommended routes' list.

Save as `docs/demo.png` (or `docs/demo.gif`) and add this under the first paragraph of the README:
```markdown
![demo](docs/demo.gif)
```

## 3. Things to point at while narrating
- Same eval cases, different models: the cheap one passes classification but fails reasoning.
- The recommendation is the *cheapest model above the pass-rate threshold*, per task type.
- `routes.generated.json` is the actual routing config the app would use.

## 4. Before you publish
Use your real-model report (`--out docs/real_report.md`) for the hero image; mock results are only for demos of the harness.
