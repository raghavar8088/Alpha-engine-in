package broker

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// AngelOneBroker calls the Angel One SmartAPI REST endpoints.
// Auth: TOTP session (JWT access token) obtained externally (e.g. from the
// Python angel_one_config.py flow); pass the live JWT and client ID here.
//
// REGULATORY: Angel One SmartAPI enforces rate limits (1 req/sec per client
// for order APIs). Do not burst — the retry in PlaceOrder respects 1-second
// back-off. Position-limits and margin checks are enforced server-side.
type AngelOneBroker struct {
	clientID    string
	jwtToken    string // "Bearer <jwt>" header value
	baseURL     string
	httpClient  *http.Client
}

const angelOneBaseURL = "https://apiconnect.angelone.in"

func NewAngelOneBroker(clientID, jwtToken string) *AngelOneBroker {
	return &AngelOneBroker{
		clientID:   clientID,
		jwtToken:   jwtToken,
		baseURL:    angelOneBaseURL,
		httpClient: &http.Client{Timeout: 10 * time.Second},
	}
}

func (b *AngelOneBroker) Name() string { return "angelone" }

// PlaceOrder maps OrderRequest → Angel One POST /rest/secure/angelbroking/order/v1/placeOrder.
func (b *AngelOneBroker) PlaceOrder(ctx context.Context, req OrderRequest) (Fill, error) {
	orderType := "MARKET"
	if req.OrderType == Limit {
		orderType = "LIMIT"
	} else if req.OrderType == SLM {
		orderType = "STOPLOSS_MARKET"
	}

	productType := "CARRYFORWARD"
	if req.ProductType == MIS {
		productType = "INTRADAY"
	}

	body := map[string]any{
		"variety":         "NORMAL",
		"tradingsymbol":   req.Symbol,
		"symboltoken":     "", // caller should resolve token via symbol lookup
		"transactiontype": req.Side,
		"exchange":        req.Exchange,
		"ordertype":       orderType,
		"producttype":     productType,
		"duration":        req.Validity,
		"price":           fmt.Sprintf("%.2f", req.Price),
		"squareoff":       "0",
		"stoploss":        "0",
		"quantity":        fmt.Sprintf("%d", req.Quantity),
	}

	resp, err := b.post(ctx, "/rest/secure/angelbroking/order/v1/placeOrder", body)
	if err != nil {
		return Fill{}, fmt.Errorf("angelone PlaceOrder: %w", err)
	}

	// Angel One wraps responses in {"status":true,"message":"","data":{"orderid":"..."}}
	var result struct {
		Status  bool   `json:"status"`
		Message string `json:"message"`
		Data    struct {
			OrderID string `json:"orderid"`
		} `json:"data"`
	}
	if err := json.Unmarshal(resp, &result); err != nil {
		return Fill{}, fmt.Errorf("angelone PlaceOrder parse: %w (%s)", err, resp)
	}
	if !result.Status {
		return Fill{
			BrokerRef: result.Data.OrderID,
			Status:    "REJECTED",
			RejReason: result.Message,
		}, fmt.Errorf("angelone PlaceOrder rejected: %s", result.Message)
	}

	// Poll order book for fill confirmation (max 10 attempts × 1s).
	for i := 0; i < 10; i++ {
		fill, done, err := b.orderStatus(ctx, result.Data.OrderID, req)
		if err != nil {
			return Fill{}, err
		}
		if done {
			return fill, nil
		}
		select {
		case <-ctx.Done():
			return Fill{BrokerRef: result.Data.OrderID, Status: "PENDING"}, ctx.Err()
		case <-time.After(time.Second):
		}
	}
	return Fill{BrokerRef: result.Data.OrderID, Status: "PENDING"}, nil
}

func (b *AngelOneBroker) orderStatus(ctx context.Context, orderID string, req OrderRequest) (Fill, bool, error) {
	raw, err := b.get(ctx, "/rest/secure/angelbroking/order/v1/orderBook")
	if err != nil {
		return Fill{}, false, err
	}

	var book struct {
		Data []struct {
			Orderid   string  `json:"orderid"`
			Status    string  `json:"status"`
			Filledshares string `json:"filledshares"`
			Averageprice string `json:"averageprice"`
			Rejectionreason string `json:"rejectionreason"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &book); err != nil {
		return Fill{}, false, fmt.Errorf("angelone orderBook parse: %w", err)
	}

	for _, o := range book.Data {
		if o.Orderid != orderID {
			continue
		}
		var qty int64
		var px float64
		fmt.Sscanf(o.Filledshares, "%d", &qty)
		fmt.Sscanf(o.Averageprice, "%f", &px)

		switch o.Status {
		case "complete", "COMPLETE":
			return Fill{
				OrderID: req.SignalID, BrokerRef: orderID,
				Symbol: req.Symbol, Side: req.Side,
				Quantity: req.Quantity, FilledQty: qty,
				AvgFillPx: px, Status: "COMPLETE",
				FilledAt: time.Now(),
			}, true, nil
		case "rejected", "REJECTED":
			return Fill{
				BrokerRef: orderID, Status: "REJECTED",
				RejReason: o.Rejectionreason,
			}, true, fmt.Errorf("angelone order rejected: %s", o.Rejectionreason)
		}
	}
	return Fill{}, false, nil
}

func (b *AngelOneBroker) CancelOrder(ctx context.Context, brokerRef string) error {
	body := map[string]any{
		"variety": "NORMAL",
		"orderid": brokerRef,
	}
	_, err := b.post(ctx, "/rest/secure/angelbroking/order/v1/cancelOrder", body)
	return err
}

func (b *AngelOneBroker) Positions(ctx context.Context) ([]Position, error) {
	raw, err := b.get(ctx, "/rest/secure/angelbroking/order/v1/getPosition")
	if err != nil {
		return nil, err
	}
	var resp struct {
		Data []struct {
			Tradingsymbol string  `json:"tradingsymbol"`
			Netqty        string  `json:"netqty"`
			Averageprice  string  `json:"averageprice"`
			Ltp           string  `json:"ltp"`
			Pnl           string  `json:"pnl"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, fmt.Errorf("angelone Positions parse: %w", err)
	}
	out := make([]Position, 0, len(resp.Data))
	for _, p := range resp.Data {
		var qty int64
		var avgPx, ltp, pnl float64
		fmt.Sscanf(p.Netqty, "%d", &qty)
		fmt.Sscanf(p.Averageprice, "%f", &avgPx)
		fmt.Sscanf(p.Ltp, "%f", &ltp)
		fmt.Sscanf(p.Pnl, "%f", &pnl)
		out = append(out, Position{
			Symbol: p.Tradingsymbol, NetQty: qty,
			AvgCostPx: avgPx, LastPx: ltp, DayPL: pnl,
		})
	}
	return out, nil
}

func (b *AngelOneBroker) Balance(ctx context.Context) (float64, error) {
	raw, err := b.get(ctx, "/rest/secure/angelbroking/user/v1/getRMS")
	if err != nil {
		return 0, err
	}
	var resp struct {
		Data struct {
			Net string `json:"net"`
		} `json:"data"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return 0, fmt.Errorf("angelone Balance parse: %w", err)
	}
	var net float64
	fmt.Sscanf(resp.Data.Net, "%f", &net)
	return net, nil
}

func (b *AngelOneBroker) authHeaders() map[string]string {
	return map[string]string{
		"Authorization":  "Bearer " + b.jwtToken,
		"Content-Type":   "application/json",
		"Accept":         "application/json",
		"X-UserType":     "USER",
		"X-SourceID":     "WEB",
		"X-ClientLocalIP": "127.0.0.1",
		"X-ClientPublicIP": "127.0.0.1",
		"X-MACAddress":   "fe80::1",
		"X-PrivateKey":   b.clientID,
	}
}

func (b *AngelOneBroker) post(ctx context.Context, path string, payload any) ([]byte, error) {
	data, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, b.baseURL+path, bytes.NewReader(data))
	if err != nil {
		return nil, err
	}
	for k, v := range b.authHeaders() {
		req.Header.Set(k, v)
	}
	resp, err := b.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("angelone POST %s: %w", path, err)
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func (b *AngelOneBroker) get(ctx context.Context, path string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, b.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range b.authHeaders() {
		req.Header.Set(k, v)
	}
	resp, err := b.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("angelone GET %s: %w", path, err)
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}
