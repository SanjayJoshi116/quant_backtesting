"""
dashboard.py — NSE Swing Trading Dashboard (v2)
Run:  streamlit run dashboard.py
"""

import sys, os, glob, warnings, subprocess
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Swing", page_icon="📊",
    layout="wide", initial_sidebar_state="expanded",
)

# ── Professional CSS ──────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* Metric cards */
  .kpi-card {
    background: linear-gradient(135deg, #1a1d2e 0%, #16192a 100%);
    border: 1px solid #2a2d3e; border-radius: 12px;
    padding: 18px 20px; margin-bottom: 12px;
  }
  .kpi-label { font-size: 12px; color: #6b7280; font-weight: 500;
               text-transform: uppercase; letter-spacing: 0.8px; }
  .kpi-value { font-size: 28px; font-weight: 700; color: #f1f5f9;
               margin: 4px 0 2px; }
  .kpi-delta { font-size: 13px; font-weight: 500; }
  .kpi-pos   { color: #10b981; }
  .kpi-neg   { color: #ef4444; }
  .kpi-neu   { color: #94a3b8; }

  /* Signal card */
  .sig-card {
    background: linear-gradient(135deg, #0f2027 0%, #1a1d2e 100%);
    border: 1px solid #1e3a5f; border-radius: 10px;
    padding: 14px 16px; margin-bottom: 10px;
    border-left: 4px solid #10b981;
  }
  .sig-card.short { border-left-color: #ef4444; }
  .sig-ticker { font-size: 16px; font-weight: 700; color: #f1f5f9; }
  .sig-type { background: #1e3a5f; color: #60a5fa; padding: 2px 10px;
              border-radius: 20px; font-size: 12px; font-weight: 600; }
  .sig-price { font-size: 13px; color: #94a3b8; margin-top: 6px; }
  .sig-score { background: #0d4429; color: #10b981; padding: 2px 8px;
               border-radius: 20px; font-size: 11px; font-weight: 700; }

  /* Pattern card */
  .pat-card {
    background: #1a1d2e; border: 1px solid #2a2d3e;
    border-radius: 10px; padding: 12px 16px; margin-bottom: 8px;
    border-left: 4px solid #f59e0b;
  }
  .pat-high { border-left-color: #10b981; }

  /* Section headers */
  .section-header {
    font-size: 13px; font-weight: 600; color: #6b7280;
    text-transform: uppercase; letter-spacing: 1px;
    margin: 20px 0 12px; padding-bottom: 6px;
    border-bottom: 1px solid #1e2130;
  }

  /* Streamlit overrides */
  .stButton button {
    background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
    color: white !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
    padding: 8px 24px !important;
  }
  .stButton button:hover {
    background: linear-gradient(135deg, #1e40af, #1d4ed8) !important;
  }
  div[data-testid="stMetric"] {
    background: #1a1d2e; border-radius: 10px;
    padding: 14px; border: 1px solid #2a2d3e;
  }
  [data-testid="stMetricValue"] { font-size: 24px !important; font-weight: 700 !important; }
  .stTabs [data-baseweb="tab-list"] { background: #0f111a; }
  .stTabs [data-baseweb="tab"] { color: #6b7280; font-weight: 500; }
  .stTabs [aria-selected="true"] { color: #60a5fa !important; }
  .stDataFrame { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

CHART_BG = "#0f111a"
GRID_CLR = "#1a1d2e"
PLOTLY_BASE = dict(paper_bgcolor=CHART_BG, plot_bgcolor=CHART_BG,
                   font=dict(color="#94a3b8", family="Inter"))


# ── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_tickers():
    from data import TICKERS
    return sorted([t.replace(".NS", "") for t in TICKERS])


@st.cache_data(ttl=900)   # 15-min cache; fetch_or_load handles market-aware refresh
def get_stock_data(ticker_ns: str):
    """
    Fetch fresh data via core.data.fetch_or_load (market-aware TTL).
    Falls back to data/raw/ CSV if screener cache unavailable.
    Caller slices with .tail(N) for display.
    """
    from indicators import prepare_indicators

    # Try fresh data first (updates automatically after 15:30 IST each day)
    try:
        from core.data import fetch_or_load
        df = fetch_or_load(ticker_ns, force=False)
        if df is not None and len(df) >= 50:
            return prepare_indicators(df)
    except Exception:
        pass

    # Fallback: read from data/raw/ (full history, may be a few days stale)
    from data import RAW_DIR, _safe_name
    csv = os.path.join(RAW_DIR, f"{_safe_name(ticker_ns)}.csv")
    if not os.path.exists(csv):
        return None
    df = pd.read_csv(csv, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    if len(df) < 50:
        return None
    return prepare_indicators(df)


@st.cache_data(ttl=30)
def get_all_trades():
    frames = []
    for f in glob.glob("results/trades_*.csv"):
        try:
            d = pd.read_csv(f)
            if not d.empty and "pnl_pct" in d.columns:
                frames.append(d)
        except Exception:
            pass
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    t["entry_date"] = pd.to_datetime(t["entry_date"])
    t["exit_date"]  = pd.to_datetime(t["exit_date"])

    # Fix NaN in pnl_on_equity — old CSVs predate the position-sizing code.
    # Reconstruct from pnl_pct × position_pct where missing.
    # Old trade CSVs (pre position-sizing) have NaN in both pnl_on_equity and
    # position_pct. Fill position_pct with 15 (typical for 1.5% risk / ~5% SL),
    # then reconstruct pnl_on_equity = pnl_pct * position_pct / 100.
    if "position_pct" in t.columns:
        t["position_pct"] = t["position_pct"].fillna(15.0)
    else:
        t["position_pct"] = 15.0

    if "pnl_on_equity" not in t.columns:
        t["pnl_on_equity"] = t["pnl_pct"] * t["position_pct"] / 100
    else:
        t["pnl_on_equity"] = t["pnl_on_equity"].fillna(
            t["pnl_pct"] * t["position_pct"] / 100
        )

    return t.sort_values("exit_date").reset_index(drop=True)


@st.cache_data(ttl=30)
def get_runs():
    p = Path("logs/backtest_runs.csv")
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


# ── Chart builder ─────────────────────────────────────────────────────────────

def make_chart(df: pd.DataFrame, ticker: str,
               trades: pd.DataFrame = None, lookback: int = 250) -> go.Figure:
    """Proper candlestick with EMAs, volume, RSI and trade markers."""
    df = df.tail(lookback).copy()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.62, 0.18, 0.20],
        vertical_spacing=0.015,
        subplot_titles=["", "", ""],
    )

    # ── Candlestick ───────────────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        name="Price",
        increasing=dict(line=dict(color="#10b981", width=1),
                        fillcolor="#10b981"),
        decreasing=dict(line=dict(color="#ef4444", width=1),
                        fillcolor="#ef4444"),
        showlegend=False,
    ), row=1, col=1)

    # ── EMAs ─────────────────────────────────────────────────────────────────
    ema_cfg = [("EMA21","#34d399",2), ("EMA50","#60a5fa",2), ("EMA200","#f87171",1.5)]
    for col, color, width in ema_cfg:
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[col], name=col,
                line=dict(color=color, width=width),
                hovertemplate=f"{col}: ₹%{{y:,.2f}}<extra></extra>",
            ), row=1, col=1)

    # ── Volume bars ───────────────────────────────────────────────────────────
    vol_c = ["#10b981" if c >= o else "#ef4444"
             for c, o in zip(df["Close"], df["Open"])]
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        marker_color=vol_c, marker_opacity=0.6,
        name="Volume", showlegend=False,
    ), row=2, col=1)
    # Volume MA
    vol_ma = df["Volume"].rolling(20).mean()
    fig.add_trace(go.Scatter(
        x=df.index, y=vol_ma,
        line=dict(color="#fbbf24", width=1, dash="dot"),
        name="Vol MA20", showlegend=False,
    ), row=2, col=1)

    # ── RSI ───────────────────────────────────────────────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#a78bfa", width=1.5),
            hovertemplate="RSI: %{y:.1f}<extra></extra>",
            showlegend=False,
        ), row=3, col=1)
        # OB/OS zones
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,68,68,0.12)",
                      line_width=0, row=3, col=1)
        fig.add_hrect(y0=0,  y1=30,  fillcolor="rgba(16,185,129,0.12)",
                      line_width=0, row=3, col=1)
        for lvl, clr in [(70,"#ef4444"),(50,"#4b5563"),(30,"#10b981")]:
            fig.add_hline(y=lvl, line=dict(color=clr, width=0.8, dash="dot"),
                          row=3, col=1)

    # ── Trade markers ─────────────────────────────────────────────────────────
    if trades is not None and not trades.empty:
        t = trades[trades["ticker"] == f"{ticker}.NS"]
        t = t[(t["entry_date"] >= df.index[0]) & (t["entry_date"] <= df.index[-1])]
        if not t.empty:
            # Entries
            long_e  = t[t["direction"] == "long"]
            short_e = t[t["direction"] == "short"]
            for row_df, sym, color, label in [
                (long_e,  "triangle-up",   "#10b981", "Long entry"),
                (short_e, "triangle-down", "#ef4444", "Short entry"),
            ]:
                if not row_df.empty:
                    fig.add_trace(go.Scatter(
                        x=row_df["entry_date"], y=row_df["entry_price"],
                        mode="markers", name=label,
                        marker=dict(size=11, symbol=sym, color=color,
                                    line=dict(color="#ffffff", width=1)),
                        customdata=row_df[["signal_type","pnl_pct"]].values,
                        hovertemplate="<b>%{customdata[0]}</b><br>"
                                      "Entry: ₹%{y:,.2f}<br>"
                                      "P&L: %{customdata[1]:+.1f}%<extra></extra>",
                    ), row=1, col=1)
            # Exits
            for reason, sym, color, label in [
                ("TP",        "star",         "#fbbf24", "TP hit"),
                ("SL",        "x",            "#ef4444", "SL hit"),
                ("MeshBreak", "circle-open",  "#94a3b8", "Exit"),
            ]:
                ex = t[t["exit_reason"] == reason]
                if not ex.empty:
                    fig.add_trace(go.Scatter(
                        x=ex["exit_date"], y=ex["exit_price"],
                        mode="markers", name=label,
                        marker=dict(size=9, symbol=sym, color=color),
                        hovertemplate=f"{reason}: ₹%{{y:,.2f}}<extra></extra>",
                    ), row=1, col=1)

    # ── Layout ────────────────────────────────────────────────────────────────
    fig.update_layout(
        **PLOTLY_BASE,
        height=680,
        title=dict(text=f"<b>{ticker}</b>", font=dict(size=18, color="#f1f5f9"),
                   x=0.01),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
        hovermode="x unified",
    )
    axis_style = dict(gridcolor=GRID_CLR, zerolinecolor=GRID_CLR,
                      linecolor="#2a2d3e", tickfont=dict(size=11))
    for ax in ["xaxis","xaxis2","xaxis3","yaxis","yaxis2","yaxis3"]:
        fig.update_layout(**{ax: axis_style})
    fig.update_yaxes(title_text="₹ Price", row=1, col=1, tickprefix="₹")
    fig.update_yaxes(title_text="Volume",  row=2, col=1)
    fig.update_yaxes(title_text="RSI",     row=3, col=1, range=[0,100])
    fig.update_xaxes(showspikes=True, spikecolor="#4b5563",
                     spikethickness=1, spikedash="dot")
    return fig


def make_equity_curve(trades: pd.DataFrame) -> go.Figure:
    pnl_col = "pnl_on_equity" if "pnl_on_equity" in trades.columns else "pnl_pct"
    t = trades.sort_values("exit_date").reset_index(drop=True)
    equity = [100_000.0]
    for pnl in t[pnl_col]:
        equity.append(equity[-1] * (1 + pnl / 100))
    dates = [t["entry_date"].iloc[0]] + t["exit_date"].tolist()

    # Drawdown series
    eq = np.array(equity)
    peak = np.maximum.accumulate(eq)
    dd   = (eq - peak) / peak * 100

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.70, 0.30], vertical_spacing=0.03)

    # Equity fill
    fig.add_trace(go.Scatter(
        x=dates, y=equity,
        fill="tozeroy", fillcolor="rgba(16,185,129,0.08)",
        line=dict(color="#10b981", width=2),
        name="Equity (₹)", hovertemplate="₹%{y:,.0f}<extra></extra>",
    ), row=1, col=1)

    # Drawdown
    fig.add_trace(go.Scatter(
        x=dates, y=dd,
        fill="tozeroy", fillcolor="rgba(239,68,68,0.15)",
        line=dict(color="#ef4444", width=1),
        name="Drawdown %", hovertemplate="%{y:.1f}%<extra></extra>",
    ), row=2, col=1)

    max_dd = float(dd.min())
    fig.add_hline(y=max_dd, line=dict(color="#ef4444", dash="dot", width=1),
                  annotation_text=f"Max DD: {max_dd:.1f}%",
                  annotation_font=dict(color="#ef4444", size=11), row=2, col=1)

    fig.update_layout(
        **PLOTLY_BASE, height=420,
        title=dict(text="<b>Portfolio Equity Curve</b>",
                   font=dict(size=15, color="#f1f5f9"), x=0.01),
        showlegend=False, hovermode="x unified",
    )
    for ax in ["xaxis","xaxis2","yaxis","yaxis2"]:
        fig.update_layout(**{ax: dict(gridcolor=GRID_CLR, zerolinecolor=GRID_CLR,
                                      linecolor="#2a2d3e")})
    fig.update_yaxes(title_text="₹ Equity", tickprefix="₹", row=1, col=1)
    fig.update_yaxes(title_text="DD %", row=2, col=1)
    return fig


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 📊 NSE Swing")
    st.markdown("<p style='color:#6b7280;font-size:13px;margin-top:-8px'>Strategy Dashboard</p>",
                unsafe_allow_html=True)
    st.divider()

    tickers = get_tickers()
    selected = st.selectbox("Stock", tickers,
                            index=tickers.index("SBIN") if "SBIN" in tickers else 0)
    lookback = st.select_slider(
        "Chart period", [60, 90, 120, 180, 250, 365, 500],
        value=180, format_func=lambda x: f"{x}d"
    )
    show_trades = st.checkbox("Show trade markers", value=True)
    st.divider()

    try:
        from core.config import load_config
        cfg = load_config()
        st.markdown(f"""
        <div style='font-size:12px;color:#6b7280;line-height:1.8'>
          <span style='color:#94a3b8'>Universe</span>: {len(tickers)} stocks<br>
          <span style='color:#94a3b8'>Config</span>: v{getattr(cfg,'config_version','1.3')}<br>
          <span style='color:#94a3b8'>Risk</span>: {cfg.risk_per_trade_pct}% per trade<br>
          <span style='color:#94a3b8'>ADX filter</span>: ≥ {cfg.adx_long}<br>
          <span style='color:#94a3b8'>SL mult</span>: {cfg.sl_mult}× ATR
        </div>
        """, unsafe_allow_html=True)
    except Exception:
        pass


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_chart, tab_screen, tab_backtest, tab_patterns, tab_paper, tab_analytics, tab_config = st.tabs([
    "  📈 Chart  ", "  🔍 Screener  ", "  ⚙️ Backtest  ",
    "  📐 Patterns  ", "  📋 Paper Trades  ", "  📊 Analytics  ", "  🛠 Config  "
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CHART
# ══════════════════════════════════════════════════════════════════════════════
with tab_chart:
    ticker_ns = f"{selected}.NS"

    with st.spinner(f"Loading {selected}..."):
        full_df = get_stock_data(ticker_ns)
        trades  = get_all_trades()

    if full_df is None or full_df.empty:
        st.warning(f"No data for {selected}.")
    else:
        df   = full_df.tail(lookback)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        chg     = (last["Close"] - prev["Close"]) / prev["Close"] * 100
        chg_col = "#10b981" if chg >= 0 else "#ef4444"
        chg_arrow = "▲" if chg >= 0 else "▼"

        # ── KPI row ───────────────────────────────────────────────────────────
        cols = st.columns(6)
        kpis = [
            ("Close",   f"₹{last['Close']:,.2f}",
             f"{chg_arrow} {abs(chg):.2f}%", chg_col),
            ("EMA 21",  f"₹{last['EMA21']:,.0f}" if "EMA21" in df.columns else "—", "", "#34d399"),
            ("EMA 50",  f"₹{last['EMA50']:,.0f}" if "EMA50" in df.columns else "—", "", "#60a5fa"),
            ("EMA 200", f"₹{last['EMA200']:,.0f}" if "EMA200" in df.columns else "—", "", "#f87171"),
            ("RSI",     f"{last['RSI']:.1f}" if "RSI" in df.columns else "—",
             "Overbought" if last.get("RSI",50) > 70 else "Oversold" if last.get("RSI",50) < 30 else "Neutral",
             "#a78bfa"),
            ("ADX",     f"{last['ADX']:.1f}" if "ADX" in df.columns else "—",
             "Strong" if last.get("ADX",0) > 30 else "Moderate" if last.get("ADX",0) > 20 else "Weak",
             "#fbbf24"),
        ]
        for col, (label, val, delta, color) in zip(cols, kpis):
            delta_col = chg_col if label == "Close" else "#6b7280"
            col.markdown(f"""
            <div class="kpi-card">
              <div class="kpi-label">{label}</div>
              <div class="kpi-value" style="color:{color}">{val}</div>
              <div class="kpi-delta" style="color:{delta_col}">{delta}</div>
            </div>""", unsafe_allow_html=True)

        # ── Trend badges ──────────────────────────────────────────────────────
        bull = bool(last.get("bull_trend", False))
        mesh = bool(last.get("green_mesh", False))
        trend_html = (
            f"<span style='background:#0d4429;color:#10b981;padding:3px 12px;"
            f"border-radius:20px;font-size:12px;font-weight:600'>"
            f"{'🟢 BULLISH' if bull else '🔴 BEARISH'}</span> &nbsp;"
            f"<span style='background:#{'0d2a4a' if mesh else '2d1212'};"
            f"color:#{'60a5fa' if mesh else 'f87171'};"
            f"padding:3px 12px;border-radius:20px;font-size:12px;font-weight:600'>"
            f"{'Green Mesh' if mesh else 'Red Mesh'}</span> &nbsp;"
            f"<span style='color:#6b7280;font-size:12px'>"
            f"Vol: {last['Volume']/1e6:.1f}M</span>"
        )
        st.markdown(trend_html, unsafe_allow_html=True)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # ── Chart ─────────────────────────────────────────────────────────────
        fig = make_chart(df, selected, trades if show_trades else None, lookback)
        st.plotly_chart(fig, use_container_width=True)

        # ── Trade history table ───────────────────────────────────────────────
        if show_trades and not trades.empty:
            t_hist = trades[trades["ticker"] == ticker_ns].copy()
            if not t_hist.empty:
                t_hist = t_hist.sort_values("entry_date", ascending=False)
                wins = (t_hist["pnl_pct"] > 0).mean() * 100
                pf_num = t_hist[t_hist["pnl_pct"]>0]["pnl_pct"].sum()
                pf_den = abs(t_hist[t_hist["pnl_pct"]<=0]["pnl_pct"].sum())
                pf = round(pf_num / pf_den, 2) if pf_den > 0 else 99

                st.markdown(f"""
                <div class="section-header">Trade History — {selected}</div>
                """, unsafe_allow_html=True)
                mc = st.columns(4)
                mc[0].metric("Total trades", len(t_hist))
                mc[1].metric("Win rate", f"{wins:.1f}%")
                mc[2].metric("Profit factor", f"{pf:.2f}")
                mc[3].metric("Avg P&L", f"{t_hist['pnl_pct'].mean():+.2f}%")

                disp = t_hist[["entry_date","signal_type","direction",
                                "entry_price","exit_price","exit_reason","pnl_pct"]].head(20)
                disp["entry_date"] = disp["entry_date"].dt.strftime("%d %b %Y")
                disp["entry_price"] = disp["entry_price"].map("₹{:,.2f}".format)
                disp["exit_price"]  = disp["exit_price"].map("₹{:,.2f}".format)
                disp["pnl_pct"]     = disp["pnl_pct"].map("{:+.2f}%".format)
                disp.columns = ["Date","Signal","Dir","Entry","Exit","Reason","P&L"]
                st.dataframe(disp, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCREENER
# ══════════════════════════════════════════════════════════════════════════════
with tab_screen:
    st.markdown("<div class='section-header'>Live Signal Screener</div>",
                unsafe_allow_html=True)
    c1, c2 = st.columns([1, 4])
    if c1.button("▶ Run Screen", type="primary"):
        try:
            from bot.screener import run_scan

            # Live progress bar + current stock display
            prog_bar  = st.progress(0, text="Starting scan...")
            prog_info = st.empty()

            def _on_progress(current: int, total: int, ticker: str):
                pct  = current / max(total, 1)
                name = ticker.replace(".NS","") if ticker != "done" else "Complete"
                prog_bar.progress(
                    min(pct, 1.0),
                    text=f"Scanning {current}/{total} — {name}"
                )
                prog_info.markdown(
                    f"<span style='color:#6b7280;font-size:12px'>"
                    f"{'⠿ ' if ticker!='done' else '✅ '}"
                    f"{current}/{total} stocks scanned"
                    f"{'  ·  ' + name if ticker!='done' else '  — Scan complete'}"
                    f"</span>",
                    unsafe_allow_html=True,
                )

            res = run_scan(verbose=False, min_pattern_confidence="HIGH",
                          progress_callback=_on_progress)

            prog_bar.empty()
            prog_info.empty()

            st.session_state["signals"]  = res["signals"]
            st.session_state["patterns"] = res["patterns"]
            st.session_state["scan_ts"]  = datetime.now().strftime("%H:%M, %d %b")
        except Exception as e:
            st.error(f"Error: {e}")

    if "signals" in st.session_state:
        sigs = st.session_state["signals"]
        pats = st.session_state["patterns"]
        c2.markdown(f"<span style='color:#6b7280;font-size:13px'>Last scan: {st.session_state.get('scan_ts','')}</span>",
                    unsafe_allow_html=True)

        col_s, col_p = st.columns([1,1])
        col_s.metric("Signals", len(sigs))
        col_p.metric("Patterns", len(pats))

        if sigs:
            st.markdown("<div class='section-header'>Today's Signals</div>",
                        unsafe_allow_html=True)
            for s in sigs:
                is_long = s["direction"] == "LONG"
                accent  = "#10b981" if is_long else "#ef4444"
                dir_ico = "▲ LONG" if is_long else "▼ SHORT"
                h = s.get("hist") or {}
                hist_str = (f"📊 {h['n']} trades · {h['wr']:.0f}% WR · avg {h['avg_pnl']:+.1f}%"
                            if h and h.get("n",0) >= 5 else "")
                score_pct = s['score'] / 7 * 100
                score_col = "#10b981" if s['score']>=6 else "#fbbf24" if s['score']>=4 else "#ef4444"

                st.markdown(f"""
                <div style="background:linear-gradient(135deg,#0f1623,#1a1d2e);
                            border:1px solid {accent}30;border-radius:12px;
                            padding:16px 20px;margin-bottom:10px;
                            border-left:4px solid {accent}">
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                      <span style="font-size:17px;font-weight:700;color:#f1f5f9">
                        {s['ticker'].replace('.NS','')}
                      </span> &nbsp;
                      <span style="background:{accent}22;color:{accent};padding:3px 10px;
                                   border-radius:20px;font-size:12px;font-weight:600">
                        {s['signal_type']}
                      </span> &nbsp;
                      <span style="color:{accent};font-size:13px;font-weight:600">
                        {dir_ico}
                      </span>
                    </div>
                    <div style="text-align:right">
                      <span style="background:{score_col}22;color:{score_col};
                                   padding:4px 12px;border-radius:20px;
                                   font-size:12px;font-weight:700">
                        {s['score']}/7 Score
                      </span>
                    </div>
                  </div>
                  <div style="margin-top:10px;display:flex;gap:24px;font-size:13px">
                    <span><span style="color:#6b7280">Entry</span>&nbsp;
                      <b style="color:#f1f5f9">₹{s['entry']:,.2f}</b></span>
                    <span><span style="color:#6b7280">SL</span>&nbsp;
                      <b style="color:#ef4444">₹{s['sl']:,.2f} ({s['sl_pct']:+.1f}%)</b></span>
                    <span><span style="color:#6b7280">TP</span>&nbsp;
                      <b style="color:#10b981">₹{s['tp']:,.2f} ({s['tp_pct']:+.1f}%)</b></span>
                    <span><span style="color:#6b7280">R/R</span>&nbsp;
                      <b style="color:#f1f5f9">1:{s['rr']}</b></span>
                    <span><span style="color:#6b7280">ADX</span>&nbsp;
                      <b style="color:#fbbf24">{s.get('adx',0):.0f}</b></span>
                  </div>
                  {'<div style="margin-top:6px;font-size:12px;color:#6b7280">' + hist_str + '</div>' if hist_str else ''}
                  {'<div style="margin-top:4px;font-size:11px;color:#f59e0b">⚠ Bear regime — Nifty below EMA200</div>' if s.get('bear_regime_warning') else ''}
                </div>
                """, unsafe_allow_html=True)

        if pats:
            st.markdown("<div class='section-header'>Chart Patterns</div>",
                        unsafe_allow_html=True)
            cols_p = st.columns(2)
            for i, p in enumerate(pats):
                pname = p["pattern"].replace("_"," ").title()
                conf_c = "#10b981" if p["confidence"]=="HIGH" else "#f59e0b"
                bo_tag = " ✅ Breaking out" if p.get("breaking_out") else ""
                cols_p[i%2].markdown(f"""
                <div style="background:#1a1d2e;border:1px solid #2a2d3e;border-radius:10px;
                            padding:12px 14px;margin-bottom:8px;border-left:3px solid {conf_c}">
                  <b style="color:#f1f5f9">{p['ticker'].replace('.NS','')}</b> &nbsp;
                  <span style="color:{conf_c};font-size:12px;font-weight:600">{pname}</span>
                  <span style="color:#10b981;font-size:12px">{bo_tag}</span>
                  <div style="font-size:12px;color:#6b7280;margin-top:4px">{p.get('description','')[:100]}...</div>
                </div>""", unsafe_allow_html=True)
    else:
        st.info("Click **Run Screen** to scan today's signals and patterns.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — BACKTEST
# ══════════════════════════════════════════════════════════════════════════════
with tab_backtest:
    st.markdown("<div class='section-header'>Backtest Engine</div>",
                unsafe_allow_html=True)

    col_a, col_b, col_c = st.columns([1, 1, 3])
    skip_optim = col_a.checkbox("Skip WFO", value=True)
    force_dl   = col_b.checkbox("Force re-download", value=False)
    run_bt     = col_c.button("▶ Run Backtest", type="primary")

    runs = get_runs()
    if not runs.empty:
        latest = runs.iloc[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Trades",        int(latest.get("n_trades", 0)))
        m2.metric("Sharpe",        f"{float(latest.get('sharpe', 0)):.2f}")
        m3.metric("Win Rate",      f"{float(latest.get('win_rate', 0)):.1f}%")
        m4.metric("Max Drawdown",  f"{float(latest.get('max_dd', 0)):.1f}%")

    if run_bt:
        cmd = [sys.executable, "-X", "utf8", "main.py"]
        if skip_optim: cmd.append("--skip-optim")
        if force_dl:   cmd.append("--force-download")
        output_box = st.empty()
        lines = []
        with subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        ) as proc:
            for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace")
                lines.append(line.rstrip())
                if any(k in line for k in ["STAGE","trades","WR=","Sharpe","PORTFOLIO"]):
                    output_box.code("\n".join(lines[-12:]), language=None)
        get_all_trades.clear(); get_runs.clear()
        st.success("✅ Backtest complete! Refresh page to see updated results.")

    # Equity curve
    trades = get_all_trades()
    if not trades.empty:
        st.plotly_chart(make_equity_curve(trades), use_container_width=True)

        # Per-stock table
        st.markdown("<div class='section-header'>Per-Stock Results</div>",
                    unsafe_allow_html=True)
        pnl_col = "pnl_on_equity" if "pnl_on_equity" in trades.columns else "pnl_pct"
        summ = trades.groupby("ticker").agg(
            Trades   = ("pnl_pct", "count"),
            WR       = ("pnl_pct", lambda x: round((x>0).mean()*100, 1)),
            Avg_PnL  = ("pnl_pct", lambda x: round(x.mean(), 2)),
            Sharpe   = (pnl_col,   lambda x: round(x.mean()/x.std()*(252/max(len(x),1))**0.5, 2)
                        if x.std() > 0 else 0),
            Total_PnL= ("pnl_pct", lambda x: round(x.sum(), 1)),
        ).reset_index().sort_values("Sharpe", ascending=False)
        summ["ticker"] = summ["ticker"].str.replace(".NS","")
        st.dataframe(
            summ, use_container_width=True, hide_index=True, height=400,
            column_config={
                "WR":       st.column_config.NumberColumn("WR%",    format="%.1f"),
                "Avg_PnL":  st.column_config.NumberColumn("Avg P&L",format="%+.2f%%"),
                "Sharpe":   st.column_config.NumberColumn("Sharpe", format="%.2f"),
                "Total_PnL":st.column_config.NumberColumn("Total",  format="%.1f%%"),
            }
        )
    else:
        st.info("Run a backtest to see results.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — PATTERNS
# ══════════════════════════════════════════════════════════════════════════════
with tab_patterns:
    st.markdown("<div class='section-header'>Chart Pattern Scanner</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 1, 3])
    conf_f = c1.selectbox("Confidence", ["HIGH","MODERATE"], key="pat_conf")
    n_top  = c2.selectbox("Show top N", [10, 20, 30, 50], index=1)
    scan_p = c3.button("▶ Scan Patterns", type="primary")

    if scan_p:
        from data import TICKERS, RAW_DIR, _safe_name
        from core.pattern_scanner import scan_patterns
        from indicators import prepare_indicators
        all_p = []
        bar = st.progress(0, text="Scanning patterns...")
        for idx, ticker in enumerate(TICKERS):
            bar.progress((idx+1)/len(TICKERS), text=f"{ticker.replace('.NS','')}...")
            csv = os.path.join(RAW_DIR, f"{_safe_name(ticker)}.csv")
            if not os.path.exists(csv): continue
            try:
                raw = pd.read_csv(csv, index_col=0, parse_dates=True)
                raw.index = pd.to_datetime(raw.index).tz_localize(None)
                from indicators import prepare_indicators as pi
                ind = pi(raw)
                for p in scan_patterns(ind):
                    if conf_f == "HIGH" and p["confidence"] != "HIGH": continue
                    p["ticker"] = ticker
                    p["_q"] = (3 if p.get("breaking_out") else 1) + \
                               (2 if p["confidence"]=="HIGH" else 0)
                    all_p.append(p)
            except Exception: pass
        all_p.sort(key=lambda x: -x.pop("_q",0))
        st.session_state["all_patterns"] = all_p
        bar.empty()

    pats = st.session_state.get("all_patterns", [])
    if pats:
        st.caption(f"Found {len(pats)} patterns across universe. Showing top {n_top}.")
        for p in pats[:n_top]:
            pname  = p["pattern"].replace("_"," ").title()
            tclean = p["ticker"].replace(".NS","")
            conf_c = "#10b981" if p["confidence"]=="HIGH" else "#f59e0b"
            bo_tag = "✅ Breaking out" if p.get("breaking_out") else ""

            with st.expander(
                f"{'🟢' if p['confidence']=='HIGH' else '🟡'} "
                f"{tclean}  ·  {pname}  {bo_tag}"
            ):
                st.markdown(f"""<div style="font-size:13px;color:#94a3b8;
                              padding:8px 0">{p.get('description','')}</div>""",
                            unsafe_allow_html=True)
                df_p = get_stock_data(p["ticker"])
                if df_p is not None:
                    fig_p = make_chart(df_p, tclean, get_all_trades(), lookback=120)
                    fig_p.update_layout(height=400)
                    st.plotly_chart(fig_p, use_container_width=True)
    else:
        st.info("Click **Scan Patterns** to find chart patterns across the universe.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — PAPER TRADES
# ══════════════════════════════════════════════════════════════════════════════
with tab_paper:
    st.markdown("<div class='section-header'>Paper Trading — Live Validation</div>",
                unsafe_allow_html=True)
    st.caption("Auto-logged from every screener run. Entry = signal day's close. Window = 14 days.")

    # Manual update button
    col_upd, col_info = st.columns([1, 4])
    if col_upd.button("🔄 Update positions", type="primary"):
        try:
            from core.paper_trader import update_open_positions
            res = update_open_positions()
            col_info.success(
                f"Updated: TP={res['tp_hit']} SL={res['sl_hit']} "
                f"Expired={res['expired']} | Still open: {res['still_open']}"
            )
        except Exception as e:
            col_info.error(str(e))

    try:
        from core.paper_trader import get_stats
        from pathlib import Path
        stats = get_stats()

        if not stats or stats.get("closed", 0) == 0:
            st.info(
                "No closed paper trades yet. Run the screener daily — "
                "trades close automatically when SL/TP is hit or after 14 days. "
                "You'll need ~20-30 closed trades before the statistics are meaningful."
            )
            if stats.get("open", 0) > 0:
                st.metric("Open positions being tracked", stats["open"])
        else:
            # ── KPIs ─────────────────────────────────────────────────────────
            BACKTEST_WR = 42.6   # reference from last full backtest
            wr   = stats["win_rate"]
            diff = wr - BACKTEST_WR
            diff_col = "#10b981" if diff >= 0 else "#ef4444"

            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Logged signals",   stats["total"])
            m2.metric("Open positions",   stats["open"])
            m3.metric("Closed trades",    stats["closed"])
            m4.metric("Live Win Rate",
                      f"{wr:.1f}%",
                      f"{diff:+.1f}pp vs backtest",
                      delta_color="normal")
            m5.metric("Profit Factor",    f"{stats['profit_factor']:.2f}")
            m6.metric("Avg hold (days)",  f"{stats['avg_days']:.1f}")

            st.markdown(
                f"<div style='background:#1a1d2e;border-radius:8px;padding:10px 16px;"
                f"margin:12px 0;border-left:4px solid {diff_col}'>"
                f"<span style='color:#94a3b8;font-size:13px'>Live WR vs Backtest: </span>"
                f"<span style='color:{diff_col};font-weight:700;font-size:14px'>"
                f"{diff:+.1f}pp</span>"
                f"<span style='color:#6b7280;font-size:12px'> — "
                f"{'Edge holding in live market ✓' if diff >= -3 else 'Gap widening — review strategy'}"
                f"</span></div>",
                unsafe_allow_html=True,
            )

            col1, col2 = st.columns(2)

            # ── Win rate by score ─────────────────────────────────────────────
            with col1:
                st.markdown("<div class='section-header'>Win Rate by Score</div>",
                            unsafe_allow_html=True)
                st.caption("Most actionable: tells you which score threshold to use live")
                if stats["by_score"]:
                    rows = sorted(stats["by_score"].items())
                    sc_df = pd.DataFrame([
                        {"Score": f"{k}/7", "Trades": v["n"],
                         "WR%": v["wr"], "Avg P&L": v["avg"]}
                        for k, v in rows
                    ])
                    fig_sc = go.Figure(go.Bar(
                        x=sc_df["Score"], y=sc_df["WR%"],
                        marker_color=[
                            "#10b981" if v >= 50 else "#fbbf24" if v >= 40 else "#ef4444"
                            for v in sc_df["WR%"]
                        ],
                        text=[f"{v:.1f}%" for v in sc_df["WR%"]],
                        textposition="outside",
                    ))
                    fig_sc.add_hline(y=50, line_dash="dot",
                                     line_color="#6b7280", line_width=1)
                    fig_sc.update_layout(
                        **PLOTLY_BASE, height=220,
                        xaxis_title="Signal Score", yaxis_title="Win Rate %",
                        margin=dict(t=10, b=20, l=40, r=20),
                        yaxis=dict(range=[0, 80]),
                    )
                    st.plotly_chart(fig_sc, use_container_width=True)

                    # Recommendation
                    best_score = max(
                        (k for k, v in stats["by_score"].items() if v["n"] >= 3),
                        key=lambda k: stats["by_score"][k]["wr"],
                        default=None,
                    )
                    if best_score:
                        bv = stats["by_score"][best_score]
                        st.success(
                            f"**Recommendation:** Filter signals to Score ≥ {best_score}/7 "
                            f"→ {bv['wr']:.0f}% WR ({bv['n']} trades). "
                            f"Skip scores below {best_score}."
                        )

            # ── Win rate by signal type ───────────────────────────────────────
            with col2:
                st.markdown("<div class='section-header'>Win Rate by Signal Type</div>",
                            unsafe_allow_html=True)
                st.caption("Which signal type actually works in live market")
                if stats["by_signal"]:
                    sig_df = pd.DataFrame([
                        {"Signal": k, "Trades": v["n"],
                         "WR%": v["wr"], "Avg": v["avg"]}
                        for k, v in stats["by_signal"].items()
                    ]).sort_values("WR%", ascending=True)

                    fig_sig = go.Figure(go.Bar(
                        y=sig_df["Signal"], x=sig_df["WR%"],
                        orientation="h",
                        marker_color=[
                            "#10b981" if v >= 50 else "#fbbf24" if v >= 40 else "#ef4444"
                            for v in sig_df["WR%"]
                        ],
                        text=[f"{v:.1f}% ({n})" for v, n in
                              zip(sig_df["WR%"], sig_df["Trades"])],
                        textposition="outside",
                    ))
                    fig_sig.add_vline(x=50, line_dash="dot",
                                      line_color="#6b7280", line_width=1)
                    fig_sig.update_layout(
                        **PLOTLY_BASE, height=220,
                        xaxis_title="Win Rate %",
                        margin=dict(t=10, b=20, l=80, r=60),
                        xaxis=dict(range=[0, 80]),
                    )
                    st.plotly_chart(fig_sig, use_container_width=True)

            # ── Recent closed trades ──────────────────────────────────────────
            if stats.get("recent"):
                st.markdown("<div class='section-header'>Recent Closed Trades</div>",
                            unsafe_allow_html=True)
                for t in stats["recent"]:
                    pnl  = float(t.get("pnl_pct", 0))
                    clr  = "#10b981" if pnl > 0 else "#ef4444"
                    icon = "✅" if pnl > 0 else "❌"
                    reason_col = (
                        "#fbbf24" if str(t.get("exit_reason","")) == "EXPIRED"
                        else clr
                    )
                    st.markdown(
                        f"<div style='background:#1a1d2e;border-radius:8px;"
                        f"padding:10px 16px;margin-bottom:6px;display:flex;"
                        f"justify-content:space-between;align-items:center'>"
                        f"<span><b style='color:#f1f5f9'>{icon} "
                        f"{str(t['ticker']).replace('.NS','')}</b> &nbsp;"
                        f"<span style='color:#6b7280;font-size:12px'>"
                        f"{t['signal_type']}</span></span>"
                        f"<span style='font-size:13px'>"
                        f"₹{float(t['entry_price']):,.2f} → "
                        f"₹{float(t['exit_price']):,.2f}</span>"
                        f"<span style='color:{clr};font-weight:700'>"
                        f"{pnl:+.2f}%</span>"
                        f"<span style='color:{reason_col};font-size:12px'>"
                        f"{t['exit_reason']} · {t['days_held']}d</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

            # ── Raw data download ─────────────────────────────────────────────
            paper_path = Path("logs/paper_trades.csv")
            if paper_path.exists():
                st.markdown("<div class='section-header'>Full Log</div>",
                            unsafe_allow_html=True)
                raw = pd.read_csv(paper_path)
                st.dataframe(raw.sort_values("signal_date", ascending=False),
                             use_container_width=True, height=300,
                             hide_index=True)
                st.download_button(
                    "⬇ Download paper_trades.csv",
                    raw.to_csv(index=False),
                    "paper_trades.csv", "text/csv",
                )

    except Exception as e:
        st.error(f"Paper trades error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — ANALYTICS
# ══════════════════════════════════════════════════════════════════════════════
with tab_analytics:
    trades = get_all_trades()
    if trades.empty:
        st.info("Run a backtest to see analytics.")
    else:
        pnl_col = "pnl_on_equity" if "pnl_on_equity" in trades.columns else "pnl_pct"

        # ── Top-level stats ───────────────────────────────────────────────────
        total_pnl = trades[pnl_col].sum()
        wr_all    = (trades["pnl_pct"] > 0).mean() * 100
        gross_p   = trades[trades["pnl_pct"]>0]["pnl_pct"].sum()
        gross_l   = abs(trades[trades["pnl_pct"]<=0]["pnl_pct"].sum())
        pf        = gross_p / gross_l if gross_l > 0 else 99

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total trades",   len(trades))
        m2.metric("Win rate",       f"{wr_all:.1f}%")
        m3.metric("Profit factor",  f"{pf:.2f}")
        m4.metric("Avg P&L",        f"{trades['pnl_pct'].mean():+.2f}%")
        m5.metric("Best stock",
                  trades.groupby("ticker")["pnl_pct"].mean().idxmax().replace(".NS",""))

        c1, c2 = st.columns(2)

        # Win rate by signal type
        with c1:
            st.markdown("<div class='section-header'>Win Rate by Signal</div>",
                        unsafe_allow_html=True)
            sg = trades.groupby("signal_type").agg(
                n  =("pnl_pct","count"),
                wr =("pnl_pct",lambda x:(x>0).mean()*100),
                avg=("pnl_pct","mean"),
                pf =("pnl_pct",lambda x: x[x>0].sum()/max(abs(x[x<=0].sum()),1e-6)),
            ).reset_index().sort_values("wr",ascending=True)
            fig_sg = go.Figure(go.Bar(
                y=sg["signal_type"], x=sg["wr"], orientation="h",
                marker=dict(color=sg["wr"],
                            colorscale=[[0,"#ef4444"],[0.5,"#fbbf24"],[1,"#10b981"]],
                            cmin=30, cmax=60),
                text=[f"{v:.1f}%" for v in sg["wr"]], textposition="outside",
            ))
            fig_sg.update_layout(**PLOTLY_BASE, height=220,
                                 xaxis_title="Win Rate %",
                                 margin=dict(t=10,b=20,l=80,r=60))
            st.plotly_chart(fig_sg, use_container_width=True)

        # Exit reason breakdown
        with c2:
            st.markdown("<div class='section-header'>Exit Breakdown</div>",
                        unsafe_allow_html=True)
            ex = trades["exit_reason"].value_counts().reset_index()
            fig_ex = px.pie(ex, values="count", names="exit_reason",
                            color_discrete_map={"TP":"#10b981","SL":"#ef4444",
                                                "MeshBreak":"#60a5fa","Trail":"#fbbf24"},
                            hole=0.55)
            fig_ex.update_layout(**PLOTLY_BASE, height=220,
                                 showlegend=True,
                                 legend=dict(orientation="h", y=-0.15),
                                 margin=dict(t=10,b=40))
            fig_ex.update_traces(textfont_color="white")
            st.plotly_chart(fig_ex, use_container_width=True)

        # Monthly heatmap
        st.markdown("<div class='section-header'>Monthly Returns Heatmap</div>",
                    unsafe_allow_html=True)
        trades["yr"] = trades["exit_date"].dt.year
        trades["mo"] = trades["exit_date"].dt.month
        mon_pnl = trades.groupby(["yr","mo"])[pnl_col].sum().reset_index()
        pivot   = mon_pnl.pivot(index="yr", columns="mo", values=pnl_col).fillna(0)
        mon_names = {1:"Jan",2:"Feb",3:"Mar",4:"Apr",5:"May",6:"Jun",
                     7:"Jul",8:"Aug",9:"Sep",10:"Oct",11:"Nov",12:"Dec"}
        pivot.columns = [mon_names.get(c,str(c)) for c in pivot.columns]

        fig_h = px.imshow(pivot, color_continuous_scale="RdYlGn",
                          text_auto=".1f", aspect="auto",
                          color_continuous_midpoint=0,
                          labels=dict(color="P&L %"))
        fig_h.update_layout(**PLOTLY_BASE, height=280,
                            xaxis_title="", yaxis_title="",
                            margin=dict(t=10, b=20))
        fig_h.update_coloraxes(showscale=False)
        fig_h.update_traces(textfont_size=11)
        st.plotly_chart(fig_h, use_container_width=True)

        # Bars held distribution
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("<div class='section-header'>Holding Period</div>",
                        unsafe_allow_html=True)
            fig_bh = px.histogram(trades, x="bars_held", nbins=30,
                                  color_discrete_sequence=["#60a5fa"])
            fig_bh.update_layout(**PLOTLY_BASE, height=220,
                                 xaxis_title="Bars held", yaxis_title="Count",
                                 margin=dict(t=10,b=20))
            st.plotly_chart(fig_bh, use_container_width=True)

        with c4:
            st.markdown("<div class='section-header'>P&L Distribution</div>",
                        unsafe_allow_html=True)
            fig_pl = px.histogram(trades, x="pnl_pct", nbins=40,
                                  color_discrete_sequence=["#10b981"])
            fig_pl.update_layout(**PLOTLY_BASE, height=220,
                                 xaxis_title="P&L %", yaxis_title="Count",
                                 margin=dict(t=10,b=20))
            fig_pl.add_vline(x=0, line_color="#ef4444", line_width=1, line_dash="dot")
            st.plotly_chart(fig_pl, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — CONFIG
# ══════════════════════════════════════════════════════════════════════════════
with tab_config:
    st.markdown("<div class='section-header'>Strategy Configuration</div>",
                unsafe_allow_html=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        try:
            yaml_path = Path("config/strategy.yaml")
            content   = yaml_path.read_text(encoding="utf-8")
            new_yaml  = st.text_area("strategy.yaml",  content, height=420)
            bc1, bc2  = st.columns(2)
            if bc1.button("💾 Save", type="primary"):
                yaml_path.write_text(new_yaml, encoding="utf-8")
                try:
                    for m in list(sys.modules):
                        if "core" in m: del sys.modules[m]
                except Exception: pass
                st.success("Saved! Re-run backtest to validate.")
            if bc2.button("↩ Discard"):
                st.rerun()
        except Exception as e:
            st.error(str(e))

    with c2:
        st.markdown("<div class='section-header'>Run History</div>",
                    unsafe_allow_html=True)
        runs = get_runs()
        if not runs.empty:
            disp = runs[["timestamp","n_trades","sharpe","win_rate","max_dd"]].tail(10)
            disp = disp.sort_values("timestamp", ascending=False)
            disp["sharpe"]   = disp["sharpe"].round(2)
            disp["win_rate"] = disp["win_rate"].map("{:.1f}%".format)
            disp["max_dd"]   = disp["max_dd"].map("{:.1f}%".format)
            st.dataframe(disp, use_container_width=True, hide_index=True,
                         height=380)
        else:
            st.info("No backtest runs yet.")
