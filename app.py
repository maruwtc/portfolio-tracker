import logging
from flask import Flask, render_template, jsonify
from flask_cors import CORS
from ib_insync import IB
import yfinance as yf  # pip install yfinance
# Import Firstrade modules
from firstrade import account, symbols
import os
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(level=logging.ERROR, format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__)
cors = CORS(app, resources={r"/api/*": {"origins": "*"}})

# Load environment variables from a .env file
load_dotenv()

# -----------------------------
# IB Initialization
# -----------------------------
IBGATEWAY_PATH = os.getenv("IBGATEWAY_PATH")
IBGATEWAY_PORT = os.getenv("IBGATEWAY_PORT")
IBGATEWAY_CLIENTID = os.getenv("IBGATEWAY_CLIENTID")

ib = IB()
try:
    # Adjust host, port, and clientId as needed.
    ib.connect(
        host=IBGATEWAY_PATH,
        port=IBGATEWAY_PORT,
        clientId=IBGATEWAY_CLIENTID, 
        readonly=True
    )
    logging.info("Successfully connected to IB Gateway/TWS!")
except Exception as e:
    logging.error(f"Error connecting to IB Gateway/TWS: {e}")
    raise e

# -----------------------------
# Firstrade Initialization
# -----------------------------
FTUSERNAME = os.getenv("FTUSERNAME")
FTPASSWORD = os.getenv("FTPASSWORD")
FTEMAIL = os.getenv("FTEMAIL")
FTPROFILE_PATH = os.getenv("FTPROFILE_PATH")
try:
    # Replace the empty strings with your actual Firstrade credentials.
    ft_ss = account.FTSession(
        username=FTUSERNAME,
        password=FTPASSWORD,
        email=FTEMAIL,
        profile_path=FTPROFILE_PATH
    )
    need_code = ft_ss.login()
    if need_code:
        # In a production app, avoid interactive input on startup.
        code = input("Please enter the pin sent to your email/phone: ")
        ft_ss.login_two(code)
    logging.info("Successfully logged into Firstrade!")
except Exception as e:
    logging.error(f"Error initializing Firstrade session: {e}")
    ft_ss = None

# Retrieve Firstrade account data if session exists.
ft_accounts = None
if ft_ss:
    try:
        ft_accounts = account.FTAccountData(ft_ss)
        if len(ft_accounts.account_numbers) < 1:
            raise Exception("No Firstrade accounts found.")
        logging.info("Firstrade account data retrieved successfully!")
    except Exception as e:
        logging.error(f"Error retrieving Firstrade account data: {e}")

# -----------------------------
# Portfolio Fetch Functions
# -----------------------------
def fetch_ib_portfolio():
    """
    Retrieves IB portfolio positions and enriches each with live market data.
    """
    try:
        positions = ib.positions()
    except Exception as e:
        logging.error(f"Error retrieving IB positions: {e}")
        return []
    
    portfolio_data = []
    for pos in positions:
        try:
            yf_ticker = yf.Ticker(pos.contract.symbol)
            current_price = yf_ticker.info.get('regularMarketPrice', 0.0)
            logging.info(f"Fetched yfinance price for {pos.contract.symbol}: {current_price}")
        except Exception as e:
            logging.error(f"Error fetching yfinance data for {pos.contract.symbol}: {e}")
            current_price = 0.0

        data = {
            'account': pos.account,
            'symbol': pos.contract.symbol,
            'secType': pos.contract.secType,
            'exchange': pos.contract.exchange,
            'currency': pos.contract.currency,
            'position': pos.position,
            'avgCost': pos.avgCost,
            'currentPrice': current_price,
            'marketValue': pos.position * current_price,
            'pnl': pos.position * (current_price - pos.avgCost)
        }
        portfolio_data.append(data)
    return portfolio_data

def fetch_firstrade_portfolio():
    """
    Retrieves Firstrade portfolio positions and enriches each with live market data.
    """
    if not ft_accounts or not ft_accounts.account_numbers:
        return []
    account_num = ft_accounts.account_numbers[0]
    try:
        positions = ft_accounts.get_positions(account=account_num)
    except Exception as e:
        logging.error(f"Error retrieving Firstrade positions: {e}")
        return []
    
    portfolio_data = []
    for item in positions["items"]:
        symbol_ = item["symbol"]
        quantity = float(item.get("quantity", 0))
        try:
            # Use Firstrade's quote API for the symbol.
            quote = symbols.SymbolQuote(ft_ss, account_num, symbol_)
            # Use the 'last' price as the current market price.
            current_price = float(quote.last) if quote.last else 0.0
        except Exception as e:
            logging.error(f"Error fetching Firstrade quote for {symbol_}: {e}")
            current_price = 0.0
        
        # Attempt to read average cost if available; otherwise default to 0.
        avg_cost = float(item.get("avgCost", 0))
        data = {
            'account': account_num,
            'symbol': symbol_,
            'position': quantity,
            'avgCost': avg_cost,
            'currentPrice': current_price,
            'marketValue': quantity * current_price,
            'pnl': quantity * (current_price - avg_cost)
        }
        portfolio_data.append(data)
    return portfolio_data

def fetch_combined_portfolio():
    """
    Combines portfolio data from both IB and Firstrade.
    """
    return fetch_ib_portfolio() + fetch_firstrade_portfolio()

def fetch_account_summary():
    """
    Retrieves account summary details from IB.
    (You can extend this function to merge Firstrade account data if desired.)
    """
    try:
        values = ib.accountValues()
    except Exception as e:
        logging.error(f"Error retrieving IB account values: {e}")
        return {}
    
    account_summary = {}
    for item in values:
        account_summary[item.tag] = item.value
    return account_summary

def fetch_firstrade_history():
    """
    Retrieves the Firstrade account history for a custom date range.
    """
    if not ft_accounts or not ft_accounts.account_numbers:
        return []
    account_num = ft_accounts.account_numbers[0]
    try:
        history = ft_accounts.get_account_history(
            account=account_num,
            date_range="cust",
            custom_range=["2024-01-01", "2024-06-30"]
        )
    except Exception as e:
        logging.error(f"Error fetching Firstrade history: {e}")
        return []
    return history.get("items", [])

# -----------------------------
# Flask Routes
# -----------------------------
@app.route('/')
def portfolio():
    # Combine IB and Firstrade portfolio data.
    portfolio_data = fetch_combined_portfolio()
    account_summary = fetch_account_summary()

    total_positions = len(portfolio_data)
    market_value = sum(item['marketValue'] for item in portfolio_data)

    # Conversion rate: 1 USD = 7.8 HKD
    conversion_rate = 7.8
    try:
        cash_balance_hkd = float(account_summary.get('TotalCashValue', 0))
    except (TypeError, ValueError):
        cash_balance_hkd = 0
    try:
        unrealizedPnL_hkd = float(account_summary.get('UnrealizedPnL', 0))
    except (TypeError, ValueError):
        unrealizedPnL_hkd = 0

    cash_balance = cash_balance_hkd / conversion_rate
    unrealizedPnL = unrealizedPnL_hkd / conversion_rate
    net_value = market_value + cash_balance

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

@app.route('/trading-history')
def trading_history():
    """
    Renders the trading history page.
    (Currently using IB trading data; extend as needed.)
    """
    # For simplicity, using an empty list for IB executions.
    trades = []
    return render_template('trading_history.html', trades=trades)

# API route for combined portfolio data
@app.route('/api/portfolio')
def api_portfolio():
    portfolio_data = fetch_combined_portfolio()
    return jsonify(portfolio_data)

# API route for Firstrade account history
@app.route('/api/firstrade-history')
def api_firstrade_history():
    history_items = fetch_firstrade_history()
    return jsonify(history_items)

# -----------------------------
# Cleanup
# -----------------------------
@app.teardown_appcontext
def shutdown_session(exception=None):
    if ib.isConnected():
        ib.disconnect()
        logging.info("Disconnected from IB Gateway/TWS.")
    # Delete Firstrade cookies if the session exists.
    if ft_ss:
        ft_ss.delete_cookies()
        logging.info("Firstrade session cookies deleted.")

if __name__ == '__main__':
    # Run Flask with HTTPS.
    # Ensure you have 'cert.pem' and 'key.pem' files in your project directory.
    FLASKPATH = os.getenv("FLASKPATH")
    FLASKPORT = os.getenv("FLASKPORT")
    FLASKSSLCERT = os.getenv("FLASKSSLCERT")
    FLASKSSLKEY = os.getenv("FLASKSSLKEY")
    app.run(
        debug=True,
        use_reloader=False,
        host=FLASKPATH,
        port=FLASKPORT,
        ssl_context=(FLASKSSLCERT, FLASKSSLKEY)
    )