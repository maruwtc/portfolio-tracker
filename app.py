import logging
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from ib_insync import IB
import yfinance as yf  # Ensure you have installed yfinance via `pip install yfinance`

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize IB instance
ib = IB()
try:
    # Adjust host, port, and clientId as needed.
    ib.connect(host='127.0.0.1', port=4001, clientId=1001)
    logging.info("Successfully connected to IB Gateway/TWS!")
except Exception as e:
    logging.error(f"Error connecting to IB Gateway/TWS: {e}")
    raise e

def fetch_portfolio():
    """
    Retrieves portfolio positions and enriches each with live market data.
    """
    try:
        positions = ib.positions()
    except Exception as e:
        logging.error(f"Error retrieving positions: {e}")
        return []
    
    portfolio_data = []
    for pos in positions:
        try:
            yf_ticker = yf.Ticker(pos.contract.symbol)
            currentPrice = yf_ticker.info.get('regularMarketPrice', 0.0)
            logging.info(f"Fetched yfinance price for {pos.contract.symbol}: {currentPrice}")
        except Exception as e:
            logging.error(f"Error fetching yfinance data for {pos.contract.symbol}: {e}")
            currentPrice = 0.0

        data = {
            'account': pos.account,
            'symbol': pos.contract.symbol,
            'secType': pos.contract.secType,
            'exchange': pos.contract.exchange,
            'currency': pos.contract.currency,
            'position': pos.position,
            'avgCost': pos.avgCost,
            'currentPrice': currentPrice,
            'marketValue': pos.position * currentPrice,
            'pnl': pos.position * (currentPrice - pos.avgCost)
        }
        portfolio_data.append(data)
    return portfolio_data

def fetch_account_summary():
    """
    Retrieves account summary details (e.g. cash balance, unrealized P&L) from IB.
    """
    try:
        value = ib.accountValues()
    except Exception as e:
        logging.error(f"Error retrieving account values: {e}")
        return {}
    
    account_summary = {}
    for item in value:
        account_summary[item.tag] = item.value
    return account_summary

@app.route('/')
def portfolio():
    portfolio_data = fetch_portfolio()
    account_summary = fetch_account_summary()

    total_positions = len(portfolio_data)
    market_value = sum(item['marketValue'] for item in portfolio_data)

    # Conversion rate: 1 USD = 7.8 HKD
    conversion_rate = 7.8

    # Convert account summary values from HKD to USD if necessary
    try:
        cash_balance_hkd = float(account_summary.get('TotalCashValue', 0))
    except (TypeError, ValueError):
        cash_balance_hkd = 0

    try:
        unrealizedPnL_hkd = float(account_summary.get('UnrealizedPnL', 0))
    except (TypeError, ValueError):
        unrealizedPnL_hkd = 0

    # Convert values from HKD to USD
    cash_balance = cash_balance_hkd / conversion_rate
    unrealizedPnL = unrealizedPnL_hkd / conversion_rate

    net_value=market_value+cash_balance

    # Calculate an approximate daily percentage change (all in USD)
    daily_change_pct = (unrealizedPnL / (market_value - unrealizedPnL) * 100) if net_value else 0

    # Optionally, update account_summary to show USD values
    account_summary['TotalCashValue'] = f"${cash_balance:.2f} (USD)"
    account_summary['UnrealizedPnL'] = f"${unrealizedPnL:.2f} (USD)"

    return render_template(
        'portfolio.html',
        portfolio=portfolio_data,
        total_positions=total_positions,
        net_value=net_value,
        market_value=market_value,
        cash_balance=cash_balance,
        daily_change=daily_change_pct,
        account_summary=account_summary
    )



@app.route('/api/portfolio')
def api_portfolio():
    portfolio_data = fetch_portfolio()
    return jsonify(portfolio_data)

@app.route('/api/benchmark')
def api_benchmark():
    """
    Retrieves monthly benchmark closing prices for the S&P 500 from Yahoo Finance.
    """
    try:
        # ^GSPC is the ticker symbol for the S&P 500 index on Yahoo Finance
        sp500 = yf.Ticker('^GSPC')
        # Fetch one year of data with monthly intervals
        hist = sp500.history(period="1y", interval="1mo")
        benchmark_data = []
        for date, row in hist.iterrows():
            benchmark_data.append({
                'month': date.strftime('%b'),
                'close': round(row['Close'], 2)
            })
        return jsonify(benchmark_data)
    except Exception as e:
        logging.error(f"Error fetching benchmark data: {e}")
        return jsonify([]), 500
    
@app.route('/api/account-summary')
def api_account_summary():
    account_summary = fetch_account_summary()
    return jsonify(account_summary)

@app.teardown_appcontext
def shutdown_session(exception=None):
    """
    Disconnect from IB Gateway/TWS when the Flask application context ends.
    """
    if ib.isConnected():
        ib.disconnect()
        logging.info("Disconnected from IB Gateway/TWS.")

if __name__ == '__main__':
    # Disable the reloader to avoid multiple IB connections during development
    app.run(debug=True, use_reloader=False)
