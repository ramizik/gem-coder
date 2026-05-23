package model

import (
	"os"
	"strings"

	"github.com/superagentic-ai/gemcoder/tui/internal/styles"
)

func renderMessage(m message, width int) string {
	var b strings.Builder
	switch m.role {
	case roleUser:
		b.WriteString(styles.UserMark.Render("›"))
		b.WriteString(" ")
		b.WriteString(styles.User.Render(m.text))
	case roleAgent:
		b.WriteString(styles.AgentMark.Render("✦"))
		b.WriteString(" ")
		b.WriteString(m.text)
		if strings.TrimSpace(m.diff) != "" {
			b.WriteString("\n\n")
			b.WriteString(styles.Diff.Render(indent(m.diff, "    ")))
		}
	case roleSystem:
		b.WriteString(styles.System.Render(m.text))
	case roleError:
		b.WriteString(styles.Err.Render("✖ " + m.text))
	}
	return b.String()
}

func indent(s, prefix string) string {
	lines := strings.Split(s, "\n")
	for i, l := range lines {
		lines[i] = prefix + l
	}
	return strings.Join(lines, "\n")
}

func homeDir() string {
	h, _ := os.UserHomeDir()
	return h
}
