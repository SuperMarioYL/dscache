# vhs tape — dscache happy path, rendered to assets/demo.gif in CI.
# Render in CI via charmbracelet/vhs-action (see .github/workflows/demo.yml),
# or locally: `vhs docs/demo.tape` (needs `dscache` on PATH: pip install -e .).
# https://github.com/charmbracelet/vhs
Output assets/demo.gif

Set Shell "bash"
Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 20
Set Theme "Dracula"

Type "# 1) Write a sample ledger (no API key) and print the prefix-cache P&L"
Enter
Sleep 700ms
Type "dscache demo"
Enter
Sleep 3s

Type "# 2) See the worst cache-bust and a prefix-reorder suggestion"
Enter
Sleep 700ms
Type "dscache suggest"
Enter
Sleep 3s
