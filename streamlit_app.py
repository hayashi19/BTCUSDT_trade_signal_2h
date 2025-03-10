import streamlit as st
import re
from typing import Callable, Optional, NoReturn, Dict, List, Any, Tuple
from time import sleep
import time
from datetime import datetime
from logging import Logger, StreamHandler, FileHandler, getLogger, basicConfig, INFO
from configparser import ConfigParser

from pickle import load, dump
from pandas import DataFrame, Index, concat, to_datetime
from numpy import ndarray, dtype, float64, zeros, argmax
from tensorneat import algorithm, common, problem, pipeline, genome
import plotly.graph_objects as go
import json

from binance.spot import Spot

start_time: datetime = datetime.now()
current_time: datetime = datetime.now()
timeout: int = 0
MICRO_SECOND_TO_SECOND: int = 60000000

basicConfig(
    level=INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        StreamHandler(),
        # FileHandler(filename=r"app.log", mode="a", encoding="utf-8"),
    ],
)
logger: Logger = getLogger(__name__)

st.set_page_config(layout="wide")

st.write("""
# Trading Sinyal
""")

col1, col2 = st.columns(2)

# key_text = col2.text_input("Key", value="bOENK3pXGYwIAomerhj4RMF9TdZfdUH8v7gZ7npP1OtwKaSfU8onoXfBY29g4D7i")
# secrete_text = col2.text_input("Secrete", value="ml7mpBdJFXupOI2LUcYNDUz8uKsl9bYzliveakp32wU3glqxTSvCOKhzpzBmf2wA")

# spot: Spot = Spot(api_key=key_text, api_secret=secrete_text)

spot: Spot = Spot()

# KLINES DATA
# symbol= col2.selectbox("Symbol", ["BTCUSDT"], index=0)
symbol= "BTCUSDT"
interval="2h"
limit=48

def get_klines(symbol="BTCUSDT", interval="1m", limit=48) -> DataFrame:
    logger.info(f"📁 Get {limit} klines data of {symbol} at {interval} timeframe.")
    try:
        data: Any = spot.klines(
            symbol=symbol, interval=interval, limit=limit)
        data_df: DataFrame = DataFrame(data)
        data_df.columns = data_df.columns = Index([
            "open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume", "ignore"
        ])
        data_df.drop(columns=["close_time",
                                "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
                                "taker_buy_quote_asset_volume", "ignore"], inplace=True)
        float_columns = ["open", "high", "low", "close", "volume"]
        data_df[float_columns] = data_df[float_columns].astype(float)

        return data_df
    except Exception as e:
        logger.error(f"🛑 Function spot_get_klines: {e}")
        return DataFrame([])

def show(data_df: DataFrame, col) -> None:
    fig = go.Figure(data=[go.Candlestick(x=to_datetime(data_df['open_time']),
                open=data_df['open'],
                high=data_df['high'],
                low=data_df['low'],
                close=data_df['close'])])

    col.plotly_chart(figure_or_data=fig)

def __load_preprocess_config(path: str) -> Tuple[int, dict]:
        with open(path, "rb") as file:
            preprocess_config: tuple = load(file)
            print(preprocess_config)
            window_size: int = preprocess_config['min_max_dict']
            min_max_dict: dict = preprocess_config['window_size']
            logger.info(f"🛠️ Preprocess config loaded from {path}")
            return window_size, min_max_dict

def __process_technical_indicator(data: DataFrame) -> DataFrame:
    try:
        logger.info(f"🛠️ Process adding technical indicator ...")
        feature_df = data.copy()

        # """ STOCHASTIC OSCILLATOR """
        k_period = 14
        d_period = 3
        d_slow_period = 3
        feature_df['lowest_low'] = feature_df['low'].rolling(
            window=k_period).min()
        feature_df['highest_high'] = feature_df['high'].rolling(
            window=k_period).max()
        price_range = feature_df['highest_high'] - feature_df['lowest_low']
        feature_df['%K'] = 100 * \
            (feature_df['close'] - feature_df['lowest_low']) / price_range
        feature_df['%K'] = feature_df['%K'].where(price_range != 0, 0)
        feature_df['%D'] = feature_df['%K'].rolling(window=d_period).mean()
        feature_df['Slow %D'] = feature_df['%D'].rolling(
            window=d_slow_period).mean()
        feature_df = feature_df.drop(
            columns=['lowest_low', 'highest_high'])

        # """ MOMENTUM (MO) """
        momentum_period = 10
        feature_df['Momentum'] = feature_df['close'] - \
            feature_df['close'].shift(momentum_period)

        # """ RATE OF CHANGE (ROC) """
        roc_period = 10
        feature_df['ROC'] = (feature_df['close'] - feature_df['close'].shift(
            roc_period)) / feature_df['close'].shift(roc_period)

        # """ WILLIAMS %R """
        williams_r_period = 14
        feature_df['lowest_low'] = feature_df['low'].rolling(
            window=williams_r_period).min()
        feature_df['highest_high'] = feature_df['high'].rolling(
            window=williams_r_period).max()
        feature_df['Williams %R'] = -100 * (feature_df['highest_high'] - feature_df['close']) / (
            feature_df['highest_high'] - feature_df['lowest_low'])
        feature_df['Williams %R'] = feature_df['Williams %R'].where(
            price_range != 0, 0)
        feature_df = feature_df.drop(
            columns=['lowest_low', 'highest_high'])

        # """ ACCUMULATION DISTRIBUTION OSCILLATOR (ADO) """
        ado_period = 1
        feature_df['ADO'] = (feature_df['high'] - feature_df['close'].shift(
            ado_period)) / (feature_df['high'] - feature_df['low'])
        feature_df['ADO'] = feature_df['ADO'].fillna(0)

        # """ DISPARITY INDEX """
        disparity_period = 14
        ma = feature_df['close'].rolling(window=disparity_period).mean()
        feature_df['Disparity Index'] = (
            (feature_df['close'] - ma) / ma) * 100

        # """ PRICE OSCILLATOR """
        short_period = 12
        long_period = 26
        short_ma = feature_df['close'].rolling(window=short_period).mean()
        long_ma = feature_df['close'].rolling(window=long_period).mean()
        feature_df['Price Oscillator'] = (
            (short_ma - long_ma) / long_ma) * 100

        # """ VOLUME OSCILLATOR """
        vol_short_period = 14
        vol_long_period = 28
        feature_df['volume_adjusted'] = feature_df['volume'].replace(
            0, 0.0001)
        vol_short_ma = feature_df['volume_adjusted'].rolling(
            window=vol_short_period).mean()
        vol_long_ma = feature_df['volume_adjusted'].rolling(
            window=vol_long_period).mean()
        feature_df['Volume Oscillator'] = (
            (vol_short_ma - vol_long_ma) / vol_long_ma) * 100
        feature_df = feature_df.drop(columns=['volume_adjusted'])

        # """ AROON OSCILLATOR """
        aroon_period = 14
        rolling_high = feature_df['high'].rolling(window=aroon_period + 1)
        rolling_low = feature_df['low'].rolling(window=aroon_period + 1)
        high_days = aroon_period - \
            rolling_high.apply(lambda x: x.argmax() if len(x) > 0 else 0)
        low_days = aroon_period - \
            rolling_low.apply(lambda x: x.argmin() if len(x) > 0 else 0)
        feature_df['Aroon Up'] = (high_days / aroon_period) * 100
        feature_df['Aroon Down'] = (low_days / aroon_period) * 100
        feature_df['Aroon Oscillator'] = feature_df['Aroon Up'] - \
            feature_df['Aroon Down']
        feature_df = feature_df.drop(columns=['Aroon Up', 'Aroon Down'])

        # """ RELATIVE STRENGTH INDEX """
        rsi_period = 14
        delta = feature_df['close'].diff().astype(float)
        gain = (delta.where(delta > 0, 0))
        loss = (-delta.where(delta < 0, 0))
        avg_gain = gain.rolling(window=rsi_period).mean()
        avg_loss = loss.rolling(window=rsi_period).mean()
        avg_loss = avg_loss.replace(0, 0.0001)
        rs = avg_gain / avg_loss
        feature_df['RSI'] = 100 - (100 / (1 + rs))
        is_flat = (avg_gain < 0.0001) & (avg_loss < 0.0001)
        feature_df.loc[is_flat, 'RSI'] = 50

        # """ MACD (Moving Average Convergence Divergence) """
        fast_period = 12
        slow_period = 26
        ema_fast = feature_df['close'].ewm(
            span=fast_period, adjust=False).mean()
        ema_slow = feature_df['close'].ewm(
            span=slow_period, adjust=False).mean()
        feature_df['MACD'] = ema_fast - ema_slow

        feature_df.dropna(inplace=True)
        feature_df.reset_index(drop=True, inplace=True)

        return feature_df
    except Exception as e:
        logger.error(f"🛑 Function process_technical_indicator: {e}", exc_info=True)
        return DataFrame([])

def __min_max_scale(data: DataFrame, feature_range: tuple = (-1, 1), min_max_dict: Optional[dict] = None) -> Tuple[DataFrame, Optional[dict]]:
    try:
        logger.info(f"🛠️ Process min max normalization ...")
        if min_max_dict is None:
            min_max_dict = {}

        target_min, target_max = feature_range
        normalized_df = data.copy()

        for column in data.columns:
            if column in min_max_dict:
                col_min = min_max_dict[column]['min']
                col_max = min_max_dict[column]['max']
            else:
                col_min = data[column].min()
                col_max = data[column].max()
                min_max_dict[column] = {'min': col_min, 'max': col_max}

            normalized_df[column] = (
                (data[column] - col_min) / (col_max - col_min)) * (target_max - target_min) + target_min
        return normalized_df, min_max_dict
    except Exception as e:
        logger.error(f"🛑 Function min_max_scale: {e}", exc_info=True)
        return DataFrame([]), None

def __sliding_window(data: DataFrame, window_size: int) -> DataFrame:
    try:
        logger.info(f"🛠️ Process sliding window ...")
        windows_df = DataFrame()

        i = 0

        while i < window_size:
            shifted_df = data.shift(i)
            shifted_df.columns = Index(
                [f"{col}.{i}" for col in data.columns])
            windows_df = concat([windows_df, shifted_df], axis=1)
            i += 1
        return windows_df
    except Exception as e:
        logger.error(f"🛑 Function sliding_window: {e}", exc_info=True)
        return DataFrame([])

def __preprocess(data: DataFrame) -> DataFrame:
    try:
        logger.info(f"🛠️ Preprocessing ...")

        data_temp: DataFrame = data.copy()
        feature_df = __process_technical_indicator(data_temp)
        feature_df.drop(columns=["open_time", "open", "high", "low", "close", "volume"], inplace=True)

        min_max_dict, window_size = __load_preprocess_config(fr"BTCUSDT_scaler.pkl")

        norm_df, _ = __min_max_scale(data=feature_df, min_max_dict=min_max_dict)
        wind_df = __sliding_window(data=norm_df, window_size=window_size)
        return wind_df
    except Exception as e:
        logger.error(f"🛑 Function preprocess: {e}", exc_info=True)
        return DataFrame(zeros(26))

def __load_model(path: str) -> tuple[algorithm.NEAT, common.state.State, tuple]:
    with open(path, "rb") as file:
        neat_config: tuple = load(file)
        neat_algorithm: algorithm.NEAT = neat_config[0]
        state: common.state.State = neat_config[1]
        best_genome: tuple = neat_config[2]
        logger.info(f"🛠️ Model loaded from {path}")
        return neat_algorithm, state, best_genome
    
def predict(input: DataFrame) -> int:
    try:
        neat_algorithm, state, best_genome = __load_model(fr"model_42_19-08-2017_31-12-2023.pkl")
        
        genome_transformed: Tuple = neat_algorithm.genome.transform(
            state=state,
            nodes=best_genome[0],
            conns=best_genome[1]
        )

        outputs: list = neat_algorithm.genome.forward(state, genome_transformed, input.values.flatten())
        output: int = argmax(outputs).item()

        logger.info(f"🎯 Output: {output}")
        return output
    except Exception as e:
        logger.error(f"🛑 Prediction error: {str(e)}", exc_info=True)
        return 0

def write_history_trade(history_data):
    file_path = "trade_history.json"  # Adjust if needed

    try:
        # Read existing data
        with open(file_path, "r") as file:
            current_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        # If file is missing or empty, start fresh
        current_data = []

    # Assign a new ID (increment from last entry or start at 1)
    history_data["id"] = current_data[-1]["id"] + 1 if current_data else 1

    # Append the new trade
    current_data.append(history_data)

    # Write back to the file
    with open(file_path, "w") as file:
        json.dump(current_data, file, indent=4)

def read_history_trade():
    file_path = "trade_history.json"
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def __buy(price: float):
    st.info(f"BUY ${price}")

def __sell(price: float):
    st.info(f"SELL ${price}")

def trade_execution(action: int, data: DataFrame):
    if action == 1:
        __buy(data["close"].values[-1])
        write_history_trade({
            "action": "BUY",
            "price": float(data["close"].values[-1]),
            "date": str(data["open_time"].values[-1]),
            "symbol": "BTCUSDT"
        })
    elif action == 2:
        __sell(data["close"].values[-1])
        write_history_trade({
            "action": "SELL",
            "price": float(data["close"].values[-1]),
            "date": str(data["open_time"].values[-1]),
            "symbol": "BTCUSDT"
        })

def simulate():
    data: DataFrame = get_klines(symbol=symbol, interval=interval, limit=limit)
    col1.write("### Raw Data")
    show(data_df=data, col=col1)
    
    data_processed = __preprocess(data=data)
    col2.write("### Inputs")
    col2.write(data_processed.tail(1))
    
    output = predict(data_processed.tail(1))
    col2.write("### Action")
    if output == 1:
        col2.write(f"Buy at ${data['close'].values[-1]}")
    elif output == 2:
        col2.write(f"Sell at ${data['close'].values[-1]}")
    else:
        col2.write(f"No trade at ${data['close'].values[-1]}")
    
    trade_execution(action=output, data=data)

if col1.button("Get Signal"):
    simulate()