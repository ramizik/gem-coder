// gemcoder-tui is the Bubble Tea front-end for GemCoder.
// It spawns `gemcoder serve` (Python) as a subprocess and talks JSON-RPC over stdio.
package main

import (
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/superagentic-ai/gemcoder/tui/internal/model"
	"github.com/superagentic-ai/gemcoder/tui/internal/rpc"
)

func main() {
	serveCmd := flag.String("serve-cmd", "", "command to launch the server (default: 'uv run gemcoder serve' or 'gemcoder serve' if uv not present)")
	flag.Parse()

	cmd := buildServerCmd(*serveCmd)
	cmd.Env = os.Environ()
	client, err := rpc.Start(cmd)
	if err != nil {
		fatalf("failed to start %s: %v", cmd.String(), err)
	}
	// Drain stderr to a log file so it doesn't fight with the TUI render loop.
	logf, _ := os.OpenFile(".gemcoder/tui.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if logf != nil {
		defer logf.Close()
		go io.Copy(logf, client.Stderr())
	} else {
		go io.Copy(io.Discard, client.Stderr())
	}

	p := tea.NewProgram(model.New(client), tea.WithAltScreen(), tea.WithMouseCellMotion())
	if _, err := p.Run(); err != nil {
		fatalf("tui error: %v", err)
	}
	_ = client.Close()
}

func buildServerCmd(override string) *exec.Cmd {
	if override != "" {
		return exec.Command("sh", "-c", override)
	}
	if _, err := exec.LookPath("uv"); err == nil {
		return exec.Command("uv", "run", "gemcoder", "serve")
	}
	return exec.Command("gemcoder", "serve")
}

func fatalf(f string, args ...any) {
	fmt.Fprintf(os.Stderr, f+"\n", args...)
	os.Exit(1)
}
