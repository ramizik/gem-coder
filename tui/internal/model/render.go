package model

import (
	"fmt"
	"os"
	"strings"

	"github.com/charmbracelet/glamour"

	"github.com/superagentic-ai/gemcoder/tui/internal/styles"
)

// newGlamour builds a TermRenderer sized to wrap at `width` columns. We clamp
// to a minimum so very narrow windows still render; on error we fall back to
// width 80 so the caller always gets a usable renderer (nil only if glamour
// itself fails for the fallback width too).
func newGlamour(width int) *glamour.TermRenderer {
	if width < 20 {
		width = 20
	}
	r, err := glamour.NewTermRenderer(
		glamour.WithAutoStyle(),
		glamour.WithWordWrap(width),
	)
	if err != nil {
		r, err = glamour.NewTermRenderer(
			glamour.WithAutoStyle(),
			glamour.WithWordWrap(80),
		)
		if err != nil {
			return nil
		}
	}
	return r
}

func (m *Model) renderMessage(msg message, width int) string {
	var b strings.Builder
	switch msg.role {
	case roleUser:
		b.WriteString(styles.UserMark.Render("›"))
		b.WriteString(" ")
		b.WriteString(styles.User.Render(msg.text))
	case roleAgent:
		b.WriteString(styles.AgentMark.Render("✦"))
		b.WriteString(" ")
		b.WriteString(m.renderAgentProse(msg.text, msg.streaming))
		if strings.TrimSpace(msg.diff) != "" {
			b.WriteString("\n\n")
			b.WriteString(indent(renderDiff(msg.diff), "    "))
		}
	case roleSystem:
		b.WriteString(styles.System.Render(msg.text))
	case roleStep:
		b.WriteString(styles.StepMeta.Render(msg.text))
	case roleError:
		b.WriteString(styles.Err.Render("✖ " + msg.text))
	}
	return b.String()
}

// renderAgentProse glamour-renders agent text once streaming is complete.
// During streaming we render plain so partial markdown doesn't reflow noisily.
func (m *Model) renderAgentProse(text string, streaming bool) string {
	if streaming || m.glamour == nil || text == "" {
		return text
	}
	out, err := m.glamour.Render(text)
	if err != nil {
		return text
	}
	return strings.TrimRight(out, "\n")
}

// renderDiff splits the blob into per-file sections by detecting
// `diff --git ` lines. Each section gets a styled header showing the file
// path and +N −N counts; the body keeps the existing per-line coloring.
func renderDiff(diff string) string {
	lines := strings.Split(diff, "\n")
	type section struct {
		path  string
		adds  int
		dels  int
		lines []string
	}
	var sections []section
	cur := -1
	for _, line := range lines {
		if strings.HasPrefix(line, "diff --git ") {
			sections = append(sections, section{path: extractDiffPath(line)})
			cur = len(sections) - 1
			sections[cur].lines = append(sections[cur].lines, line)
			continue
		}
		if cur < 0 {
			// Preamble before any `diff --git` header — keep as its own
			// implicit section so we don't drop content.
			sections = append(sections, section{})
			cur = 0
		}
		sections[cur].lines = append(sections[cur].lines, line)
		switch {
		case strings.HasPrefix(line, "+++") || strings.HasPrefix(line, "---"):
			// file header lines don't count as added/deleted content
		case strings.HasPrefix(line, "+"):
			sections[cur].adds++
		case strings.HasPrefix(line, "-"):
			sections[cur].dels++
		}
	}
	var b strings.Builder
	for i, s := range sections {
		if i > 0 {
			b.WriteString("\n\n")
		}
		if s.path != "" {
			header := fmt.Sprintf("▎ %s  +%d −%d", s.path, s.adds, s.dels)
			b.WriteString(styles.DiffFileHeader.Render(header))
			b.WriteString("\n")
		}
		b.WriteString(renderDiffLines(s.lines))
	}
	return b.String()
}

// renderDiffLines applies per-line coloring (additions, deletions, hunks,
// meta) to a slice of raw diff lines.
func renderDiffLines(lines []string) string {
	var b strings.Builder
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

// extractDiffPath returns the b/<path> from a `diff --git a/foo b/foo` line.
// Falls back to the a/<path> form, then to the raw remainder.
func extractDiffPath(line string) string {
	rest := strings.TrimPrefix(line, "diff --git ")
	fields := strings.Fields(rest)
	if len(fields) >= 2 {
		b := strings.TrimPrefix(fields[1], "b/")
		if b != "" {
			return b
		}
		return strings.TrimPrefix(fields[0], "a/")
	}
	return rest
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
