// Package alerting implements the Telegram/email alert dispatch the
// BTC engine learned to build from day one after a 42-hour silent
// outage. Wired here as an interface plus a Telegram implementation so
// it ships with the very first deployment, not bolted on after an
// incident.
package alerting

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

type Severity string

const (
	SeverityInfo     Severity = "INFO"
	SeverityWarning  Severity = "WARNING"
	SeverityCritical Severity = "CRITICAL"
)

type Alerter interface {
	Send(ctx context.Context, severity Severity, title, message string) error
}

// TelegramAlerter posts to a Telegram bot chat. Requires TELEGRAM_BOT_TOKEN
// and TELEGRAM_CHAT_ID to be configured; Send is a no-op (returns nil)
// if either is empty, so local/dev runs do not fail on missing config.
type TelegramAlerter struct {
	BotToken string
	ChatID   string
	Client   *http.Client
}

func NewTelegramAlerter(botToken, chatID string) *TelegramAlerter {
	return &TelegramAlerter{BotToken: botToken, ChatID: chatID, Client: &http.Client{Timeout: 10 * time.Second}}
}

func (a *TelegramAlerter) Send(ctx context.Context, severity Severity, title, message string) error {
	if a.BotToken == "" || a.ChatID == "" {
		return nil // alerting not configured, e.g. local dev
	}
	url := fmt.Sprintf("https://api.telegram.org/bot%s/sendMessage", a.BotToken)
	body, _ := json.Marshal(map[string]string{
		"chat_id": a.ChatID,
		"text":    fmt.Sprintf("[%s] %s\n%s", severity, title, message),
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.Client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return nil
}

// NoopAlerter is used when alerting is intentionally disabled (tests, dev).
type NoopAlerter struct{}

func (NoopAlerter) Send(ctx context.Context, severity Severity, title, message string) error {
	return nil
}

// StalenessWatchdog periodically checks feed staleness and fires a
// CRITICAL alert if no tick has been received for >2 minutes during
// market hours. Same pattern as the BTC engine's post-incident fix,
// shipped from day one here instead of after an outage.
type StalenessWatchdog struct {
	Alerter        Alerter
	MaxStaleness   time.Duration
	CheckInterval  time.Duration
}

func NewStalenessWatchdog(a Alerter) *StalenessWatchdog {
	return &StalenessWatchdog{Alerter: a, MaxStaleness: 2 * time.Minute, CheckInterval: 30 * time.Second}
}

// CheckOnce evaluates one feed's staleness and alerts if breached.
// Call this from a ticker loop in main.go, gated by calendar.IsMarketOpen.
func (w *StalenessWatchdog) CheckOnce(ctx context.Context, feedKey string, staleness time.Duration) {
	if staleness > w.MaxStaleness {
		_ = w.Alerter.Send(ctx, SeverityCritical, "Data feed stale",
			fmt.Sprintf("feed=%s staleness=%s exceeds max=%s during market hours", feedKey, staleness, w.MaxStaleness))
	}
}
