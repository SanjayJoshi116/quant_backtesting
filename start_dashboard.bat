@echo off
title NSE Swing Dashboard
cd /d "C:\Users\shast\Desktop\Quant backtesting\quant_backtest"
echo Starting NSE Swing Dashboard...
echo Open http://localhost:8501 in your browser
python -m streamlit run dashboard.py --server.port 8501 --server.headless true
pause
