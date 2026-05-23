package model

import (
	"strings"
	"testing"

	"github.com/superagentic-ai/gemcoder/tui/internal/rpc"
)

func TestBackendCommandSetsAndClearsBackend(t *testing.T) {
	m := New(nil)
	if cmd := m.handleCommand("/backend local"); cmd != nil {
		t.Fatalf("expected nil cmd, got %v", cmd)
	}
	if m.currentBackend != "local" {
		t.Fatalf("backend = %q, want local", m.currentBackend)
	}
	m.handleCommand("/backend auto")
	if m.currentBackend != "" {
		t.Fatalf("backend = %q, want empty for auto", m.currentBackend)
	}
}

func TestFormatStepEventTagsBackend(t *testing.T) {
	line := formatStepEvent(StreamEventMsg{
		Kind:    "backend.selected",
		Backend: "local",
		Text:    "routing to local SDK",
	})
	if !strings.Contains(line, "backend.selected") {
		t.Fatalf("missing kind: %q", line)
	}
	if !strings.Contains(line, "local") {
		t.Fatalf("missing backend tag: %q", line)
	}
}

func TestRenderRunsSummaries(t *testing.T) {
	out := renderRuns([]rpc.RunSummary{
		{
			RunID:        "run_abc",
			Status:       "completed",
			Backend:      "remote",
			PatchPresent: true,
			Task:         "fix tests",
		},
	})
	if !strings.Contains(out, "run_abc") || !strings.Contains(out, "fix tests") {
		t.Fatalf("unexpected output: %q", out)
	}
}

func TestFailureGuidanceTimeout(t *testing.T) {
	msg := failureGuidance(map[string]any{"error_type": "timeout"})
	if !strings.Contains(msg, "retry") {
		t.Fatalf("expected retry guidance, got %q", msg)
	}
}
