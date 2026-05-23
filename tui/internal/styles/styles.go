// Package styles centralizes Lipgloss styles for the chat TUI.
package styles

import "github.com/charmbracelet/lipgloss"

var (
	Accent    = lipgloss.Color("#7D56F4")
	Soft      = lipgloss.Color("99")
	Subtle    = lipgloss.Color("241")
	Dim       = lipgloss.Color("238")
	Good      = lipgloss.Color("42")
	Bad       = lipgloss.Color("196")
	Highlight = lipgloss.Color("212")
)

var (
	Header = lipgloss.NewStyle().
		Foreground(Subtle).
		Bold(true)

	Hint = lipgloss.NewStyle().
		Foreground(Dim).
		Italic(true)

	Status = lipgloss.NewStyle().
		Foreground(Subtle).
		Background(lipgloss.Color("235")).
		Padding(0, 1)

	UserMark = lipgloss.NewStyle().
			Foreground(Accent).
			Bold(true)

	User = lipgloss.NewStyle().
		Foreground(lipgloss.Color("253"))

	AgentMark = lipgloss.NewStyle().
			Foreground(Highlight).
			Bold(true)

	System = lipgloss.NewStyle().
		Foreground(Subtle).
		Italic(true)

	StepMeta = lipgloss.NewStyle().
			Foreground(Dim).
			Italic(true)

	Err = lipgloss.NewStyle().
		Foreground(Bad).
		Bold(true)

	Diff = lipgloss.NewStyle().
		Foreground(Soft)

	DiffAdd        = lipgloss.NewStyle().Foreground(lipgloss.Color("42"))  // green
	DiffDel        = lipgloss.NewStyle().Foreground(lipgloss.Color("203")) // red
	DiffHunk       = lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Bold(true)
	DiffMeta       = lipgloss.NewStyle().Foreground(Subtle)
	DiffFileHeader = lipgloss.NewStyle().Foreground(Highlight).Bold(true)

	// InputBox wraps the textarea with a rounded border when idle.
	InputBox = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(Subtle).
			Padding(0, 1)

	// InputBoxBusy dims the border while a run is in flight.
	InputBoxBusy = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(Dim).
			Padding(0, 1)

	// Backend tags used to distinguish step lines when both backends stream
	// into the same viewport (e.g. `gemcoder serve --backend both`).
	LocalTag  = lipgloss.NewStyle().Foreground(lipgloss.Color("36")).Bold(true)  // cyan
	RemoteTag = lipgloss.NewStyle().Foreground(lipgloss.Color("213")).Bold(true) // pink
)
