// Package rpc speaks JSON-RPC 2.0 to the `gemcoder serve` subprocess over stdio.
package rpc

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os/exec"
	"sync"
	"sync/atomic"
)

type request struct {
	JSONRPC string `json:"jsonrpc"`
	ID      int64  `json:"id"`
	Method  string `json:"method"`
	Params  any    `json:"params"`
}

type Error struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

func (e *Error) Error() string { return fmt.Sprintf("rpc %d: %s", e.Code, e.Message) }

type response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      int64           `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
	Error   *Error          `json:"error,omitempty"`
}

type Client struct {
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	stdout   *bufio.Scanner
	stderr   io.ReadCloser
	mu       sync.Mutex // serializes one in-flight call
	nextID   atomic.Int64
	onNotify NotificationHandler
}

// Start spawns the server (e.g. exec.Command("uv","run","gemcoder","serve") or just "gemcoder","serve").
func Start(cmd *exec.Cmd) (*Client, error) {
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	scanner := bufio.NewScanner(stdout)
	scanner.Buffer(make([]byte, 1024*1024), 16*1024*1024)
	return &Client{cmd: cmd, stdin: stdin, stdout: scanner, stderr: stderr}, nil
}

func (c *Client) Close() error {
	_ = c.stdin.Close()
	return c.cmd.Wait()
}

// NotificationHandler is invoked for server-pushed notifications encountered
// during a Call (JSON-RPC messages with no "id"). Set via SetNotificationHandler.
type NotificationHandler func(method string, params json.RawMessage)

// SetNotificationHandler installs a handler invoked for every server notification.
func (c *Client) SetNotificationHandler(h NotificationHandler) {
	c.mu.Lock()
	c.onNotify = h
	c.mu.Unlock()
}

// Call sends one request and reads stdout until it sees the matching response.
// Any notifications received in the meantime are dispatched via the handler.
// Not safe for concurrent calls.
func (c *Client) Call(method string, params any, out any) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if params == nil {
		params = struct{}{}
	}
	req := request{JSONRPC: "2.0", ID: c.nextID.Add(1), Method: method, Params: params}
	buf, err := json.Marshal(req)
	if err != nil {
		return err
	}
	if _, err := c.stdin.Write(append(buf, '\n')); err != nil {
		return fmt.Errorf("write: %w", err)
	}
	for {
		if !c.stdout.Scan() {
			if err := c.stdout.Err(); err != nil {
				return fmt.Errorf("read: %w", err)
			}
			return fmt.Errorf("read: EOF")
		}
		raw := append([]byte(nil), c.stdout.Bytes()...)
		var head struct {
			ID     *int64          `json:"id"`
			Method string          `json:"method"`
			Params json.RawMessage `json:"params"`
		}
		if err := json.Unmarshal(raw, &head); err != nil {
			return fmt.Errorf("decode: %w", err)
		}
		if head.ID == nil && head.Method != "" {
			if c.onNotify != nil {
				c.onNotify(head.Method, head.Params)
			}
			continue
		}
		var resp response
		if err := json.Unmarshal(raw, &resp); err != nil {
			return fmt.Errorf("decode: %w", err)
		}
		if resp.Error != nil {
			return resp.Error
		}
		if out == nil {
			return nil
		}
		return json.Unmarshal(resp.Result, out)
	}
}

// Stderr returns the server's stderr stream so the caller can tee it to a log.
func (c *Client) Stderr() io.Reader { return c.stderr }

// ---- typed wrappers ----

type Event struct {
	Type      string         `json:"type"`
	Data      map[string]any `json:"data"`
	Timestamp string         `json:"timestamp"`
}

type RunDetail struct {
	Record  map[string]any `json:"record"`
	RunID   string         `json:"run_id"`
	Summary string         `json:"summary"`
	Patch   string         `json:"patch"`
	Backend string         `json:"backend"`
}

type ApplyResult struct {
	OK     bool     `json:"ok"`
	Files  []string `json:"files"`
	Stderr string   `json:"stderr"`
	DryRun bool     `json:"dry_run"`
	RunID  string   `json:"run_id"`
}

type Info struct {
	Model          string `json:"model"`
	Root           string `json:"root"`
	Project        string `json:"project"`
	Initialized    bool   `json:"initialized"`
	ApprovalsApply bool   `json:"approvals_apply"`
}

type InitResult struct {
	Written []string `json:"written"`
}

type VerifyResult struct {
	Command    string `json:"command"`
	ReturnCode int    `json:"returncode"`
	Stdout     string `json:"stdout"`
	Stderr     string `json:"stderr"`
}

type ShellResult struct {
	Command    string `json:"command"`
	ReturnCode int    `json:"returncode"`
	Stdout     string `json:"stdout"`
	Stderr     string `json:"stderr"`
}

func (c *Client) Info() (*Info, error) {
	var out Info
	return &out, c.Call("info", nil, &out)
}

func (c *Client) Init(force bool) (*InitResult, error) {
	var out InitResult
	return &out, c.Call("init", map[string]any{"force": force}, &out)
}

func (c *Client) Verify(runID string) ([]VerifyResult, error) {
	var out []VerifyResult
	params := map[string]any{}
	if runID != "" {
		params["run_id"] = runID
	}
	return out, c.Call("verify", params, &out)
}

func (c *Client) ResetSession() error {
	return c.Call("reset_session", nil, nil)
}

func (c *Client) ListRuns() ([]string, error) {
	var out []string
	return out, c.Call("list_runs", nil, &out)
}

func (c *Client) GetEvents(runID string) ([]Event, error) {
	var out []Event
	return out, c.Call("get_events", map[string]string{"run_id": runID}, &out)
}

func (c *Client) GetRun(runID string) (*RunDetail, error) {
	var out RunDetail
	return &out, c.Call("get_run", map[string]string{"run_id": runID}, &out)
}

func (c *Client) StartRun(task, backend string) (*RunDetail, error) {
	var out RunDetail
	params := map[string]string{"task": task}
	if backend != "" {
		params["backend"] = backend
	}
	return &out, c.Call("start_run", params, &out)
}

func (c *Client) Apply(runID string, dryRun bool) (*ApplyResult, error) {
	var out ApplyResult
	params := map[string]any{"dry_run": dryRun}
	if runID != "" {
		params["run_id"] = runID
	}
	return &out, c.Call("apply", params, &out)
}

func (c *Client) Shell(command string) (*ShellResult, error) {
	var out ShellResult
	return &out, c.Call("shell", map[string]string{"command": command}, &out)
}
