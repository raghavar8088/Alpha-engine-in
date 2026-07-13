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

// DhanBroker calls the DhanHQ v2 REST API.
// Auth: client_id + access_token (JWT) from dhan_config.py.
// All order endpoints are at https://api.dhan.co/v2/.
//
// REGULATORY: DhanHQ enforces SEBI-mandated position limits server-side.
// The adapter only sends; enforcement is the exchange's responsibility.
type DhanBroker struct {
	clientID    string
	accessToken string // raw JWT, set as "access-token" header
	baseURL     string
	httpClient  *http.Client
}

const dhanBaseURL = "https://api.dhan.co/v2"

func NewDhanBroker(clientID, accessToken string) *DhanBroker {
	return &DhanBroker{
		clientID:    clientID,
		accessToken: accessToken,
		baseURL:     dhanBaseURL,
		httpClient:  &http.Client{Timeout: 10 * time.Second},
	}
}

func (b *DhanBroker) Name() string { return "dhan" }

// PlaceOrder maps OrderRequest → Dhan POST /v2/orders.
// Dhan uses "BUY"/"SELL" transaction types and numeric price.
func (b *DhanBroker) PlaceOrder(ctx context.Context, req OrderRequest) (Fill, error) {
	orderType := "MARKET"
	if req.OrderType == Limit {
		orderType = "LIMIT"
	} else if req.OrderType == SLM {
		orderType = "STOP_LOSS_MARKET"
	}

	productType := "CNC"
	if req.ProductType == MIS {
		productType = "INTRADAY"
	} else if req.ProductType == NRML {
		productType = "MARGIN"
	}

	validity := "DAY"
	if req.Validity == "IOC" {
		validity = "IOC"
	}

	body := map[string]any{
		"dhanClientId":       b.clientID,
		"transactionType":    req.Side,    // "BUY" or "SELL"
		"exchangeSegment":    dhanExchange(req.Exchange),
		"productType":        productType,
		"orderType":          orderType,
		"validity":           validity,
		"tradingSymbol":      req.Symbol,
		"securityId":         "", // caller resolves via Dhan's security master
		"quantity":           req.Quantity,
		"disclosedQuantity":  0,
		"price":              req.Price,
		"triggerPrice":       req.TriggerPx,
		"afterMarketOrder":   false,
		"amoTime":            "OPEN",
	}

	raw, err := b.post(ctx, "/orders", body)
	if err != nil {
		return Fill{}, fmt.Errorf("dhan PlaceOrder: %w", err)
	}

	// Dhan v2 order response: {"orderId":"...","orderStatus":"TRANSIT",...}
	var result struct {
		OrderID     string `json:"orderId"`
		OrderStatus string `json:"orderStatus"`
		Remarks     string `json:"remarks"`
	}
	if err := json.Unmarshal(raw, &result); err != nil {
		return Fill{}, fmt.Errorf("dhan PlaceOrder parse: %w (%s)", err, raw)
	}

	if result.OrderStatus == "REJECTED" {
		return Fill{
			BrokerRef: result.OrderID, Status: "REJECTED", RejReason: result.Remarks,
		}, fmt.Errorf("dhan order rejected: %s", result.Remarks)
	}

	// Poll for terminal status.
	for i := 0; i < 10; i++ {
		fill, done, err := b.orderStatus(ctx, result.OrderID, req)
		if err != nil {
			return Fill{}, err
		}
		if done {
			return fill, nil
		}
		select {
		case <-ctx.Done():
			return Fill{BrokerRef: result.OrderID, Status: "PENDING"}, ctx.Err()
		case <-time.After(time.Second):
		}
	}
	return Fill{BrokerRef: result.OrderID, Status: "PENDING"}, nil
}

func (b *DhanBroker) orderStatus(ctx context.Context, orderID string, req OrderRequest) (Fill, bool, error) {
	raw, err := b.get(ctx, "/orders/"+orderID)
	if err != nil {
		return Fill{}, false, err
	}

	var o struct {
		OrderStatus      string  `json:"orderStatus"`
		TradedQuantity   int64   `json:"tradedQuantity"`
		Price            float64 `json:"price"`
		AveragePrice     float64 `json:"averagePrice"`
		Remarks          string  `json:"remarks"`
	}
	if err := json.Unmarshal(raw, &o); err != nil {
		return Fill{}, false, fmt.Errorf("dhan orderStatus parse: %w", err)
	}

	switch o.OrderStatus {
	case "TRADED":
		return Fill{
			OrderID: req.SignalID, BrokerRef: orderID,
			Symbol: req.Symbol, Side: req.Side,
			Quantity: req.Quantity, FilledQty: o.TradedQuantity,
			AvgFillPx: o.AveragePrice, Status: "COMPLETE",
			FilledAt: time.Now(),
		}, true, nil
	case "REJECTED":
		return Fill{
			BrokerRef: orderID, Status: "REJECTED", RejReason: o.Remarks,
		}, true, fmt.Errorf("dhan order rejected: %s", o.Remarks)
	case "CANCELLED":
		return Fill{
			BrokerRef: orderID, Status: "REJECTED", RejReason: "CANCELLED",
		}, true, fmt.Errorf("dhan order cancelled")
	}
	return Fill{}, false, nil
}

func (b *DhanBroker) CancelOrder(ctx context.Context, brokerRef string) error {
	_, err := b.del(ctx, "/orders/"+brokerRef)
	return err
}

func (b *DhanBroker) Positions(ctx context.Context) ([]Position, error) {
	raw, err := b.get(ctx, "/positions")
	if err != nil {
		return nil, err
	}
	var positions []struct {
		TradingSymbol  string  `json:"tradingSymbol"`
		NetQty         int64   `json:"netQty"`
		CostPrice      float64 `json:"costPrice"`
		LastTradedPrice float64 `json:"lastTradedPrice"`
		UnrealizedProfit float64 `json:"unrealizedProfit"`
		DayBuyQty      int64   `json:"dayBuyQty"`
		DaySellQty     int64   `json:"daySellQty"`
	}
	if err := json.Unmarshal(raw, &positions); err != nil {
		return nil, fmt.Errorf("dhan Positions parse: %w", err)
	}
	out := make([]Position, 0, len(positions))
	for _, p := range positions {
		out = append(out, Position{
			Symbol:       p.TradingSymbol,
			NetQty:       p.NetQty,
			AvgCostPx:    p.CostPrice,
			LastPx:       p.LastTradedPrice,
			UnrealisedPL: p.UnrealizedProfit,
		})
	}
	return out, nil
}

func (b *DhanBroker) Balance(ctx context.Context) (float64, error) {
	raw, err := b.get(ctx, "/fundlimit")
	if err != nil {
		return 0, err
	}
	var funds struct {
		AvailableBalance float64 `json:"availabelBalance"` // sic: Dhan API typo
		SODLimit         float64 `json:"sodLimit"`
		Collateral       float64 `json:"collateralAmount"`
		ReceivableAmount float64 `json:"receiveableAmount"`
	}
	if err := json.Unmarshal(raw, &funds); err != nil {
		return 0, fmt.Errorf("dhan Balance parse: %w", err)
	}
	return funds.AvailableBalance, nil
}

// dhanExchange maps NSE/NFO → Dhan segment codes.
func dhanExchange(nseExchange string) string {
	switch nseExchange {
	case "NFO":
		return "NSE_FNO"
	case "NSE":
		return "NSE_EQ"
	case "BSE":
		return "BSE_EQ"
	default:
		return "NSE_FNO"
	}
}

func (b *DhanBroker) authHeaders() map[string]string {
	return map[string]string{
		"access-token": b.accessToken,
		"client-id":    b.clientID,
		"Content-Type": "application/json",
	}
}

func (b *DhanBroker) post(ctx context.Context, path string, payload any) ([]byte, error) {
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
		return nil, fmt.Errorf("dhan POST %s: %w", path, err)
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func (b *DhanBroker) get(ctx context.Context, path string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, b.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range b.authHeaders() {
		req.Header.Set(k, v)
	}
	resp, err := b.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("dhan GET %s: %w", path, err)
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

func (b *DhanBroker) del(ctx context.Context, path string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, b.baseURL+path, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range b.authHeaders() {
		req.Header.Set(k, v)
	}
	resp, err := b.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("dhan DELETE %s: %w", path, err)
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}
