import streamlit as st
import asyncio
from binance.client import Client
import pandas as pd
import requests
import time
import datetime
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

# Verificar se as credenciais foram carregadas corretamente
if not api_key_spot or not api_secret_spot:
    st.error("As credenciais da API não foram carregadas corretamente. Verifique o arquivo .env.")
if not telegram_bot_token or not telegram_chat_id:
    st.warning("As credenciais do Telegram não foram carregadas. As notificações não funcionarão.")

# Inicializando o cliente Binance
client = Client(api_key_spot, api_secret_spot)

# Funções auxiliares
def sync_time():
    try:
        url = 'https://fapi.binance.com/fapi/v1/time'
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        server_time = response.json()['serverTime']
        local_time = int(time.time() * 1000)
        time_difference = server_time - local_time
        return time_difference
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao sincronizar o tempo: {e}")
        return 0

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
        # Obtendo dados de candles
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

        # Obtendo o preço atual
        ticker = client.get_symbol_ticker(symbol=symbol)
        current_price = float(ticker['price'])

        return current_price, df
    except Exception as e:
        st.error(f"Erro ao obter dados de {symbol} no timeframe {timeframe}: {e}")
        return None, None

async def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": telegram_chat_id,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao enviar mensagem para o Telegram: {e}")

async def notify_conditions(symbol, timeframes, notify_telegram):
    """Envia notificações continuamente com base nas condições técnicas para múltiplos timeframes."""
    while True:  # Loop infinito
        for timeframe in timeframes:
            current_price, df = await fetch_ticker_and_candles(symbol, timeframe)
            if df is None:
                await asyncio.sleep(5)  # Espera 5 segundos antes de tentar novamente
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
            volume_ma = df['volume'].rolling(window=21).mean().iloc[-1]

            # Condições de compra
            if current_price < lower_band and stochastic_k < 20 and stochastic_d < 20 and df['volume'].iloc[-1] > volume_ma and rsi < 30:
                message = f"Sinal de COMPRA para {symbol} no timeframe {timeframe}: Preço atual: {current_price}"
                st.info(message)
                if notify_telegram:
                    await send_telegram_message(message)

            # Condições de venda
            if current_price > upper_band and stochastic_k > 80 and stochastic_d > 80 and df['volume'].iloc[-1] > volume_ma and rsi > 70:
                message = f"Sinal de VENDA para {symbol} no timeframe {timeframe}: Preço atual: {current_price}"
                st.info(message)
                if notify_telegram:
                    await send_telegram_message(message)

            await asyncio.sleep(60)  # Aguarda 60 segundos antes de verificar novamente

# Configuração do Streamlit
st.title("Robô de Notificação para Criptomoedas")
st.write("O sistema utiliza uma combinação de indicadores técnicos para gerar sinais de compra e venda.")

# Entrada do usuário
all_symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "DOTUSDT", "DOGEUSDT", "FTMUSDT", "ASTRUSDT", "XRPUSDT", "SOLUSDT", 
               "LTCUSDT", "PENDLEUSDT", "AAVEUSDT", "ORDIUSDT", "UNIUSDT", "LINKUSDT", 
               "ENSUSDT", "MOVRUSDT", "ARBUSDT", "TRBUSDT", "MANTAUSDT", "AVAXUSDT", "NEIROUSDT","ADAUSDT","GALAUSDT"]

select_all = st.sidebar.checkbox("Selecionar todos os pares")
symbols = st.sidebar.multiselect("Selecione os pares de moedas", all_symbols, default=all_symbols if select_all else [])
timeframes = st.sidebar.multiselect("Selecione o(s) timeframe(s)", ["1m", "5m", "15m", "1h", "4h", "1d"])
notify_telegram = st.sidebar.checkbox("Enviar notificações no Telegram", value=False)

if st.sidebar.button("Iniciar Monitoramento"):
    if not symbols:
        st.error("Por favor, selecione pelo menos um par de moedas.")
    elif not timeframes:
        st.error("Por favor, selecione pelo menos um timeframe.")
    else:
        st.success("Monitoramento iniciado! Acompanhe os alertas abaixo.")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        tasks = [notify_conditions(symbol, timeframes, notify_telegram) for symbol in symbols]
        loop.run_until_complete(asyncio.gather(*tasks))
