from ib_insync import IB
import logging

def main():
    # Optional: Setup logging to see connection info and potential errors.
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

    # Create an IB instance.
    ib = IB()

    try:
        # Connect to IB Gateway. Adjust host, port, and clientId as needed.
        # For IB Gateway, the default port is usually 4002.
        ib.connect(host='127.0.0.1', port=4001, clientId=1, readonly=True)
        logging.info("Successfully connected to IB Gateway!")
        
        # Optionally, you can perform a read-only request. For example, request the current time:
        serverTime = ib.reqCurrentTime()
        logging.info(f"Server time: {serverTime}")

    except Exception as e:
        logging.error(f"Error connecting to IB Gateway: {e}")

    try:
        # Perform other operations here, such as retrieving account information, market data, etc.
        # For example, you can fetch account values:
        logging.info("Testing functionality...")
        result = ib.trades()
        logging.info(f"Result: {result}")
    
    finally:
        # Always disconnect to clean up the connection.
        if ib.isConnected():
            ib.disconnect()
            logging.info("Disconnected from IB Gateway.")

if __name__ == '__main__':
    main()
