package model

import (
	"os"
	"strings"

	"github.com/charmbracelet/glamour"

	"github.com/superagentic-ai/gemcoder/tui/internal/styles"
)

// glamourRenderer is a process-wide renderer reused across messages.
// nil means initialization failed; we fall back to plain text in that case.
var glamourRenderer = func() *glamour.TermRenderer {
	r, err := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(0), // let the viewport handle wrapping
	)
	if err != nil {
		return nil
	}
	return r
}()

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
		b.WriteString(renderAgentProse(m.text, m.streaming))
		if strings.TrimSpace(m.diff) != "" {
			b.WriteString("\n\n")
			b.WriteString(indent(renderDiff(m.diff), "    "))
		}
	case roleSystem:
		b.WriteString(styles.System.Render(m.text))
	case roleStep:
		b.WriteString(styles.StepMeta.Render(m.text))
	case roleError:
		b.WriteString(styles.Err.Render("✖ " + m.text))
	}
	return b.String()
}

// renderAgentProse glamour-renders agent text once streaming is complete.
// During streaming we render plain so partial markdown doesn't reflow noisily.
func renderAgentProse(text string, streaming bool) string {
	if streaming || glamourRenderer == nil || text == "" {
		return text
	}
	out, err := glamourRenderer.Render(text)
	if err != nil {
		return text
	}
	return strings.TrimRight(out, "\n")
}

func renderDiff(diff string) string {
	var b strings.Builder
	lines := strings.Split(diff, "\n")
	for i, line := range lines {
		var styled string
		switch {
		case strings.HasPrefix(line, "+++") || strings.HasPrefix(line, "---") ||
			strings.HasPrefix(line, "diff --git ") || strings.HasPrefix(line, "index "):
			styled = styles.DiffMeta.Render(line)
		case strings.HasPrefix(line, "@@"):
			styled = styles.DiffHunk.Render(line)
		case strings.HasPrefix(line, "+"):
			styled = styles.DiffAdd.Render(line)
		case strings.HasPrefix(line, "-"):
			styled = styles.DiffDel.Render(line)
		default:
			styled = styles.Diff.Render(line)
		}
		b.WriteString(styled)
		if i < len(lines)-1 {
			b.WriteString("\n")
		}
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
