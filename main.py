import streamlit as st
import asyncio
from binance.client import Client
import pandas as pd
import requests
from ta.momentum import RSIIndicator
from dotenv import load_dotenv
import os

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Importando credenciais
api_key_spot = os.getenv("api_key_spot")
api_secret_spot = os.getenv("api_secret_spot")
telegram_bot_token = os.getenv("telegram_bot_token")
telegram_chat_id = os.getenv("telegram_chat_id")

# Inicializando o cliente Binance
client = Client(api_key_spot, api_secret_spot)

# Funções auxiliares
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

async def fetch_ticker_and_candles(symbol, timeframe):
    try:
        candles = client.get_klines(symbol=symbol, interval=timeframe, limit=50)
        df = pd.DataFrame(candles, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 
                                            'close_time', 'quote_asset_volume', 'number_of_trades', 
                                            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
        
        # Convertendo para os tipos corretos
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)

        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])

        return current_price, df
    except Exception as e:
        st.error(f"Erro ao obter dados de {symbol} no timeframe {timeframe}: {e}")
        return None, None

async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": message}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao enviar mensagem para o Telegram: {e}")

# Controle de notificações para evitar repetições
last_notifications = {}

async def notify_conditions(symbol, timeframes, notify_telegram, signal_choice):
    """Envia notificações com controle de repetição."""
    while True:
        for timeframe in timeframes:
            current_price, df = await fetch_ticker_and_candles(symbol, timeframe)
            if df is None:
                await asyncio.sleep(5)
                continue

            # Indicadores
            df = calculate_bollinger_bands(df)
            df = calculate_stochastic_oscillator(df)
            rsi_indicator = RSIIndicator(df['close'], window=14)
            df['rsi'] = rsi_indicator.rsi()

            upper_band = df['upper_band'].iloc[-1]
            lower_band = df['lower_band'].iloc[-1]
            stochastic_k = df['%K'].iloc[-1]
            stochastic_d = df['%D'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            volume_ma = df['volume'].rolling(window=21).mean().iloc[-1]  # Média móvel de volume

            # Novo critério: volume > 100% acima da média (2x a média)
            high_volume = df['volume'].iloc[-1] > 3 * volume_ma

            # Determinar sinal atual
            current_signal = None
            if (
                current_price < lower_band and 
                stochastic_k < 20 and 
                stochastic_d < 20 and 
                high_volume and 
                rsi < 30 and
                signal_choice in ["Compra", "Ambos"]
            ):
                current_signal = "COMPRA"
            elif (
                current_price > upper_band and 
                stochastic_k > 80 and 
                stochastic_d > 80 and 
                high_volume and 
                rsi > 70 and
                signal_choice in ["Venda", "Ambos"]
            ):
                current_signal = "VENDA"

            # Evitar notificações repetidas
            key = f"{symbol}_{timeframe}"
            last_signal = last_notifications.get(key)

            if current_signal and current_signal != last_signal:
                message = (
                    f"Sinal de {current_signal} para {symbol} no timeframe {timeframe}:\n"
                    f"Preço atual: {current_price}\n"
                )
                st.info(message)
                if notify_telegram:
                    await send_telegram_message(message)
                last_notifications[key] = current_signal

            await asyncio.sleep(60)

# Configuração do Streamlit
st.title("Robô de Notificação para Criptomoedas")
st.write("O sistema utiliza uma combinação de indicadores técnicos para gerar sinais de compra e venda.")

# Entrada do usuário
all_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "DOTUSDT", "DOGEUSDT", "FTMUSDT", "ASTRUSDT", "XRPUSDT", "SOLUSDT", 
               "LTCUSDT", "PENDLEUSDT", "AAVEUSDT", "ORDIUSDT", "UNIUSDT", "LINKUSDT", 
               "ENSUSDT", "MOVRUSDT", "ARBUSDT", "TRBUSDT", "MANTAUSDT", "AVAXUSDT", "ADAUSDT", "GALAUSDT","LDOUSDT"]

select_all = st.sidebar.checkbox("Selecionar todos os pares")
symbols = st.sidebar.multiselect("Selecione os pares de moedas", all_symbols, default=all_symbols if select_all else [])
timeframes = st.sidebar.multiselect("Selecione o(s) timeframe(s)", ["1m", "5m", "15m", "1h", "4h", "1d"])
notify_telegram = st.sidebar.checkbox("Enviar notificações no Telegram", value=False)
signal_choice = st.sidebar.radio("Selecione os sinais desejados", ["Compra", "Venda", "Ambos"], index=2)

if st.sidebar.button("Iniciar Monitoramento"):
    if not symbols:
        st.error("Por favor, selecione pelo menos um par de moedas.")
    elif not timeframes:
        st.error("Por favor, selecione pelo menos um timeframe.")
    else:
        if notify_telegram:
            st.success("Monitoramento iniciado com notificações no Telegram! Acompanhe os alertas abaixo.")
        else:
            st.warning("Monitoramento iniciado sem notificações no Telegram. Apenas os alertas locais serão exibidos.")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tasks = [notify_conditions(symbol, timeframes, notify_telegram, signal_choice) for symbol in symbols]
        loop.run_until_complete(asyncio.gather(*tasks))
