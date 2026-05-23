// Package model implements the chat-style Bubble Tea TUI for GemCoder.
package model

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/superagentic-ai/gemcoder/tui/internal/rpc"
	"github.com/superagentic-ai/gemcoder/tui/internal/styles"
)

type role int

const (
	roleUser role = iota
	roleAgent
	roleSystem
	roleError
	roleStep
)

type message struct {
	role      role
	text      string
	diff      string
	runID     string
	applied   bool
	streaming bool
}

// StreamChunkMsg is exported so main.go's RPC notification handler can send it.
type StreamChunkMsg struct {
	Delta string
}

// StreamEventMsg carries one orchestrator step event from the JSON-RPC
// `run.event` notification so the TUI can render a live step line.
type StreamEventMsg struct {
	Kind    string
	Backend string
	Text    string
	Data    string
}

type infoMsg struct {
	info *rpc.Info
	err  error
}

type runDoneMsg struct {
	detail *rpc.RunDetail
	err    error
}

type applyDoneMsg struct {
	result *rpc.ApplyResult
	err    error
}

type verifyDoneMsg struct {
	results []rpc.VerifyResult
	err     error
}

type initDoneMsg struct {
	result *rpc.InitResult
	err    error
}

type shellDoneMsg struct {
	result *rpc.ShellResult
	err    error
}

type Model struct {
	client *rpc.Client

	info     *rpc.Info
	history  []message
	input    textinput.Model
	viewport viewport.Model
	spinner  spinner.Model

	busy           bool
	busyStart      time.Time
	busyLabel      string
	lastRunID      string
	lastPatch      string
	lastBackend    string
	currentBackend string
	lastEvent      string
	width          int
	height         int
}

// backendCycle drives Ctrl+B — order chosen so the most common toggle
// (auto ↔ remote) is two presses, and `both` is opt-in last.
var backendCycle = []string{"", "local", "remote", "both"}

func New(client *rpc.Client) Model {
	ti := textinput.New()
	ti.Placeholder = "Describe a coding task, or type /help…"
	ti.Prompt = "› "
	ti.Focus()
	ti.CharLimit = 4000

	vp := viewport.New(0, 0)

	sp := spinner.New()
	sp.Spinner = spinner.Dot
	sp.Style = lipgloss.NewStyle().Foreground(styles.Accent)

	return Model{
		client:   client,
		input:    ti,
		viewport: vp,
		spinner:  sp,
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(m.fetchInfo(), m.spinner.Tick)
}

func (m Model) fetchInfo() tea.Cmd {
	return func() tea.Msg {
		info, err := m.client.Info()
		return infoMsg{info: info, err: err}
	}
}

func (m Model) startRun(task string) tea.Cmd {
	backend := m.currentBackend
	return func() tea.Msg {
		d, err := m.client.StartRun(task, backend)
		return runDoneMsg{detail: d, err: err}
	}
}

func (m Model) apply(runID string) tea.Cmd {
	return func() tea.Msg {
		r, err := m.client.Apply(runID, false)
		return applyDoneMsg{result: r, err: err}
	}
}

func (m Model) verify() tea.Cmd {
	return func() tea.Msg {
		r, err := m.client.Verify("")
		return verifyDoneMsg{results: r, err: err}
	}
}

func (m Model) initRepo() tea.Cmd {
	return func() tea.Msg {
		r, err := m.client.Init(false)
		return initDoneMsg{result: r, err: err}
	}
}

func (m Model) shell(command string) tea.Cmd {
	return func() tea.Msg {
		r, err := m.client.Shell(command)
		return shellDoneMsg{result: r, err: err}
	}
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.layout()
		m.rerender()
	case infoMsg:
		if msg.err != nil {
			m.push(roleError, "server info failed: "+msg.err.Error(), "")
		} else {
			m.info = msg.info
			banner := fmt.Sprintf("GemCoder · %s · %s", msg.info.Model, prettyRoot(msg.info.Root))
			m.push(roleSystem, banner, "")
			if !msg.info.Initialized {
				m.push(roleSystem, "No gemcoder.yaml here. Type /init to scaffold this repo.", "")
			} else {
				m.push(roleSystem, "Type a task. Prefix with ! to run a local shell command. /help for commands.", "")
			}
		}
		m.rerender()
	case StreamChunkMsg:
		if !m.busy {
			break
		}
		idx := m.lastStreamingAgentIdx()
		if idx < 0 {
			m.history = append(m.history, message{role: roleAgent, text: msg.Delta, streaming: true})
		} else {
			m.history[idx].text += msg.Delta
		}
		m.rerender()
	case StreamEventMsg:
		// `token` is already streamed via run.chunk; skip to avoid double-render.
		if msg.Kind == "token" {
			break
		}
		m.lastEvent = msg.Kind
		if msg.Backend != "" {
			m.lastEvent += " [" + msg.Backend + "]"
		}
		line := formatStepEvent(msg)
		if line == "" {
			break
		}
		// Steps render as their own dim italic line, kept above any later
		// agent prose so the user sees the full step trail as it happens.
		idx := m.lastStreamingAgentIdx()
		stepMsg := message{role: roleStep, text: line}
		if idx < 0 {
			m.history = append(m.history, stepMsg)
		} else {
			// Insert step line just before the in-flight streaming agent
			// message so prose stays at the bottom.
			m.history = append(m.history, message{})
			copy(m.history[idx+1:], m.history[idx:])
			m.history[idx] = stepMsg
		}
		m.rerender()
	case runDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, msg.err.Error(), "")
		} else {
			recID := msg.detail.RunID
			if recID == "" && msg.detail.Record != nil {
				recID, _ = msg.detail.Record["run_id"].(string)
			}
			m.lastRunID = recID
			m.lastPatch = msg.detail.Patch
			m.lastBackend = msg.detail.Backend
			idx := m.lastStreamingAgentIdx()
			if idx >= 0 {
				m.history[idx].text = msg.detail.Summary
				m.history[idx].diff = msg.detail.Patch
				m.history[idx].streaming = false
			} else {
				m.push(roleAgent, msg.detail.Summary, msg.detail.Patch)
			}
		}
		m.rerender()
	case applyDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "apply failed: "+msg.err.Error(), "")
		} else if !msg.result.OK {
			m.push(roleError, "apply failed:\n"+msg.result.Stderr, "")
		} else {
			m.push(roleSystem, fmt.Sprintf("Applied %d file(s): %s", len(msg.result.Files), strings.Join(msg.result.Files, ", ")), "")
		}
		m.rerender()
	case verifyDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "verify failed: "+msg.err.Error(), "")
		} else if len(msg.results) == 0 {
			m.push(roleSystem, "No verification commands configured in gemcoder.yaml.", "")
		} else {
			var b strings.Builder
			for _, r := range msg.results {
				tag := "pass"
				if r.ReturnCode != 0 {
					tag = "fail"
				}
				fmt.Fprintf(&b, "  %s · %s\n", r.Command, tag)
			}
			m.push(roleSystem, "Verification:\n"+b.String(), "")
		}
		m.rerender()
	case initDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "init failed: "+msg.err.Error(), "")
		} else if len(msg.result.Written) == 0 {
			m.push(roleSystem, "Already initialized. Use /init force to overwrite.", "")
		} else {
			m.push(roleSystem, "Initialized:\n  "+strings.Join(msg.result.Written, "\n  "), "")
		}
		cmds = append(cmds, m.fetchInfo())
		m.rerender()
	case shellDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "shell failed: "+msg.err.Error(), "")
		} else {
			m.push(roleSystem, renderShellResult(msg.result), "")
		}
		m.rerender()
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			return m, tea.Quit
		case "ctrl+l":
			m.viewport.SetContent("")
			m.viewport.GotoTop()
		case "ctrl+h":
			if cmd := m.handleCommand("/help"); cmd != nil {
				cmds = append(cmds, cmd)
			}
		case "ctrl+a":
			if !m.busy {
				if cmd := m.handleCommand("/apply"); cmd != nil {
					cmds = append(cmds, cmd)
				}
			}
		case "ctrl+e":
			if !m.busy {
				if cmd := m.handleCommand("/verify"); cmd != nil {
					cmds = append(cmds, cmd)
				}
			}
		case "ctrl+p":
			if !m.busy {
				if cmd := m.handleCommand("/patch"); cmd != nil {
					cmds = append(cmds, cmd)
				}
			}
		case "ctrl+r":
			if !m.busy {
				if cmd := m.handleCommand("/reset"); cmd != nil {
					cmds = append(cmds, cmd)
				}
			}
		case "ctrl+b":
			if !m.busy {
				m.cycleBackend()
			}
		case "enter":
			if m.busy {
				break
			}
			text := strings.TrimSpace(m.input.Value())
			if text == "" {
				break
			}
			m.input.Reset()
			if cmd := m.handleInput(text); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
	}

	var icmd tea.Cmd
	m.input, icmd = m.input.Update(msg)
	cmds = append(cmds, icmd)
	var vcmd tea.Cmd
	m.viewport, vcmd = m.viewport.Update(msg)
	cmds = append(cmds, vcmd)
	return m, tea.Batch(cmds...)
}

func (m *Model) handleInput(text string) tea.Cmd {
	if strings.HasPrefix(text, "/") {
		return m.handleCommand(text)
	}
	if strings.HasPrefix(text, "!") {
		command := strings.TrimSpace(text[1:])
		if command == "" {
			m.push(roleError, "Usage: ! <command>   (e.g. ! ls, ! git status)", "")
			m.rerender()
			return nil
		}
		m.push(roleUser, "$ "+command, "")
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "running local command"
		m.rerender()
		return m.shell(command)
	}
	m.push(roleUser, text, "")
	m.busy = true
	m.busyStart = time.Now()
	m.busyLabel = "thinking"
	m.rerender()
	return m.startRun(text)
}

func (m *Model) handleCommand(text string) tea.Cmd {
	parts := strings.Fields(text)
	cmd := parts[0]
	switch cmd {
	case "/quit", "/exit", "/q":
		return tea.Quit
	case "/help", "/?":
		m.push(roleSystem,
			"Commands:\n"+
				"  /init [force]            scaffold gemcoder in this repo\n"+
				"  /apply                   apply the most recent run's patch\n"+
				"  /patch                   preview the most recent run's patch\n"+
				"  /verify                  run configured verification commands\n"+
				"  /runs                    list recent runs\n"+
				"  /show <run-id>           load a previous run into the chat\n"+
				"  /reset                   clear conversation history\n"+
				"  /shell <cmd>             run a local inspection command (also: !<cmd>)\n"+
				"  /backend [local|remote|auto|both]   show or set the backend for new runs\n"+
				"  /quit                    exit\n"+
				"\n"+
				"Shortcuts:\n"+
				"  Ctrl+A apply   Ctrl+P preview   Ctrl+E verify   Ctrl+B cycle backend\n"+
				"  Ctrl+R reset   Ctrl+L clear     Ctrl+H help     Ctrl+C quit\n"+
				"\n"+
				"Anything you type goes to Gemini as a coding task with the last 10 turns of context. Prefix with ! to run a local shell command instead.",
			"")
		m.rerender()
		return nil
	case "/backend":
		if len(parts) < 2 {
			m.push(roleSystem, "Current backend: "+m.backendLabel(), "")
			m.rerender()
			return nil
		}
		switch parts[1] {
		case "local":
			m.currentBackend = "local"
		case "remote":
			m.currentBackend = "remote"
		case "both":
			m.currentBackend = "both"
		case "auto":
			m.currentBackend = ""
		default:
			m.push(roleError, "Usage: /backend [local|remote|auto|both]", "")
			m.rerender()
			return nil
		}
		m.push(roleSystem, "Backend set to: "+m.backendLabel(), "")
		m.rerender()
		return nil
	case "/reset":
		if err := m.client.ResetSession(); err != nil {
			m.push(roleError, "reset failed: "+err.Error(), "")
		} else {
			m.history = nil
			m.lastRunID = ""
			m.push(roleSystem, "Conversation history cleared.", "")
		}
		m.rerender()
		return nil
	case "/shell", "/sh":
		command := strings.TrimSpace(strings.TrimPrefix(text, cmd))
		if command == "" {
			m.push(roleError, "Usage: "+cmd+" <ls|pwd|git status|git branch|git log>", "")
			m.rerender()
			return nil
		}
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "running local command"
		m.push(roleUser, "$ "+command, "")
		m.rerender()
		return m.shell(command)
	case "/init":
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "initializing"
		m.push(roleSystem, "Initializing…", "")
		m.rerender()
		return m.initRepo()
	case "/apply":
		if m.lastRunID == "" {
			m.push(roleError, "No run to apply yet.", "")
			m.rerender()
			return nil
		}
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "applying"
		m.push(roleSystem, "Applying patch from "+m.lastRunID+"…", "")
		m.rerender()
		return m.apply(m.lastRunID)
	case "/patch":
		if m.lastRunID == "" {
			m.push(roleError, "No run yet — type a task first.", "")
			m.rerender()
			return nil
		}
		if strings.TrimSpace(m.lastPatch) == "" {
			m.push(roleSystem, "Last run produced no patch.", "")
			m.rerender()
			return nil
		}
		m.push(roleSystem, "Patch preview · "+m.lastRunID+" (use /apply or Ctrl+A to apply)", m.lastPatch)
		m.rerender()
		return nil
	case "/runs":
		runs, err := m.client.ListRuns()
		if err != nil {
			m.push(roleError, "list_runs failed: "+err.Error(), "")
			m.rerender()
			return nil
		}
		if len(runs) == 0 {
			m.push(roleSystem, "No runs yet.", "")
			m.rerender()
			return nil
		}
		// Show the last 10, newest first.
		start := 0
		if len(runs) > 10 {
			start = len(runs) - 10
		}
		var b strings.Builder
		b.WriteString("Recent runs (newest last) — /show <id> to load:\n")
		for i := len(runs) - 1; i >= start; i-- {
			b.WriteString("  ")
			b.WriteString(runs[i])
			if runs[i] == m.lastRunID {
				b.WriteString("  (current)")
			}
			b.WriteString("\n")
		}
		m.push(roleSystem, strings.TrimRight(b.String(), "\n"), "")
		m.rerender()
		return nil
	case "/show":
		if len(parts) < 2 {
			m.push(roleError, "Usage: /show <run-id>   (try /runs to list)", "")
			m.rerender()
			return nil
		}
		runID := parts[1]
		detail, err := m.client.GetRun(runID)
		if err != nil {
			m.push(roleError, "get_run failed: "+err.Error(), "")
			m.rerender()
			return nil
		}
		m.lastRunID = runID
		m.lastPatch = detail.Patch
		summary := detail.Summary
		if summary == "" {
			summary = "(no summary recorded for " + runID + ")"
		}
		m.push(roleAgent, summary, detail.Patch)
		m.rerender()
		return nil
	case "/verify":
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "verifying"
		m.push(roleSystem, "Running verification…", "")
		m.rerender()
		return m.verify()
	default:
		m.push(roleError, "Unknown command: "+cmd+". Try /help.", "")
		m.rerender()
		return nil
	}
}

func renderShellResult(result *rpc.ShellResult) string {
	var b strings.Builder
	fmt.Fprintf(&b, "$ %s", result.Command)
	if result.Stdout != "" {
		fmt.Fprintf(&b, "\n%s", strings.TrimRight(result.Stdout, "\n"))
	}
	if result.Stderr != "" {
		fmt.Fprintf(&b, "\n%s", strings.TrimRight(result.Stderr, "\n"))
	}
	if result.ReturnCode != 0 {
		fmt.Fprintf(&b, "\n(exit %d)", result.ReturnCode)
	}
	return b.String()
}

func (m *Model) push(r role, text, diff string) {
	m.history = append(m.history, message{role: r, text: text, diff: diff})
}

func (m *Model) lastStreamingAgentIdx() int {
	for i := len(m.history) - 1; i >= 0; i-- {
		if m.history[i].role == roleAgent && m.history[i].streaming {
			return i
		}
	}
	return -1
}

func (m *Model) layout() {
	if m.width == 0 || m.height == 0 {
		return
	}
	headerH := 1
	inputH := 1
	statusH := 1
	hintH := 1
	bodyH := m.height - headerH - inputH - statusH - hintH - 1
	if bodyH < 4 {
		bodyH = 4
	}
	m.viewport.Width = m.width
	m.viewport.Height = bodyH
	m.input.Width = m.width - 2
}

func (m *Model) cycleBackend() {
	idx := 0
	for i, b := range backendCycle {
		if b == m.currentBackend {
			idx = i
			break
		}
	}
	idx = (idx + 1) % len(backendCycle)
	m.currentBackend = backendCycle[idx]
	m.push(roleSystem, "Backend cycled to: "+m.backendLabel(), "")
	m.rerender()
}

func (m Model) backendLabel() string {
	if m.currentBackend == "" {
		return "auto (server default)"
	}
	return m.currentBackend
}

func (m *Model) rerender() {
	var b strings.Builder
	for _, msg := range m.history {
		b.WriteString(renderMessage(msg, m.width))
		b.WriteString("\n")
	}
	m.viewport.SetContent(b.String())
	m.viewport.GotoBottom()
}

func (m Model) View() string {
	if m.width == 0 {
		return "loading…"
	}
	header := styles.Header.Render(m.headerText())
	body := m.viewport.View()
	prompt := m.input.View()
	if m.busy {
		elapsed := int(time.Since(m.busyStart).Seconds())
		label := m.busyLabel
		if label == "" {
			label = "working"
		}
		prompt = fmt.Sprintf("%s %s… %ds  (Ctrl+C to cancel)", m.spinner.View(), label, elapsed)
	}
	status := m.statusLine()
	hint := styles.Hint.Render(m.hintLine())
	return strings.Join([]string{header, body, status, prompt, hint}, "\n")
}

// statusLine renders the bottom always-on info row: project · backend ·
// last run · live state. Truncates to the viewport width so it never wraps.
func (m Model) statusLine() string {
	var parts []string
	if m.info != nil {
		parts = append(parts, m.info.Project)
		parts = append(parts, "model:"+m.info.Model)
	}
	parts = append(parts, "backend:"+m.backendLabel())
	if m.lastRunID != "" {
		short := m.lastRunID
		if len(short) > 16 {
			short = short[:16] + "…"
		}
		runStr := "run:" + short
		if m.lastBackend != "" && m.lastBackend != m.currentBackend {
			runStr += "(" + m.lastBackend + ")"
		}
		parts = append(parts, runStr)
	}
	if m.busy {
		elapsed := int(time.Since(m.busyStart).Seconds())
		label := m.busyLabel
		if label == "" {
			label = "working"
		}
		parts = append(parts, styles.StatusBarBusy.Render(fmt.Sprintf("%s %ds", label, elapsed)))
	} else if m.lastEvent != "" {
		parts = append(parts, "last:"+m.lastEvent)
	}
	line := strings.Join(parts, "  ·  ")
	// Truncate before lipgloss styling so we don't blow the line width.
	if m.width > 4 && lipgloss.Width(line) > m.width-2 {
		// Width-aware trim: render width may differ from byte width with
		// styled content, but parts here are mostly plain.
		runes := []rune(line)
		if len(runes) > m.width-3 {
			runes = runes[:m.width-3]
			line = string(runes) + "…"
		}
	}
	return styles.StatusBar.Width(m.width).Render(line)
}

// hintLine adapts to the current state: streaming → cancel hint, have-patch
// → apply/preview, idle → top shortcuts.
func (m Model) hintLine() string {
	if m.busy {
		return "Ctrl+C cancel  ·  pgup/pgdn scroll"
	}
	if m.lastRunID != "" && strings.TrimSpace(m.lastPatch) != "" {
		return "Ctrl+A apply  ·  Ctrl+P preview  ·  Ctrl+E verify  ·  Ctrl+B backend  ·  /help"
	}
	return "Ctrl+B backend  ·  Ctrl+E verify  ·  Ctrl+R reset  ·  Ctrl+L clear  ·  /help"
}

func (m Model) headerText() string {
	if m.info == nil {
		return "GemCoder"
	}
	base := fmt.Sprintf("GemCoder · %s · %s", m.info.Model, prettyRoot(m.info.Root))
	if m.currentBackend != "" {
		base += " · backend:" + m.currentBackend
	}
	return base
}

// formatStepEvent renders a single run.event notification as a one-line
// step trail entry, e.g. `· backend.selected [local]: routing to local SDK`.
// Returns "" for events that should not be shown (empty / uninteresting).
func formatStepEvent(msg StreamEventMsg) string {
	kind := msg.Kind
	if kind == "" {
		return ""
	}
	var b strings.Builder
	b.WriteString("· ")
	b.WriteString(kind)
	if msg.Backend != "" {
		b.WriteString(" [")
		b.WriteString(msg.Backend)
		b.WriteString("]")
	}
	text := strings.TrimSpace(msg.Text)
	if text != "" {
		// Keep step lines compact; collapse newlines so one event = one line.
		text = strings.ReplaceAll(text, "\n", " ")
		if len(text) > 160 {
			text = text[:157] + "…"
		}
		b.WriteString(": ")
		b.WriteString(text)
	} else if msg.Data != "" && msg.Data != "{}" {
		b.WriteString(" ")
		b.WriteString(msg.Data)
	}
	return b.String()
}

func prettyRoot(p string) string {
	if p == "" {
		return ""
	}
	home := homeDir()
	if home != "" && strings.HasPrefix(p, home) {
		return "~" + strings.TrimPrefix(p, home)
	}
	return p
}
