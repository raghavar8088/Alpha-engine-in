# broker-service

Standalone process that maintains a persistent Dhan order-update WebSocket
(`wss://api-order-update.dhan.co`) per connected user, publishing fills/status
changes to Redis (`broker_order_updates:{user_id}`) for the backend's
`/ws/broker/orders` endpoint to relay to that user's browser.

REST order placement/cancellation, holdings, positions, and funds all live in
`backend/app/services/dhan_client.py` and `backend/app/api/routes/broker.py`
instead — this service only owns the always-on WebSocket listener, since that's
the piece that needs to run independently of any single HTTP request.

Polls `broker_credentials` in MongoDB every `CREDENTIAL_POLL_SECONDS` (default
30s) to start/stop a listener task per user as they connect/disconnect Dhan.

Run: `pip install -r requirements.txt && cp .env.example .env && python main.py`
(`BROKER_ENCRYPTION_KEY` must match the backend's exactly, or credential
decryption fails.)
