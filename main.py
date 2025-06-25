import streamlit as st
import asyncio
import yfinance as yf
import pandas as pd
from ta.momentum import RSIIndicator
from dotenv import load_dotenv
import os
import requests

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Importando credenciais do Telegram
telegram_bot_token = os.getenv("telegram_bot_token")
telegram_chat_id = os.getenv("telegram_chat_id")

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
    """
    Busca dados OHLCV do Yahoo Finance via yfinance.
    symbol: string do ticker, ex: "BTC-USD"
    timeframe: string do intervalo, ex: "1m", "5m", "1d"
    """
    try:
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "1h": "60m",
            "4h": "4h",
            "1d": "1d",
        }
        yf_interval = interval_map.get(timeframe, "1d")

        # Ajustar período para download
        period = "7d" if yf_interval.endswith("m") else "60d"

        df = yf.download(tickers=symbol, period=period, interval=yf_interval, progress=False, auto_adjust=False)

        if df.empty:
            st.error(f"Nenhum dado retornado para {symbol} no timeframe {timeframe}")
            return None, None

        # Se MultiIndex, extrair apenas colunas do ticker
        if isinstance(df.columns, pd.MultiIndex):
            # Usar .xs para pegar só as colunas do ticker solicitado
            df = df.xs(symbol, axis=1, level=1, drop_level=True)

        # Renomear colunas para minúsculas
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        df = df.reset_index()

        # Criar colunas open_time e close_time para manter compatibilidade com lógica anterior
        if 'Datetime' in df.columns:
            df['open_time'] = df['Datetime']
        elif 'Date' in df.columns:
            df['open_time'] = df['Date']
        else:
            df['open_time'] = pd.to_datetime('now')

        df['close_time'] = df['open_time']

        current_price = df['close'].iloc[-1]

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

last_notifications = {}

async def notify_conditions(symbol, timeframes, notify_telegram, signal_choice):
    while True:
        for timeframe in timeframes:
            current_price, df = await fetch_ticker_and_candles(symbol, timeframe)
            if df is None:
                await asyncio.sleep(5)
                continue

            # Indicadores técnicos
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

            high_volume = df['volume'].iloc[-1] > 3 * volume_ma

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

# Adaptar símbolos para Yahoo Finance (exemplo: BTCUSDT -> BTC-USD)
all_symbols = [
    "BTC-USD", "ETH-USD", "BNB-USD", "DOT-USD", "DOGE-USD", "FTM-USD", "ASTR-USD", "XRP-USD", "SOL-USD",
    "LTC-USD", "PENDLE-USD", "AAVE-USD", "ORDI-USD", "UNI-USD", "LINK-USD",
    "ENS-USD", "MOVR-USD", "ARB-USD", "TRB-USD", "MANTA-USD", "AVAX-USD", "ADA-USD", "GALA-USD", "LDO-USD"
]

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
