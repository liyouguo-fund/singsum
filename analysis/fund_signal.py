"""
基金技术信号分析模块

计算技术指标并生成买卖信号：
- 移动平均线（MA5/MA10）信号
- RSI指标信号
- MACD指标信号
- CCI指标信号
- 布林带信号

从 fund_signal 项目迁移，重构为函数接口。
使用共享的 fund_fetcher 获取基金列表，使用统一的 logger。
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import time
import sys
import os
import random

warnings.filterwarnings('ignore')

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger
from core.fund_fetcher import get_funds_from_wencai

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def retry_api_call(func, max_retries=3, base_delay=1):
    """API调用重试"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"第{attempt+1}次尝试失败，{delay:.2f}秒后重试：{str(e)}")
                time.sleep(delay)
            else:
                logger.error(f"第{attempt+1}次尝试失败，放弃重试：{str(e)}")
                raise


def get_fund_data(fund_code="000001", prefetched_df=None, fund_name=None):
    """获取基金历史净值数据，带重试机制

    Args:
        fund_code: 基金代码
        prefetched_df: 预取数据 (date, nav, daily_return, fund_code)，为 None 则自行调用 API
        fund_name: 基金真实名称（来自问财）
    """
    try:
        logger.info(f"开始获取基金{fund_code}历史数据")

        # 处理基金代码，去掉.OF后缀
        if '.' in fund_code:
            fund_code = fund_code.split('.')[0]
        code = str(fund_code).zfill(6).split('.')[0]

        # ---- 使用预取数据 ----
        if prefetched_df is not None and not prefetched_df.empty:
            pdf = prefetched_df.copy()
            name = fund_name or f'基金{code}'
            history_df = pd.DataFrame({
                '净值日期': pd.to_datetime(pdf['date'], errors='coerce'),
                '最新净值': pd.to_numeric(pdf['nav'], errors='coerce'),
                '日增长率%': pd.to_numeric(pdf.get('daily_return', 0), errors='coerce'),
                '基金代码': code,
                '基金简称': name,
            })
            history_df = history_df.dropna(subset=['最新净值']).reset_index(drop=True)
            if not history_df.empty:
                logger.info(f"基金{code}使用预取数据，共{len(history_df)}条记录")
                return history_df

        # 尝试获取历史数据
        try:
            def get_history_data():
                return ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

            history_df = retry_api_call(get_history_data, max_retries=3, base_delay=1)

            if history_df is not None and not history_df.empty:
                fund_name = f"基金{fund_code}"
                history_df['基金代码'] = fund_code
                history_df['基金简称'] = fund_name
                history_df = history_df.rename(columns={
                    '单位净值': '最新净值',
                    '日增长率': '日增长率%'
                })
                history_df['日增长率%'] = pd.to_numeric(history_df['日增长率%'], errors='coerce')
                logger.info(f"基金{fund_code}历史数据获取成功，共{len(history_df)}条记录")
                return history_df
        except Exception as e:
            logger.error(f"获取基金{fund_code}历史数据失败：{str(e)}")
            logger.warning(f"基金{fund_code}尝试使用备选方案")

        # 备选方案
        def get_daily_data():
            return ak.fund_open_fund_daily_em()

        df = retry_api_call(get_daily_data, max_retries=3, base_delay=1)

        if df is None:
            logger.warning(f"基金数据返回为空")
            return None

        fund_data = df[df['基金代码'] == fund_code]
        if fund_data.empty:
            logger.warning(f"未找到基金{fund_code}的数据")
            return None

        unit_nav_col = [col for col in df.columns if '-单位净值' in col][0]
        unit_nav = fund_data.iloc[0][unit_nav_col]
        daily_growth = fund_data.iloc[0]['日增长率']
        latest_date = unit_nav_col.split('-')[0]

        history_data = pd.DataFrame({
            '净值日期': [pd.Timestamp(latest_date)],
            '最新净值': [float(unit_nav)],
            '日增长率%': [float(daily_growth)],
            '基金代码': [fund_code],
            '基金简称': [f"基金{fund_code}"]
        })

        logger.info(f"基金{fund_code}数据获取成功，共{len(history_data)}条记录")
        return history_data

    except Exception as e:
        logger.error(f"获取基金{fund_code}历史数据失败：{str(e)}")
        return None


def calculate_technical_indicators(df):
    """计算技术指标和信号"""
    if df is None or len(df) == 0:
        logger.warning("数据为空，无法计算技术指标")
        return df

    fund_code = df['基金代码'].iloc[0] if '基金代码' in df.columns else '未知'
    logger.info(f"开始计算基金{fund_code}技术指标")

    # 数据不足时生成基础信号
    if len(df) < 20:
        logger.info(f"基金{fund_code}数据不足20条，生成基础信号")
        df['均线信号'] = '持有'
        df['RSI'] = 50
        df['RSI信号'] = '持有'
        df['MACD'] = 0
        df['macd值'] = 0
        df['macd信号'] = '持有'
        df['cci值'] = 0
        df['cci信号'] = '持有'
        df['布林带中轨值'] = df['最新净值']
        df['布林带上轨值'] = df['最新净值'] * 1.1
        df['布林带下轨值'] = df['最新净值'] * 0.9
        df['布林带信号'] = '持有'
        return df

    # ---- 均线信号 ----
    df['MA5'] = df['最新净值'].rolling(window=5, min_periods=1).mean()
    df['MA10'] = df['最新净值'].rolling(window=10, min_periods=1).mean()
    df['均线信号'] = '持有'
    buy_signals = (df['MA5'] > df['MA10']) & (df['MA5'].shift(1) <= df['MA10'].shift(1))
    sell_signals = (df['MA5'] < df['MA10']) & (df['MA5'].shift(1) >= df['MA10'].shift(1))
    df.loc[buy_signals, '均线信号'] = '买入'
    df.loc[sell_signals, '均线信号'] = '卖出'

    # ---- RSI 信号 ----
    delta = df['最新净值'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
    rs = gain / loss
    df['RSI'] = (100 - (100 / (1 + rs))).round(2)
    df['RSI'] = df['RSI'].fillna(50)
    df['RSI信号'] = '持有'
    rsi_buy = (df['RSI'] > 30) & (df['RSI'].shift(1) <= 30)
    rsi_sell = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    rsi_opp = df['RSI'] < 30
    rsi_risk = df['RSI'] > 70
    df.loc[rsi_buy, 'RSI信号'] = '买入'
    df.loc[rsi_sell, 'RSI信号'] = '卖出'
    df.loc[rsi_opp, 'RSI信号'] = '机会买入'
    df.loc[rsi_risk, 'RSI信号'] = '提示风险'

    # ---- MACD 信号 ----
    exp1 = df['最新净值'].ewm(span=12, adjust=False).mean()
    exp2 = df['最新净值'].ewm(span=26, adjust=False).mean()
    df['MACD'] = (exp1 - exp2).round(4)
    df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['macd值'] = df['MACD']
    df['macd信号'] = '持有'
    macd_buy = (df['MACD'] > -100) & (df['MACD'].shift(1) <= -100)
    macd_sell = (df['MACD'] < 100) & (df['MACD'].shift(1) >= 100)
    df.loc[macd_buy, 'macd信号'] = '买入'
    df.loc[macd_sell, 'macd信号'] = '卖出'

    # ---- CCI 信号 ----
    tp = df['最新净值']
    tp_ma = tp.rolling(window=20, min_periods=1).mean()
    md = tp.rolling(window=20, min_periods=1).apply(lambda x: np.mean(np.abs(x - np.mean(x))))
    df['cci值'] = ((tp - tp_ma) / (0.015 * md)).round(2)
    df['cci值'] = df['cci值'].fillna(0)
    df['cci信号'] = '持有'
    cci_buy = (df['cci值'] > -100) & (df['cci值'].shift(1) <= -100)
    cci_sell = (df['cci值'] < 100) & (df['cci值'].shift(1) >= 100)
    cci_opp = df['cci值'] < -100
    cci_risk = df['cci值'] > 100
    df.loc[cci_buy, 'cci信号'] = '买入'
    df.loc[cci_sell, 'cci信号'] = '卖出'
    df.loc[cci_opp, 'cci信号'] = '机会买入'
    df.loc[cci_risk, 'cci信号'] = '提示风险'

    # ---- 布林带信号 ----
    df['布林带中轨值'] = df['最新净值'].rolling(window=20, min_periods=1).mean()
    bb_std = df['最新净值'].rolling(window=20, min_periods=1).std()
    df['布林带上轨值'] = (df['布林带中轨值'] + 2 * bb_std).round(4)
    df['布林带下轨值'] = (df['布林带中轨值'] - 2 * bb_std).round(4)
    df['布林带信号'] = '持有'
    bb_buy_opp = df['最新净值'] < df['布林带下轨值']
    bb_risk = df['最新净值'] > df['布林带上轨值']
    bb_cross_buy = (df['最新净值'] > df['布林带下轨值']) & (df['最新净值'].shift(1) <= df['布林带下轨值'].shift(1))
    bb_cross_sell = (df['最新净值'] < df['布林带上轨值']) & (df['最新净值'].shift(1) >= df['布林带上轨值'].shift(1))
    df.loc[bb_buy_opp, '布林带信号'] = '机会买入'
    df.loc[bb_risk, '布林带信号'] = '提示风险'
    df.loc[bb_cross_buy, '布林带信号'] = '买入'
    df.loc[bb_cross_sell, '布林带信号'] = '卖出'

    logger.info(f"基金{fund_code}技术指标计算完成")
    return df


def create_signal_table(df, fund_code, report_date=None):
    """创建信号明细表格"""
    if df is None or len(df) == 0:
        logger.warning(f"基金{fund_code}数据为空")
        return pd.DataFrame()

    if report_date is None:
        report_date = datetime.now().strftime('%Y-%m-%d')

    required_columns = [
        '基金代码', '基金简称', '投资类型', '净值日期',
        '均线信号', 'RSI', 'RSI信号', 'cci值', 'cci信号',
        'macd值', 'macd信号', '布林带下轨值', '布林带中轨值',
        '布林带上轨值', '布林带信号'
    ]

    existing_columns = [col for col in required_columns if col in df.columns]
    output_df = df[existing_columns].copy()

    if '净值日期' in output_df.columns:
        output_df['净值日期'] = pd.to_datetime(output_df['净值日期'], errors='coerce')
        output_df['净值日期'] = output_df['净值日期'].dt.strftime('%Y-%m-%d')

    output_df['报告日期'] = report_date

    return output_df


def show_progress(current, total, start_time, prefix="分析进度"):
    """显示分析进度"""
    elapsed_time = time.time() - start_time
    progress = current / total * 100

    if current > 0:
        remaining_time = (elapsed_time / current) * (total - current)
        time_str = f"预计剩余: {remaining_time:.1f}秒"
    else:
        time_str = ""

    sys.stdout.write(f"\r{prefix}: {current}/{total} ({progress:.1f}%) {time_str}")
    sys.stdout.flush()


def run_fund_signal_analysis(days_to_keep=10, fund_codes=None, wencai_query=None,
                             prefetched_data=None, fund_name_map=None) -> dict:
    """运行基金技术信号分析（主入口）

    Args:
        days_to_keep: 保留数据天数
        fund_codes: 基金代码列表，None 则从问财获取
        wencai_query: 问财查询语句
        prefetched_data: 预取的历史数据 {fund_code: DataFrame(date, nav, daily_return, fund_code)}
        fund_name_map: 基金代码→名称映射 {fund_code: fund_name}

    Returns:
        dict: {'csv_path', 'excel_path', 'dataframe', 'results', 'success'}
    """
    report_date = datetime.now().strftime('%Y-%m-%d')

    logger.info("=" * 80)
    logger.info("基金技术信号分析开始")
    logger.info(f"报告日期：{report_date}，保留天数：{days_to_keep}")
    logger.info("=" * 80)

    # 获取基金列表
    wencai_fund_data = None

    if fund_codes is None:
        if wencai_query:
            wencai_fund_data = get_funds_from_wencai(wencai_query)
        else:
            wencai_fund_data = get_funds_from_wencai()

        if wencai_fund_data is not None:
            fund_codes = wencai_fund_data['基金代码'].tolist()
            logger.info(f"从问财获取到 {len(fund_codes)} 个基金")
        else:
            logger.error("问财未返回有效基金列表")
            return {'csv_path': None, 'excel_path': None, 'results': [], 'success': False}

    if not fund_codes:
        logger.error("基金列表为空")
        return {'csv_path': None, 'excel_path': None, 'results': [], 'success': False}

    logger.info(f"待分析基金：{len(fund_codes)} 个")

    # 创建输出目录
    output_dir = os.path.join(PROJECT_ROOT, 'output')
    os.makedirs(output_dir, exist_ok=True)

    csv_filename = os.path.join(output_dir, f'信号明细_{report_date}.csv')
    excel_filename = os.path.join(output_dir, f'信号明细_{report_date}.xlsx')

    results = []
    first_write = True
    start_time = time.time()

    for i, fund_code in enumerate(fund_codes, 1):
        show_progress(i, len(fund_codes), start_time, "分析进度")

        try:
            # 获取数据（优先使用预取数据 + 问财真实名称）
            pdf = prefetched_data.get(fund_code) if prefetched_data else None
            real_name = fund_name_map.get(fund_code) if fund_name_map else None
            fund_df = get_fund_data(fund_code, prefetched_df=pdf, fund_name=real_name)
            if fund_df is None:
                logger.warning(f"基金{fund_code}数据获取失败，跳过")
                continue

            # 计算技术指标
            fund_df = calculate_technical_indicators(fund_df)

            # 计算买点2/买点5策略信号
            buy2, buy5 = False, False
            try:
                strat_df = calculate_strategy_indicators(
                    fund_df[['净值日期', '最新净值']].rename(
                        columns={'净值日期': 'date', '最新净值': 'nav'})
                )
                if not strat_df.empty:
                    latest_s = strat_df.iloc[-1]
                    buy2 = bool(latest_s.get('buy_signal_2', False))
                    buy5 = bool(latest_s.get('buy_signal_5', False))
            except Exception:
                pass

            # 创建信号表格
            signal_df = create_signal_table(fund_df, fund_code, report_date)
            signal_df['买点2信号'] = '买入' if buy2 else '—'
            signal_df['买点5信号'] = '买入' if buy5 else '—'

            # 过滤近N天数据
            if '净值日期' in signal_df.columns:
                signal_df['净值日期'] = pd.to_datetime(signal_df['净值日期'])
                max_date = signal_df['净值日期'].max()
                cutoff_date = max_date - pd.Timedelta(days=days_to_keep)
                signal_df = signal_df[signal_df['净值日期'] >= cutoff_date]
                signal_df['净值日期'] = signal_df['净值日期'].dt.strftime('%Y-%m-%d')

            # 从问财数据更新基金简称、投资类型、持仓概念等
            if wencai_fund_data is not None:
                fund_info = wencai_fund_data[wencai_fund_data['基金代码'] == fund_code]
                if not fund_info.empty:
                    if '基金简称' in fund_info.columns:
                        signal_df['基金简称'] = fund_info['基金简称'].iloc[0]
                    if '投资类型' in fund_info.columns:
                        signal_df['投资类型'] = fund_info['投资类型'].iloc[0]
                    # 同步问财返回的 持仓/概念 等额外字段
                    extra_cols = [c for c in wencai_fund_data.columns
                                  if '持仓' in c or '概念' in c or '主题' in c or '板块' in c]
                    for col in extra_cols:
                        signal_df[col] = fund_info[col].iloc[0]

            # 添加基金名称
            fund_name = fund_df['基金简称'].iloc[0] if '基金简称' in fund_df.columns else f'基金{fund_code}'

            results.append({
                'fund_code': fund_code,
                'fund_name': fund_name,
                'signal_data': signal_df,
            })

            # 写入CSV（增量写入）
            if first_write:
                signal_df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
                first_write = False
            else:
                signal_df.to_csv(csv_filename, index=False, encoding='utf-8-sig', mode='a', header=False)

            # 写入Excel（全量更新）
            try:
                if os.path.exists(excel_filename):
                    with pd.ExcelFile(excel_filename, engine='openpyxl') as xls:
                        existing_df = pd.read_excel(xls, sheet_name='信号明细')
                    combined_df = pd.concat([existing_df, signal_df], ignore_index=True)
                else:
                    combined_df = signal_df

                with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
                    combined_df.to_excel(writer, sheet_name='信号明细', index=False)
            except Exception as e:
                logger.error(f"写入Excel失败：{str(e)}")

        except Exception as e:
            logger.error(f"分析基金{fund_code}失败：{str(e)}")

        # 避免请求过快
        time.sleep(random.uniform(1, 1.5))

    elapsed_time = time.time() - start_time
    sys.stdout.write("\n")

    logger.info("=" * 80)
    logger.info(f"信号分析完成！成功：{len(results)}/{len(fund_codes)}，耗时：{elapsed_time:.1f}秒")
    logger.info("=" * 80)

    # 构建统一 DataFrame（从已生成的 CSV 读取，确保数据完整）
    signal_df = pd.DataFrame()
    if csv_filename and os.path.exists(csv_filename):
        try:
            signal_df = pd.read_csv(csv_filename, encoding='utf-8-sig')
            logger.info(f"从 CSV 读取信号数据：{len(signal_df)} 条记录")
        except Exception as e:
            logger.warning(f"读取信号 CSV 失败：{e}")

    return {
        'csv_path': csv_filename if results else None,
        'excel_path': excel_filename if results else None,
        'dataframe': signal_df,
        'results': results,
        'success': len(results) > 0,
    }


# ════════════════════════════════════════════════════════════════════
# 买点2(稳健型) + 买点5(平衡型) 策略
# ════════════════════════════════════════════════════════════════════

def calculate_strategy_indicators(df):
    """计算买点2/买点5策略所需指标（复用信号分析的净值数据）

    需要列: date, nav (来自 最新净值)
    新增列:
        trend_line_wma6, trend_line_wma10, deviation_s, ma10, ma20, ma30, ma60,
        ma_bullish, ma_bearish, trend_slope_short, trend_slope_medium,
        uptrend_strict, uptrend_early, uptrend, sideways, dev_cci,
        buy_signal_2, buy_signal_5, sell_stop_loss, sell_take_profit, sell_ma_bearish
    """
    df = df.copy()
    nav = df['nav'].values

    # WMA6 趋势线（权重 6,5,4,3,2,1）
    w6 = np.array([6, 5, 4, 3, 2, 1])
    def _wma6(x):
        n = len(x)
        w = np.arange(n, 0, -1) if n < 6 else w6
        return np.sum(w * x) / w.sum()
    df['trend_line_wma6'] = df['nav'].rolling(6).apply(_wma6, raw=True)

    # WMA10
    w10 = np.arange(10, 0, -1)
    def _wma10(x):
        n = len(x)
        w = np.arange(n, 0, -1) if n < 10 else w10
        return np.sum(w * x) / w.sum()
    df['trend_line_wma10'] = df['nav'].rolling(10).apply(_wma10, raw=True)

    # 偏离率（基于 WMA6）
    df['deviation_s'] = (df['nav'] - df['trend_line_wma6']) / df['trend_line_wma6'] * 100

    # 均线
    df['ma10'] = nav_series = df['nav'].rolling(10).mean()
    df['ma20'] = df['nav'].rolling(20).mean()
    df['ma30'] = df['nav'].rolling(30).mean()
    df['ma60'] = df['nav'].rolling(60).mean()

    # 多/空头
    df['ma_bullish'] = (df['ma10'] > df['ma20']) & (df['ma20'] > df['ma30']) & (df['ma30'] > df['ma60'])
    df['ma_bearish'] = (df['ma10'] < df['ma20']) & (df['ma20'] < df['ma30']) & (df['ma30'] < df['ma60'])

    # 斜率
    df['trend_slope_short'] = df['ma10'].diff(5)
    df['trend_slope_medium'] = df['ma20'].diff(10)

    # 上升趋势
    df['uptrend_strict'] = (df['ma20'] > df['ma60']) & (df['trend_slope_medium'] > 0)
    df['uptrend_early'] = (df['ma10'] > df['ma20']) & (df['trend_slope_short'] > 0)
    df['uptrend'] = df['uptrend_strict'] | df['uptrend_early']

    # 震荡市场（买点5 需要）
    ma_range = (df['ma10'] - df['ma60']).abs() / df['ma60'].abs()
    df['ma_converged'] = ma_range < 0.08
    df['slope_unstable'] = df['trend_slope_short'].abs() < df['nav'].rolling(20).std() * 0.15
    df['dev_volatility_low'] = df['deviation_s'].rolling(20).std() < 5
    df['sideways'] = df['ma_converged'] & df['slope_unstable'] & df['dev_volatility_low']

    # CCI（偏离率版）
    sma_dev = df['deviation_s'].rolling(20).mean()
    mad_dev = df['deviation_s'].rolling(20).apply(lambda x: np.abs(x - x.mean()).mean())
    df['dev_cci'] = (df['deviation_s'] - sma_dev) / (0.015 * mad_dev)

    # 偏离率前一日
    dev_prev = df['deviation_s'].shift(1)

    # ── 买点2(稳健型)：均线多头 + 偏离率上穿5% + 上升趋势 ──
    df['buy_signal_2'] = (
        df['ma_bullish'] &
        (df['deviation_s'] > 5) & (dev_prev <= 5) &
        df['uptrend']
    )

    # ── 买点5(平衡型)：均线多头 + 偏离率金叉4% + 偏离率上升 + CCI>-50 ──
    df['buy_signal_5_uptrend'] = (
        df['ma_bullish'] & df['uptrend'] &
        (df['deviation_s'] > 4) & (dev_prev <= 4) &
        (df['deviation_s'] > dev_prev) & (df['dev_cci'] > -50)
    )
    df['buy_signal_5_sideways'] = (
        df['sideways'] &
        (df['deviation_s'] > 5) & (dev_prev <= 5) &
        (df['deviation_s'] > dev_prev) & (df['dev_cci'] > 0)
    )
    df['buy_signal_5'] = df['buy_signal_5_uptrend'] | df['buy_signal_5_sideways']

    # 卖出条件（两策略共用）
    df['sell_stop_loss'] = df['deviation_s'] < -5
    df['sell_take_profit'] = df['deviation_s'] > 10
    df['sell_ma_bearish'] = df['ma10'] < df['ma20']

    return df


def backtest_strategy(df, signal_col='buy_signal_2', max_hold=120):
    """回测策略

    Args:
        df: 含 buy/sell 信号的 DataFrame
        signal_col: 'buy_signal_2' 或 'buy_signal_5'
        max_hold: 最长持有天数

    Returns:
        list[dict]: 每笔交易 {buy_date, sell_date, buy_price, sell_price, return_pct, sell_reason, holding_days}
    """
    trades = []
    buy_mask = df[signal_col] == True
    if not buy_mask.any():
        return trades

    buy_indices = df[buy_mask].index.tolist()

    for buy_idx in buy_indices:
        buy_pos = df.index.get_loc(buy_idx)
        buy_price = df.loc[buy_idx, 'nav']
        buy_date = df.loc[buy_idx, 'date']

        sell_price = None
        sell_date = None
        sell_reason = None
        holding_days = 0

        for i in range(buy_pos + 1, len(df)):
            cur = df.iloc[i]
            holding_days = i - buy_pos

            if cur['sell_stop_loss']:
                sell_price = cur['nav']; sell_date = cur['date']; sell_reason = '止损'; break
            if cur['sell_take_profit']:
                sell_price = cur['nav']; sell_date = cur['date']; sell_reason = '止盈'; break
            if cur['sell_ma_bearish']:
                sell_price = cur['nav']; sell_date = cur['date']; sell_reason = '趋势退出'; break
            if holding_days >= max_hold:
                sell_price = cur['nav']; sell_date = cur['date']; sell_reason = '到期退出'; break

        if sell_price is None:
            continue

        trades.append({
            'buy_date': buy_date, 'sell_date': sell_date,
            'buy_price': buy_price, 'sell_price': sell_price,
            'return_pct': (sell_price - buy_price) / buy_price * 100,
            'sell_reason': sell_reason, 'holding_days': holding_days,
        })
    return trades


def strategy_summary(trades):
    """策略回测汇总统计"""
    if not trades:
        return {'total': 0, 'win_rate': 0, 'avg_return': 0, 'max_return': 0,
                'min_return': 0, 'avg_hold': 0, 'stop_loss': 0, 'take_profit': 0,
                'trend_exit': 0, 'expire': 0, 'wins': 0, 'losses': 0}

    td = pd.DataFrame(trades)
    wins = (td['return_pct'] > 0).sum()
    return {
        'total': len(td), 'wins': int(wins), 'losses': int(len(td) - wins),
        'win_rate': wins / len(td) * 100,
        'avg_return': td['return_pct'].mean(),
        'max_return': td['return_pct'].max(),
        'min_return': td['return_pct'].min(),
        'avg_hold': td['holding_days'].mean(),
        'stop_loss': int((td['sell_reason'] == '止损').sum()),
        'take_profit': int((td['sell_reason'] == '止盈').sum()),
        'trend_exit': int((td['sell_reason'] == '趋势退出').sum()),
        'expire': int((td['sell_reason'] == '到期退出').sum()),
    }


def run_strategy_analysis(fund_code, fund_name, nav_df):
    """对单只基金运行买点2+买点5策略分析

    Args:
        fund_code: 基金代码
        fund_name: 基金名称
        nav_df: 含 (date, nav) 列的 DataFrame

    Returns:
        dict: {
            'fund_code', 'fund_name',
            'latest_deviation_s', 'latest_ma_bullish', 'latest_uptrend',
            'buy2_signal', 'buy5_signal',
            'buy2_summary': {...}, 'buy5_summary': {...},
        }
    """
    if nav_df is None or len(nav_df) < 60:
        return {'fund_code': fund_code, 'fund_name': fund_name,
                'error': '数据不足(需要至少60条)'}

    df = calculate_strategy_indicators(nav_df[['date', 'nav']].copy())

    latest = df.iloc[-1]

    # 回测
    trades2 = backtest_strategy(df, 'buy_signal_2')
    trades5 = backtest_strategy(df, 'buy_signal_5')

    return {
        'fund_code': fund_code,
        'fund_name': fund_name,
        'latest_deviation_s': latest.get('deviation_s', 0),
        'latest_ma_bullish': bool(latest.get('ma_bullish', False)),
        'latest_uptrend': bool(latest.get('uptrend', False)),
        'latest_dev_cci': latest.get('dev_cci', 0),
        'buy2_signal': bool(latest.get('buy_signal_2', False)),
        'buy5_signal': bool(latest.get('buy_signal_5', False)),
        'buy2_summary': strategy_summary(trades2),
        'buy5_summary': strategy_summary(trades5),
    }


def strategy_results_to_dataframe(results):
    """将策略分析结果转为 DataFrame"""
    rows = []
    for r in results:
        if 'error' in r:
            continue
        b2 = r.get('buy2_summary', {})
        b5 = r.get('buy5_summary', {})
        rows.append({
            '基金代码': r['fund_code'],
            '基金名称': r['fund_name'],
            '偏离率(WMA6)': round(r.get('latest_deviation_s', 0), 2),
            '均线多头': '是' if r.get('latest_ma_bullish') else '否',
            '上升趋势': '是' if r.get('latest_uptrend') else '否',
            '买点2信号': '★买入' if r.get('buy2_signal') else '—',
            '买点5信号': '★买入' if r.get('buy5_signal') else '—',
            '买点2_交易次数': b2.get('total', 0),
            '买点2_胜率(%)': round(b2.get('win_rate', 0), 1),
            '买点2_平均收益(%)': round(b2.get('avg_return', 0), 2),
            '买点5_交易次数': b5.get('total', 0),
            '买点5_胜率(%)': round(b5.get('win_rate', 0), 1),
            '买点5_平均收益(%)': round(b5.get('avg_return', 0), 2),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='基金技术信号分析')
    parser.add_argument('--days', type=int, default=10, help='保留数据天数')
    parser.add_argument('--funds', type=str, help='基金代码列表，逗号分隔')
    parser.add_argument('--wencai', type=str, help='问财查询语句')
    args = parser.parse_args()

    fund_codes = None
    if args.funds:
        fund_codes = args.funds.split(',')

    run_fund_signal_analysis(
        days_to_keep=args.days,
        fund_codes=fund_codes,
        wencai_query=args.wencai
    )
