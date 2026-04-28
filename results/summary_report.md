# NSE Swing Strategy — Backtest Summary Report

Generated on: 2026-04-28 17:22

## Universe
HDFCBANK, INFY, ICICIBANK, SBIN, WIPRO, SUNPHARMA, LT, BHARTIARTL, DIXON, BSE, CANBK, BEL, HAL, TITAN, BAJFINANCE, HCLTECH, TRENT, PERSISTENT, SIEMENS, RELIANCE, NTPC, ONGC, POWERGRID, ITC, NESTLEIND, BRITANNIA, M&M, MARUTI, HEROMOTOCO, TATASTEEL, JINDALSTEL, HINDALCO, COALINDIA, CIPLA, DRREDDY, APOLLOHOSP, ETERNAL, TATAELXSI, KPITTECH, KOTAKBANK, AXISBANK, INDUSINDBK, BAJAJFINSV, CHOLAFIN, MUTHOOTFIN, TCS, TECHM, MPHASIS, LTIM, COFORGE, OFSS, ABB, BHEL, CUMMINSIND, THERMAX, POLYCAB, KEI, PIDILITIND, AARTIIND, NAVINFLUOR, ALKYLAMINE, HAVELLS, VOLTAS, VGUARD, DMART, NYKAA, TORNTPHARM, AUROPHARMA, LALPATHLAB, IPCALAB, BPCL, IOC, GAIL, TATAPOWER, ADANIGREEN, ADANIPORTS, HDFCLIFE, SBILIFE, ICICIGI, ULTRACEMCO, INDUSTOWER, IDEA

## Combined Portfolio (all stocks, default params, 2019–2026)

| Metric            | Value           |
|-------------------|-----------------|
| Total Trades      | 2077 |
| Win Rate          | 42.6% |
| Avg Win           | +9.40% |
| Avg Loss          | -4.19% |
| Win/Loss Ratio    | 2.24 |
| Profit Factor     | 1.66 |
| Expectancy/trade  | +1.59% |
| Sharpe (ann.)     | 3.35 |
| Sortino (ann.)    | 18.34 |
| Max Drawdown      | -34.3% |
| Expectancy t-stat | 10.32 (p=0.0000) |
| *(H0: mean return = 0, one-tailed. p < 0.05 = statistically significant edge)* | |

**Inter-stock avg ρ** : 0.031  | **Adj. Z** : -3.61  | **Adj. p** : 0.0003

## Monte Carlo (10 000 simulations, position-sized returns)
- Starting capital    : ₹100,000
- Median final equity : ₹60,790,384  (+60690.4%)
- 5th pct equity      : ₹21,451,165  (+21351.2%)
- 95th pct max DD     : -10.7%
- % profitable paths  : 100.0%

## Overall Verdict
✅ PROMISING — strategy shows statistically significant positive edge. Recommend paper-trading before going live.

## Key Risks
- NSE-specific risks: circuit breakers, settlement delays, SEBI rule changes.
- Strategy tested on daily bars (not 3H); execution may differ on live 3H data.
- SL/TP fills assumed at exact levels — slippage may be worse in practice.
- Short selling in India requires F&O or margin; many retail accounts cannot short stocks directly.
- Parameter fragility: check sensitivity charts — fragile params need wider search or removal.

## Suggested Improvements
1. Re-run on 3H intraday data once yfinance / other data source provides sufficient history.
2. Add a volatility filter (e.g. skip entries when ATR/close ratio is extreme).
3. Consider position-size scaling by ATR so larger-ATR trades risk the same INR amount.
4. Sector rotation: weight allocation by recent relative strength vs Nifty.
5. Test alternative trend filter: use Supertrend or higher-TF MA in place of EMA200.