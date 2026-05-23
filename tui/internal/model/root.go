// Package model implements the chat-style Bubble Tea TUI for GemCoder.
package model

import (
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/key"
	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"

	"github.com/superagentic-ai/gemcoder/tui/internal/rpc"
	"github.com/superagentic-ai/gemcoder/tui/internal/styles"
)

// maxPromptHistory bounds the recallable prompt list so a long session
// doesn't grow it unbounded.
const maxPromptHistory = 100

// slashCommands is the static list used by Tab completion. Keep in sync
// with handleCommand below.
var slashCommands = []string{
	"/init", "/apply", "/verify", "/reset", "/shell",
	"/backend", "/runs", "/smoke", "/help", "/quit", "/exit",
}

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

// applyDryDoneMsg carries the dry-run preview result that we show before
// asking for y/n confirmation.
type applyDryDoneMsg struct {
	result *rpc.ApplyResult
	err    error
}

// elapsedTickMsg fires once per second so the footer counter updates while busy.
type elapsedTickMsg time.Time

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

type runsDoneMsg struct {
	runs []rpc.RunSummary
	err  error
}

type smokeDoneMsg struct {
	results []rpc.SmokeResult
	err     error
}

type interruptDoneMsg struct {
	err error
}

type Model struct {
	client *rpc.Client

	info     *rpc.Info
	history  []message
	input    textarea.Model
	viewport viewport.Model
	spinner  spinner.Model

	busy                bool
	busyStart           time.Time
	busyLabel           string
	lastRunID           string
	lastResolvedBackend string
	currentBackend      string
	width               int
	height              int

	// pendingApply, when true, means we've shown a dry-run preview and are
	// blocking input until the user answers y/n.
	pendingApply      bool
	pendingApplyRunID string

	// glamour renders agent prose; recreated on WindowSizeMsg so word wrap
	// matches the current viewport width. nil falls back to plain text.
	glamour *glamour.TermRenderer

	// prompts is a bounded recall stack of submitted user prompts.
	// promptIdx == -1 means "no recall active"; otherwise it indexes into
	// prompts where 0 is the oldest. promptDraft holds the in-progress
	// text the user had typed before they started walking history so we
	// can restore it when they walk back past the newest entry.
	prompts     []string
	promptIdx   int
	promptDraft string
}

func New(client *rpc.Client) Model {
	ta := textarea.New()
	ta.Placeholder = "Describe a coding task, or type /help…   (Enter to submit, Shift+Enter for newline)"
	ta.CharLimit = 4000
	ta.ShowLineNumbers = false
	ta.SetHeight(1)
	ta.MaxHeight = 6
	// Show the prompt marker only on the first line so wrapped/multi-line
	// input stays visually flush.
	ta.SetPromptFunc(2, func(i int) string {
		if i == 0 {
			return "› "
		}
		return "  "
	})
	// Enter submits (handled in Update); Shift+Enter / Alt+Enter / Ctrl+J inserts a newline.
	ta.KeyMap.InsertNewline = key.NewBinding(
		key.WithKeys("ctrl+j", "shift+enter", "alt+enter"),
		key.WithHelp("shift+enter", "newline"),
	)
	ta.Focus()

	vp := viewport.New(0, 0)

	sp := spinner.New()
	sp.Spinner = spinner.Dot
	sp.Style = lipgloss.NewStyle().Foreground(styles.Accent)

	return Model{
		client:    client,
		input:     ta,
		viewport:  vp,
		spinner:   sp,
		glamour:   newGlamour(80),
		promptIdx: -1,
	}
}

func (m Model) Init() tea.Cmd {
	return tea.Batch(m.fetchInfo(), m.spinner.Tick, elapsedTick(), textarea.Blink)
}

// elapsedTick fires once per second to refresh the footer "elapsed" counter.
func elapsedTick() tea.Cmd {
	return tea.Tick(time.Second, func(t time.Time) tea.Msg { return elapsedTickMsg(t) })
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

// applyDry runs the apply RPC with dry_run=true so we can preview the files
// that would change before asking for y/n confirmation.
func (m Model) applyDry(runID string) tea.Cmd {
	return func() tea.Msg {
		r, err := m.client.Apply(runID, true)
		return applyDryDoneMsg{result: r, err: err}
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

func (m Model) listRuns() tea.Cmd {
	return func() tea.Msg {
		runs, err := m.client.ListRuns()
		return runsDoneMsg{runs: runs, err: err}
	}
}

func (m Model) smoke(backend string) tea.Cmd {
	return func() tea.Msg {
		results, err := m.client.Smoke("Say hello in five words.", backend, 30)
		return smokeDoneMsg{results: results, err: err}
	}
}

func (m Model) interrupt() tea.Cmd {
	return func() tea.Msg {
		return interruptDoneMsg{err: m.client.Interrupt()}
	}
}

// cancelRun fires the JSON-RPC cancel for the current run id and discards any
// error: the server may not implement `cancel_run` yet, in which case we
// still treat the local-side cancel (busy=false + system message) as success.
func (m Model) cancelRun(runID string) tea.Cmd {
	return func() tea.Msg {
		_ = m.client.Cancel(runID)
		return nil
	}
}

func (m Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd

	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		// Recreate the glamour renderer so word-wrap tracks the new width.
		m.glamour = newGlamour(m.width)
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
			m.push(roleError, enhanceError(msg.err.Error()), "")
		} else {
			recID := msg.detail.RunID
			if recID == "" && msg.detail.Record != nil {
				recID, _ = msg.detail.Record["run_id"].(string)
			}
			m.lastRunID = recID
			if msg.detail.Backend != "" {
				m.lastResolvedBackend = msg.detail.Backend
			}
			summary := msg.detail.Summary
			cancelled := msg.detail.Cancelled || strings.TrimSpace(strings.ToLower(summary)) == "cancelled"
			failed := strings.EqualFold(msg.detail.Status, "failed")
			idx := m.lastStreamingAgentIdx()
			if cancelled {
				if idx >= 0 {
					m.history = append(m.history[:idx], m.history[idx+1:]...)
				}
				m.push(roleSystem, "Run cancelled.", "")
			} else if failed {
				if idx >= 0 {
					m.history = append(m.history[:idx], m.history[idx+1:]...)
				}
				m.push(roleError, summary+"\n"+failureGuidance(msg.detail.Diagnostics), msg.detail.Patch)
			} else if idx >= 0 {
				m.history[idx].text = summary
				m.history[idx].diff = msg.detail.Patch
				m.history[idx].streaming = false
			} else {
				m.push(roleAgent, summary, msg.detail.Patch)
			}
		}
		m.rerender()
	case applyDryDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "apply dry-run failed: "+enhanceError(msg.err.Error()), "")
			m.pendingApply = false
			m.pendingApplyRunID = ""
		} else if !msg.result.OK {
			m.push(roleError, "apply dry-run failed:\n"+msg.result.Stderr, "")
			m.pendingApply = false
			m.pendingApplyRunID = ""
		} else {
			files := msg.result.Files
			m.pendingApply = true
			m.pendingApplyRunID = msg.result.RunID
			if m.pendingApplyRunID == "" {
				m.pendingApplyRunID = m.lastRunID
			}
			m.push(roleSystem,
				fmt.Sprintf("About to apply %d file(s): %s. Confirm? [y/n]",
					len(files), strings.Join(files, ", ")), "")
		}
		m.rerender()
	case applyDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "apply failed: "+enhanceError(msg.err.Error()), "")
		} else if !msg.result.OK {
			m.push(roleError, "apply failed:\n"+msg.result.Stderr, "")
		} else {
			m.push(roleSystem, fmt.Sprintf("Applied %d file(s): %s", len(msg.result.Files), strings.Join(msg.result.Files, ", ")), "")
		}
		m.rerender()
	case verifyDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "verify failed: "+enhanceError(msg.err.Error()), "")
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
			m.push(roleError, "init failed: "+enhanceError(msg.err.Error()), "")
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
			m.push(roleError, "shell failed: "+enhanceError(msg.err.Error()), "")
		} else {
			m.push(roleSystem, renderShellResult(msg.result), "")
		}
		m.rerender()
	case runsDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "runs failed: "+enhanceError(msg.err.Error()), "")
		} else {
			m.push(roleSystem, renderRuns(msg.runs), "")
		}
		m.rerender()
	case smokeDoneMsg:
		m.busy = false
		if msg.err != nil {
			m.push(roleError, "smoke failed: "+enhanceError(msg.err.Error()), "")
		} else {
			m.push(roleSystem, renderSmokeResults(msg.results), "")
		}
		m.rerender()
	case interruptDoneMsg:
		if msg.err != nil {
			m.push(roleError, "cancel failed: "+enhanceError(msg.err.Error()), "")
		} else {
			m.push(roleSystem, "Cancel signal sent.", "")
		}
		m.rerender()
	case spinner.TickMsg:
		var cmd tea.Cmd
		m.spinner, cmd = m.spinner.Update(msg)
		cmds = append(cmds, cmd)
	case tea.KeyMsg:
		// forwardKey: when false, we skip handing the key to the textarea
		// (e.g. we consumed Enter/Tab/↑/↓ ourselves).
		forwardKey := true
		k := msg.String()
		// While the y/n diff-confirm is pending, swallow other input.
		if m.pendingApply {
			switch k {
			case "y", "Y":
				runID := m.pendingApplyRunID
				m.pendingApply = false
				m.pendingApplyRunID = ""
				m.busy = true
				m.busyStart = time.Now()
				m.busyLabel = "applying"
				m.push(roleSystem, "Applying patch from "+runID+"…", "")
				m.rerender()
				cmds = append(cmds, m.apply(runID))
				return m, tea.Batch(cmds...)
			case "n", "N", "esc":
				m.pendingApply = false
				m.pendingApplyRunID = ""
				m.push(roleSystem, "Apply cancelled.", "")
				m.rerender()
				return m, tea.Batch(cmds...)
			case "ctrl+c", "ctrl+d":
				return m, tea.Quit
			default:
				return m, tea.Batch(cmds...)
			}
		}
		switch k {
		case "ctrl+c":
			if m.busy {
				_ = m.client.Interrupt()
				m.push(roleSystem, "Cancelling…", "")
				m.rerender()
				forwardKey = false
				break
			}
			return m, tea.Quit
		case "ctrl+d":
			return m, tea.Quit
		case "esc":
			if m.busy {
				// Per server contract: SIGINT the server; it returns the
				// in-flight call with summary == "cancelled", which we surface
				// as a system message in the runDoneMsg branch. We do NOT
				// flip busy locally so the footer reflects true server state.
				_ = m.client.Interrupt()
				m.push(roleSystem, "Cancelling…", "")
				m.rerender()
				forwardKey = false
			}
		case "f2":
			if m.busy {
				break
			}
			m.cycleBackend()
			m.rerender()
		case "f5":
			if m.busy {
				break
			}
			m.busy = true
			m.busyStart = time.Now()
			m.busyLabel = "verifying"
			m.push(roleSystem, "Running verification…", "")
			m.rerender()
			cmds = append(cmds, m.verify())
		case "f6":
			if m.busy {
				break
			}
			m.busy = true
			m.busyStart = time.Now()
			m.busyLabel = "loading runs"
			m.rerender()
			cmds = append(cmds, m.listRuns())
		case "f7":
			if m.busy {
				break
			}
			m.busy = true
			m.busyStart = time.Now()
			m.busyLabel = "smoke testing"
			m.push(roleSystem, "Running smoke test for "+m.backendForCall()+"…", "")
			m.rerender()
			cmds = append(cmds, m.smoke(m.backendForCall()))
		case "ctrl+b":
			if m.busy {
				break
			}
			m.cycleBackend()
			m.rerender()
		case "ctrl+v":
			if m.busy {
				break
			}
			m.busy = true
			m.busyStart = time.Now()
			m.busyLabel = "verifying"
			m.push(roleSystem, "Running verification…", "")
			m.rerender()
			cmds = append(cmds, m.verify())
		case "ctrl+a":
			if m.busy {
				break
			}
			if cmd := m.startApply(); cmd != nil {
				cmds = append(cmds, cmd)
			}
			forwardKey = false
		case "ctrl+r":
			// Per spec: ctrl+r resets the session. The run-list moves to F6/`/runs`.
			if m.busy {
				break
			}
			m.doReset()
			forwardKey = false
		case "ctrl+l":
			// Clear viewport history only; server-side session is preserved.
			m.history = nil
			m.rerender()
			forwardKey = false
		case "ctrl+_", "ctrl+/":
			// Most terminals deliver ctrl+/ as ctrl+_; accept both.
			m.showHelp()
			forwardKey = false
		case "ctrl+s":
			if m.busy {
				break
			}
			m.busy = true
			m.busyStart = time.Now()
			m.busyLabel = "smoke testing"
			m.push(roleSystem, "Running smoke test for "+m.backendForCall()+"…", "")
			m.rerender()
			cmds = append(cmds, m.smoke(m.backendForCall()))
		case "enter":
			if m.busy {
				forwardKey = false
				break
			}
			text := strings.TrimSpace(m.input.Value())
			if text == "" {
				forwardKey = false
				break
			}
			m.input.Reset()
			m.input.SetHeight(1)
			m.rememberPrompt(text)
			forwardKey = false
			if cmd := m.handleInput(text); cmd != nil {
				cmds = append(cmds, cmd)
			}
		case "up":
			// History recall: only when the cursor is on the first line so
			// users can still navigate within a multi-line draft normally.
			if !m.busy && m.input.Line() == 0 && len(m.prompts) > 0 {
				m.historyPrev()
				forwardKey = false
			}
		case "down":
			// Symmetric: only consume on the last line, otherwise let
			// textarea move the cursor down within multi-line input.
			if !m.busy && m.input.Line() == m.lastInputLine() && m.promptIdx != -1 {
				m.historyNext()
				forwardKey = false
			}
		case "tab":
			if !m.busy && m.tryCompleteSlash() {
				forwardKey = false
			}
		}

		if forwardKey {
			var icmd tea.Cmd
			m.input, icmd = m.input.Update(msg)
			cmds = append(cmds, icmd)
			// Grow textarea height to fit content, capped at 6.
			m.resizeInput()
		}
		var vcmd tea.Cmd
		m.viewport, vcmd = m.viewport.Update(msg)
		cmds = append(cmds, vcmd)
		return m, tea.Batch(cmds...)
	}

	// Non-key messages: forward to both sub-models as before.
	var icmd tea.Cmd
	m.input, icmd = m.input.Update(msg)
	cmds = append(cmds, icmd)
	var vcmd tea.Cmd
	m.viewport, vcmd = m.viewport.Update(msg)
	cmds = append(cmds, vcmd)
	return m, tea.Batch(cmds...)
}

// rememberPrompt appends a submitted prompt to the bounded history stack
// and resets recall state.
func (m *Model) rememberPrompt(text string) {
	m.prompts = append(m.prompts, text)
	if len(m.prompts) > maxPromptHistory {
		m.prompts = m.prompts[len(m.prompts)-maxPromptHistory:]
	}
	m.promptIdx = -1
	m.promptDraft = ""
}

// historyPrev walks one step back into recall history (older entries).
// promptIdx == -1 means "no recall active"; on the first ↑ we stash the
// in-progress draft so we can restore it when the user walks back past
// the newest entry.
func (m *Model) historyPrev() {
	if len(m.prompts) == 0 {
		return
	}
	if m.promptIdx == -1 {
		m.promptDraft = m.input.Value()
		m.promptIdx = len(m.prompts) - 1
	} else if m.promptIdx > 0 {
		m.promptIdx--
	} else {
		return
	}
	m.input.SetValue(m.prompts[m.promptIdx])
	m.input.CursorEnd()
	m.resizeInput()
}

// historyNext walks one step forward (newer entries); past the newest we
// restore the saved draft and exit recall mode.
func (m *Model) historyNext() {
	if m.promptIdx == -1 {
		return
	}
	if m.promptIdx < len(m.prompts)-1 {
		m.promptIdx++
		m.input.SetValue(m.prompts[m.promptIdx])
		m.input.CursorEnd()
	} else {
		m.promptIdx = -1
		m.input.SetValue(m.promptDraft)
		m.promptDraft = ""
		m.input.CursorEnd()
	}
	m.resizeInput()
}

// lastInputLine returns the index of the last line in the textarea so the
// "down arrow on last line" check works regardless of input height.
func (m *Model) lastInputLine() int {
	return strings.Count(m.input.Value(), "\n")
}

// resizeInput grows/shrinks the textarea height to fit the current value,
// clamped to [1, 6].
func (m *Model) resizeInput() {
	n := strings.Count(m.input.Value(), "\n") + 1
	if n < 1 {
		n = 1
	}
	if n > 6 {
		n = 6
	}
	m.input.SetHeight(n)
}

// tryCompleteSlash implements Tab completion for slash commands. Triggers
// only on a single-token input that starts with `/`. Returns true if Tab
// was consumed (regardless of whether the value changed).
func (m *Model) tryCompleteSlash() bool {
	value := m.input.Value()
	if !strings.HasPrefix(value, "/") {
		return false
	}
	if strings.ContainsAny(value, " \n") {
		return false
	}
	var matches []string
	for _, c := range slashCommands {
		if strings.HasPrefix(c, value) {
			matches = append(matches, c)
		}
	}
	switch len(matches) {
	case 0:
		// Consume Tab silently so we don't insert a literal tab into the input.
		return true
	case 1:
		m.input.SetValue(matches[0] + " ")
		m.input.CursorEnd()
	default:
		lcp := longestCommonPrefix(matches)
		if len(lcp) > len(value) {
			m.input.SetValue(lcp)
			m.input.CursorEnd()
		}
	}
	return true
}

// longestCommonPrefix returns the longest string that is a prefix of every
// input. Empty slice → "".
func longestCommonPrefix(ss []string) string {
	if len(ss) == 0 {
		return ""
	}
	prefix := ss[0]
	for _, s := range ss[1:] {
		// Trim prefix down to whatever is shared with s.
		max := len(prefix)
		if len(s) < max {
			max = len(s)
		}
		i := 0
		for i < max && prefix[i] == s[i] {
			i++
		}
		prefix = prefix[:i]
		if prefix == "" {
			break
		}
	}
	return prefix
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

// startApply kicks off the /apply flow: dry-run the apply RPC, then ask for
// y/n confirmation before doing the real write. Used by both `/apply` and Ctrl+A.
func (m *Model) startApply() tea.Cmd {
	if m.lastRunID == "" {
		m.push(roleError, "No run to apply yet.", "")
		m.rerender()
		return nil
	}
	m.busy = true
	m.busyStart = time.Now()
	m.busyLabel = "previewing patch"
	m.push(roleSystem, "Previewing patch from "+m.lastRunID+"…", "")
	m.rerender()
	return m.applyDry(m.lastRunID)
}

// doReset clears the server session and local viewport history.
// Used by /reset and Ctrl+R so the behaviour stays in one place.
func (m *Model) doReset() {
	if err := m.client.ResetSession(); err != nil {
		m.push(roleError, "reset failed: "+err.Error(), "")
	} else {
		m.history = nil
		m.lastRunID = ""
		m.push(roleSystem, "Conversation history cleared.", "")
	}
	m.rerender()
}

// showHelp renders the /help system message. Used by /help and Ctrl+/ so the
// help text lives in one place.
func (m *Model) showHelp() {
	m.push(roleSystem,
		"Commands:\n"+
			"  /init [force]  scaffold gemcoder in this repo\n"+
			"  /apply         preview & apply the most recent run's patch\n"+
			"  /verify        run configured verification commands\n"+
			"  /runs          show recent runs with status/backend\n"+
			"  /smoke [backend]  smoke test local, remote, auto, or both\n"+
			"  /reset         clear conversation history (start a fresh session)\n"+
			"  /shell <cmd>   run a local inspection command (equivalent to !<cmd>)\n"+
			"  /backend [local|remote|auto|both]  show or set backend for new runs\n"+
			"  /quit          exit\n"+
			"\n"+
			"Shortcuts:\n"+
			"  Enter submit · Shift+Enter newline\n"+
			"  Esc cancel run · Ctrl+A apply (preview) · Ctrl+R reset\n"+
			"  Ctrl+L clear viewport (server session kept) · Ctrl+/ help\n"+
			"  F2 backend · F5 verify · F6 runs · F7 smoke\n"+
			"\n"+
			"Anything you type goes to Gemini as a coding task with the last 10 turns of context. Prefix with ! to run a local shell command instead (e.g. ! ls, ! git status).",
		"")
	m.rerender()
}

func (m *Model) handleCommand(text string) tea.Cmd {
	parts := strings.Fields(text)
	cmd := parts[0]
	switch cmd {
	case "/quit", "/exit", "/q":
		return tea.Quit
	case "/help", "/?":
		m.showHelp()
		return nil
	case "/backend":
		if len(parts) < 2 {
			label := m.currentBackend
			if label == "" {
				label = "auto (server default)"
			}
			m.push(roleSystem, "Current backend: "+label, "")
			m.rerender()
			return nil
		}
		switch parts[1] {
		case "local", "remote", "both":
			m.currentBackend = parts[1]
		case "auto":
			m.currentBackend = ""
		default:
			m.push(roleError, "Usage: /backend [local|remote|auto|both]", "")
			m.rerender()
			return nil
		}
		label := m.currentBackend
		if label == "" {
			label = "auto (server default)"
		}
		m.push(roleSystem, "Backend set to: "+label, "")
		m.rerender()
		return nil
	case "/reset":
		m.doReset()
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
	case "/runs":
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "loading runs"
		m.rerender()
		return m.listRuns()
	case "/smoke":
		backend := m.backendForCall()
		if len(parts) >= 2 {
			switch parts[1] {
			case "local", "remote", "auto", "both":
				backend = parts[1]
			default:
				m.push(roleError, "Usage: /smoke [local|remote|auto|both]", "")
				m.rerender()
				return nil
			}
		}
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "smoke testing"
		m.push(roleSystem, "Running smoke test for "+backend+"…", "")
		m.rerender()
		return m.smoke(backend)
	case "/init":
		m.busy = true
		m.busyStart = time.Now()
		m.busyLabel = "initializing"
		m.push(roleSystem, "Initializing…", "")
		m.rerender()
		return m.initRepo()
	case "/apply":
		return m.startApply()
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
	// Input box: textarea height + 2 border rows. While busy we show the
	// spinner line in place of the input so still reserve the same vertical
	// space to avoid jitter on transition.
	inputH := m.input.Height() + 2
	statusH := 1
	hintH := 1
	footerH := 1
	bodyH := m.height - headerH - inputH - statusH - hintH - footerH - 1
	if bodyH < 4 {
		bodyH = 4
	}
	m.viewport.Width = m.width
	m.viewport.Height = bodyH
	// Subtract 4 for the rounded border (2) + horizontal padding (2) so the
	// textarea content area lines up inside InputBox.
	taWidth := m.width - 4
	if taWidth < 10 {
		taWidth = 10
	}
	m.input.SetWidth(taWidth)
}

func (m *Model) rerender() {
	// Preserve scroll position: if the user has scrolled up to read backlog
	// we don't yank them back down when new chunks arrive.
	wasAtBottom := m.viewport.AtBottom()
	var b strings.Builder
	for _, msg := range m.history {
		b.WriteString(m.renderMessage(msg, m.width))
		b.WriteString("\n")
	}
	m.viewport.SetContent(b.String())
	if wasAtBottom {
		m.viewport.GotoBottom()
	}
}

func (m Model) View() string {
	if m.width == 0 {
		return "loading…"
	}
	header := styles.Header.Render(m.headerText())
	body := m.viewport.View()
	// Dim the input border while a run is in flight so the spinner line
	// above it reads as the focal point.
	boxStyle := styles.InputBox
	if m.busy {
		boxStyle = styles.InputBoxBusy
	}
	prompt := boxStyle.Render(m.input.View())
	if m.busy {
		elapsed := int(time.Since(m.busyStart).Seconds())
		label := m.busyLabel
		if label == "" {
			label = "working"
		}
		spinnerLine := fmt.Sprintf("%s %s… %ds  (Esc to cancel · Ctrl+C to quit)", m.spinner.View(), label, elapsed)
		prompt = spinnerLine + "\n" + prompt
	}
	status := styles.Status.Render(m.statusText())
	hint := styles.Hint.Render("Enter submit · Shift+Enter newline · Esc cancel · Ctrl+A apply · Ctrl+R reset · Ctrl+L clear · Ctrl+/ help")
	footer := styles.Hint.Render(m.footerText())
	return strings.Join([]string{header, body, prompt, status, hint, footer}, "\n")
}

// footerText is the live state line below the hint: "Run abc · backend: X · elapsed: Ns".
// When idle, shows the last run id or "idle".
func (m Model) footerText() string {
	backend := m.resolvedBackendLabel()
	if m.busy {
		runID := m.lastRunID
		if runID == "" {
			runID = "—"
		}
		elapsed := int(time.Since(m.busyStart).Seconds())
		return fmt.Sprintf("Run %s · backend: %s · elapsed: %ds", short(runID), backend, elapsed)
	}
	state := "idle"
	if m.lastRunID != "" {
		state = "last: " + short(m.lastRunID)
	}
	return fmt.Sprintf("%s · backend: %s", state, backend)
}

// short returns the first 8 chars of a run id so the footer stays compact.
func short(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8]
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

func (m Model) statusText() string {
	state := "idle"
	if m.busy {
		state = m.busyLabel
		if state == "" {
			state = "working"
		}
	}
	run := "none"
	if m.lastRunID != "" {
		run = m.lastRunID
	}
	return fmt.Sprintf(
		"backend:%s · run:%s · state:%s · patch:%s",
		m.resolvedBackendLabel(),
		run,
		state,
		m.patchState(),
	)
}

func (m Model) resolvedBackendLabel() string {
	if m.lastResolvedBackend != "" {
		return m.lastResolvedBackend
	}
	return m.backendLabel()
}

func (m Model) backendLabel() string {
	if m.currentBackend == "" {
		return "auto"
	}
	return m.currentBackend
}

func (m Model) backendForCall() string {
	if m.currentBackend == "" {
		return "auto"
	}
	return m.currentBackend
}

func (m Model) patchState() string {
	for i := len(m.history) - 1; i >= 0; i-- {
		if strings.TrimSpace(m.history[i].diff) != "" {
			return "yes"
		}
	}
	return "no"
}

func (m *Model) cycleBackend() {
	switch m.currentBackend {
	case "":
		m.currentBackend = "local"
	case "local":
		m.currentBackend = "remote"
	case "remote":
		m.currentBackend = "both"
	default:
		m.currentBackend = ""
	}
	m.push(roleSystem, "Backend set to: "+m.backendLabel(), "")
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
		b.WriteString(" ")
		tag := "[" + msg.Backend + "]"
		switch msg.Backend {
		case "local", "antigravity_local":
			b.WriteString(styles.LocalTag.Render(tag))
		case "remote", "managed_agent":
			b.WriteString(styles.RemoteTag.Render(tag))
		default:
			b.WriteString(tag)
		}
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

func renderRuns(runs []rpc.RunSummary) string {
	if len(runs) == 0 {
		return "No runs yet."
	}
	limit := len(runs)
	if limit > 10 {
		limit = 10
	}
	var b strings.Builder
	b.WriteString("Recent runs:\n")
	for i := 0; i < limit; i++ {
		r := runs[i]
		patch := "no patch"
		if r.PatchPresent {
			patch = "patch"
		}
		backend := r.Backend
		if backend == "" {
			backend = "?"
		}
		task := strings.TrimSpace(r.Task)
		if task == "" {
			task = "(no task preview)"
		}
		fmt.Fprintf(&b, "  %s · %s · %s · %s\n    %s\n", r.RunID, r.Status, backend, patch, task)
	}
	return strings.TrimRight(b.String(), "\n")
}

func renderSmokeResults(results []rpc.SmokeResult) string {
	if len(results) == 0 {
		return "Smoke returned no results."
	}
	var b strings.Builder
	b.WriteString("Smoke results:\n")
	for _, r := range results {
		elapsed := ""
		if r.ElapsedSeconds > 0 {
			elapsed = fmt.Sprintf(" · %.3fs", r.ElapsedSeconds)
		}
		body := strings.TrimSpace(r.Preview)
		if body == "" {
			body = strings.TrimSpace(r.Error)
		}
		if body == "" {
			body = "(no preview)"
		}
		fmt.Fprintf(&b, "  %s · %s%s\n    %s\n", r.Backend, r.Status, elapsed, body)
	}
	return strings.TrimRight(b.String(), "\n")
}

func failureGuidance(diagnostics map[string]any) string {
	if diagnostics == nil {
		return "Next steps: inspect run-summary.json and run /smoke."
	}
	errorType, _ := diagnostics["error_type"].(string)
	switch {
	case errorType == "timeout":
		return "Next steps: retry, increase timeout, or use a smaller task."
	case diagnostics["http_status"] == float64(401) || diagnostics["http_status"] == float64(403):
		return "Next steps: check GEMINI_API_KEY in .env or run /smoke remote."
	case diagnostics["http_status"] == float64(404):
		return "Next steps: check managed_agent.base_agent and api_base in gemcoder.yaml."
	case errorType == "network":
		return "Next steps: check network access and managed_agent.api_base."
	default:
		return "Next steps: inspect managed-result.json and run /smoke."
	}
}

func enhanceError(text string) string {
	lowered := strings.ToLower(text)
	switch {
	case strings.Contains(lowered, "401") || strings.Contains(lowered, "403") ||
		strings.Contains(lowered, "api key"):
		return text + "\nFix: check GEMINI_API_KEY in .env or run /smoke remote."
	case strings.Contains(lowered, "timeout"):
		return text + "\nFix: retry, reduce task/context size, or increase timeout."
	case strings.Contains(lowered, "google-antigravity") || strings.Contains(lowered, "sdk"):
		return text + "\nFix: run `uv sync --extra dev --extra local` for local backend."
	case strings.Contains(lowered, "no patch"):
		return text + "\nFix: run a task that requests code changes, or inspect /runs."
	default:
		return text
	}
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
