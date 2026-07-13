"""TradingAI options analytics (roadmap Phase 7): Black-Scholes pricing/Greeks/IV,
live Dhan option-chain fetch + OI analytics, multi-leg payoff, and a synthetic-premium
backtester for the options strategies (#46-50) that were underlying-proxies until now."""

from options_service.greeks import black_scholes_greeks, black_scholes_price, implied_volatility

__all__ = ["black_scholes_greeks", "black_scholes_price", "implied_volatility"]
