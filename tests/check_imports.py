import sys
import os
sys.path.append(os.getcwd())

try:
    print("Checking imports...")
    from src.data.state import TradingState
    print("1. TradingState OK")
    from src.workers.market_worker import MarketWorker
    print("2. MarketWorker OK")
    from src.workers.sync_worker import DataSyncWorker
    print("3. DataSyncWorker OK")
    from src.workers.trade_worker import TradeWorker
    print("4. TradeWorker OK")
    from src.data_manager import DataManager
    print("5. DataManager OK")
    print("\nAll imports successful!")
except Exception as e:
    print(f"\nImport failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
