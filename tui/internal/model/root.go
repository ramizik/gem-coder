// Package model implements the chat-style Bubble Tea TUI for GemCoder.
package model

import (
	"fmt"
	"strings"

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
)

type message struct {
	role    role
	text    string
	diff    string
	runID   string
	applied bool
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

type Model struct {
	client *rpc.Client

	info     *rpc.Info
	history  []message
	input    textinput.Model
	viewport viewport.Model
	spinner  spinner.Model

	busy        bool
	lastRunID   string
	width       int
	height      int
}

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
	return func() tea.Msg {
		d, err := m.client.StartRun(task)
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
				m.push(roleSystem, "Type a task. Slash commands: /apply /verify /init /help /quit", "")
			}
		}
		m.rerender()
	case runDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, msg.err.Error(), "")
		} else {
			recID, _ := msg.detail.Record["run_id"].(string)
			m.lastRunID = recID
			m.push(roleAgent, msg.detail.Summary, msg.detail.Patch)
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
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)
	case tea.KeyMsg:
		switch msg.String() {
		case "ctrl+c", "ctrl+d":
			return m, tea.Quit
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
	m.push(roleUser, text, "")
	m.busy = true
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
				"  /init [force]  scaffold gemcoder in this repo\n"+
				"  /apply         apply the most recent run's patch\n"+
				"  /verify        run configured verification commands\n"+
				"  /quit          exit\n"+
				"Anything else: a coding task sent to Gemini.",
			"")
		m.rerender()
		return nil
	case "/init":
		m.busy = true
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
		m.push(roleSystem, "Applying patch from "+m.lastRunID+"…", "")
		m.rerender()
		return m.apply(m.lastRunID)
	case "/verify":
		m.busy = true
		m.push(roleSystem, "Running verification…", "")
		m.rerender()
		return m.verify()
	default:
		m.push(roleError, "Unknown command: "+cmd+". Try /help.", "")
		m.rerender()
		return nil
	}
}

func (m *Model) push(r role, text, diff string) {
	m.history = append(m.history, message{role: r, text: text, diff: diff})
}

func (m *Model) layout() {
	if m.width == 0 || m.height == 0 {
		return
	}
	headerH := 1
	inputH := 1
	hintH := 1
	bodyH := m.height - headerH - inputH - hintH - 1
	if bodyH < 4 {
		bodyH = 4
	}
	m.viewport.Width = m.width
	m.viewport.Height = bodyH
	m.input.Width = m.width - 2
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
		prompt = m.spinner.View() + " thinking… (press Ctrl+C to cancel)"
	}
	hint := styles.Hint.Render("/apply  /verify  /init  /help  /quit")
	return strings.Join([]string{header, body, prompt, hint}, "\n")
}

func (m Model) headerText() string {
	if m.info == nil {
		return "GemCoder"
	}
	return fmt.Sprintf("GemCoder · %s · %s", m.info.Model, prettyRoot(m.info.Root))
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
