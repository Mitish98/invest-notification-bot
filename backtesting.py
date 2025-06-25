import pandas as pd
from binance.client import Client
from ta.momentum import RSIIndicator
from dotenv import load_dotenv
import os
import time
from datetime import datetime
import xlsxwriter

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Credenciais Binance
api_key_spot = os.getenv("api_key_spot")
api_secret_spot = os.getenv("api_secret_spot")

# Inicializar o cliente Binance
client = Client(api_key_spot, api_secret_spot)

# Lista de pares de moedas
symbol_list = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "DOTUSDT", "DOGEUSDT", "FTMUSDT", "ASTRUSDT", "XRPUSDT", "SOLUSDT", 
    "LTCUSDT", "AAVEUSDT", "ORDIUSDT", "UNIUSDT", "LINKUSDT", 
    "ENSUSDT", "MOVRUSDT", "ARBUSDT", "TRBUSDT", "MANTAUSDT", "AVAXUSDT", "ADAUSDT", "GALAUSDT", "LDOUSDT"
]

# Lista de timeframes disponíveis
timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

# Funções auxiliares
def fetch_historical_data(symbol, timeframe, limit=1000, max_data_points=1000):
    """
    Busca o máximo de dados históricos, segmentados em múltiplas solicitações.
    """
    all_data = []
    last_timestamp = None  # Inicializar com None para começar com os dados mais recentes
    
    while len(all_data) < max_data_points:
        try:
            candles = client.get_klines(
                symbol=symbol, 
                interval=timeframe, 
                limit=limit, 
                endTime=last_timestamp
            )
            
            if not candles:
                break  # Para quando não houver mais dados disponíveis
            
            # Adicionar dados ao conjunto
            all_data.extend(candles)
            
            # Atualizar o timestamp para a próxima solicitação
            last_timestamp = candles[0][0]  # Usar o timestamp inicial da primeira vela
            time.sleep(1)  # Pequeno delay para evitar limitações de taxa da API
        
        except Exception as e:
            print(f"Erro ao buscar dados para {symbol} ({timeframe}): {e}")
            break

    # Converter para DataFrame
    df = pd.DataFrame(all_data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume', 
        'close_time', 'quote_asset_volume', 'number_of_trades', 
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df[:max_data_points]  # Retorna até o máximo permitido

def calculate_bollinger_bands(df, num_periods=21, std_dev_factor=2):
    df['SMA'] = df['close'].rolling(window=num_periods).mean()
    df['std_dev'] = df['close'].rolling(window=num_periods).std()
    df['upper_band'] = df['SMA'] + (std_dev_factor * df['std_dev'])
    df['lower_band'] = df['SMA'] - (std_dev_factor * df['std_dev'])
    return df

def calculate_stochastic_oscillator(df, k_period=14, d_period=3):
    df['L14'] = df['low'].rolling(window=k_period).min()
    df['H14'] = df['high'].rolling(window=k_period).max()
    df['%K'] = ((df['close'] - df['L14']) / (df['H14'] - df['L14'])) * 100
    df['%D'] = df['%K'].rolling(window=d_period).mean()
    return df

def calculate_drawdown(trades):
    """
    Calcula o Drawdown máximo com base nos trades realizados.
    """
    balances = [100]  # Saldo inicial
    for trade in trades:
        if trade['type'] == 'BUY':
            balances.append(balances[-1] - (trade['price'] * trade['size']))
        elif trade['type'] == 'SELL':
            balances.append(balances[-1] + (trade['price'] * trade['size']))
    peak = -float('inf')
    max_drawdown = 0
    for balance in balances:
        if balance > peak:
            peak = balance
        drawdown = peak - balance
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    return (max_drawdown / peak) * 100 if peak > 0 else 0

def calculate_hit_rate(trades):
    """
    Calcula a taxa de acerto com base nos trades lucrativos.
    """
    wins = 0
    total_trades = 0
    for i in range(0, len(trades) - 1, 2):  # Itera em pares de trades (compra e venda)
        if trades[i]['type'] == 'BUY' and trades[i + 1]['type'] == 'SELL':
            total_trades += 1
            if trades[i + 1]['price'] > trades[i]['price']:  # Verifica lucro
                wins += 1
    hit_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    return hit_rate, total_trades

def backtest_strategy(symbol, timeframe, initial_balance=100, trade_size=0.1):
    # Baixa os dados históricos
    df = fetch_historical_data(symbol, timeframe, max_data_points=1000)

    # Calcula os indicadores técnicos
    df = calculate_bollinger_bands(df)
    df = calculate_stochastic_oscillator(df)
    rsi = RSIIndicator(df['close'], window=14)
    df['rsi'] = rsi.rsi()

    # Variáveis de backtest
    balance = initial_balance
    position = 0  # 0 = sem posição, >0 = comprado
    trades = []

    # Simula a estratégia
    for i in range(len(df)):
        price = df['close'].iloc[i]
        if position == 0:
            # Sinal de compra
            if price < df['lower_band'].iloc[i] and df['%K'].iloc[i] < 20 and df['rsi'].iloc[i] < 30:
                amount = balance * trade_size / price
                balance -= amount * price
                position += amount
                trades.append({'type': 'BUY', 'price': price, 'size': amount, 'time': df['open_time'].iloc[i]})
        elif position > 0:
            # Sinal de venda
            if price > df['upper_band'].iloc[i] and df['%K'].iloc[i] > 80 and df['rsi'].iloc[i] > 70:
                balance += position * price
                trades.append({'type': 'SELL', 'price': price, 'size': position, 'time': df['open_time'].iloc[i]})
                position = 0

    # Calcula métricas
    final_balance = balance + (position * df['close'].iloc[-1] if position > 0 else 0)
    max_drawdown = calculate_drawdown(trades)
    hit_rate, total_trades = calculate_hit_rate(trades)

    return {
        "final_balance": final_balance,
        "profit": final_balance - initial_balance,
        "max_drawdown": max_drawdown,
        "hit_rate": hit_rate,
        "total_trades": total_trades
    }

# Configuração principal
if __name__ == "__main__":
    excel_file = f"backtesting_results_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
    with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
        for symbol in symbol_list:
            results = []
            for timeframe in timeframes:
                print(f"Iniciando backtest para {symbol} no timeframe {timeframe}...")
                try:
                    metrics = backtest_strategy(symbol, timeframe)
                    results.append({
                        "Timeframe": timeframe,
                        "Final Balance": metrics["final_balance"],
                        "Profit": metrics["profit"],
                        "Max Drawdown (%)": metrics["max_drawdown"],
                        "Hit Rate (%)": metrics["hit_rate"],
                        "Total Trades": metrics["total_trades"]
                    })
                except Exception as e:
                    print(f"Erro no backtest para {symbol} ({timeframe}): {e}")
                    results.append({
                        "Timeframe": timeframe,
                        "Final Balance": None,
                        "Profit": None,
                        "Max Drawdown (%)": None,
                        "Hit Rate (%)": None,
                        "Total Trades": None
                    })
            df = pd.DataFrame(results)
            df.to_excel(writer, sheet_name=symbol[:31], index=False)

    print(f"Resultados salvos no arquivo: {excel_file}")
