# vhs script for the dscache 10-minute happy path → rendered to assets/demo.gif in CI.
# https://github.com/charmbracelet/vhs
Output assets/demo.gif

Set FontSize 18
Set Width 1100
Set Height 640
Set Padding 20
Set Theme "Dracula"

Type "pip install dscache"
Enter
Sleep 1s

Type "# wrap your DeepSeek client in two lines, run your agent loop, then:"
Enter
Sleep 800ms

Type "dscache demo"
Enter
Sleep 3s

Type "dscache suggest"
Enter
Sleep 3s
