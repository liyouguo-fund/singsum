"""
宽基指数趋势大模型 - EMA版本

指标计算（使用EMA指数移动平均）：
- 趋势线: (最高价 + 最低价) / 2 的20日指数移动平均(EMA)
- 偏离率: (现价 - 趋势线) / 趋势线 × 100%
- 强度排序: 按偏离率数值排序，数值最大=1（最强）

数据源：统一使用 akshare
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger


# 默认分析指数列表（code 用于 akshare, prefix 区分指数/ETF）
# 指数代码格式: 'sh000001' (无点), ETF代码格式: '510050' (纯数字)
DEFAULT_INDICES = [
    # A股主要指数（stock_zh_index_daily）
    ('sh000001', '上证指数', 'index'),
    ('sz399001', '深证成指', 'index'),
    ('sz399006', '创业板指', 'index'),

    # 宽基ETF（fund_etf_hist_em）
    ('510050', '上证50', 'etf'),
    ('510300', '沪深300', 'etf'),
    ('510500', '中证500', 'etf'),
    ('512100', '中证1000', 'etf'),
    ('563300', '国证2000', 'etf'),

    # 风格/策略ETF
    ('159949', '创业板50', 'etf'),
    ('159967', '创成长', 'etf'),
    ('588000', '科创50', 'etf'),
    ('588220', '科创100', 'etf'),
    ('512890', '红利低波', 'etf'),

    # 跨境ETF（QDII）
    ('159920', '恒生ETF', 'etf'),
    ('513130', '恒生科技', 'etf'),
    ('513100', '纳指', 'etf'),
    ('513030', '德国', 'etf'),
    ('513520', '日经', 'etf'),
    ('513310', '中韩半导体', 'etf'),
    ('164824', '印度基金', 'etf'),

    # 商品ETF
    ('518880', '黄金', 'etf'),
    ('161226', '白银', 'etf'),
    ('159985', '豆粕', 'etf'),
    ('162411', '华宝油气', 'etf'),
]


def get_stock_data(stock_code: str, code_type: str = 'etf', days: int = 100,
                   end_date: str = None) -> pd.DataFrame:
    """获取股票/指数/ETF 历史数据（统一使用 akshare，多数据源 fallback）

    Args:
        stock_code: 代码（指数如 'sh000001'，ETF如 '510050'）
        code_type: 'index' 或 'etf'
        days: 获取天数
        end_date: 截止日期

    Returns:
        DataFrame: 标准化列名 date, open, high, low, close, volume
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days + 30)).strftime('%Y-%m-%d')

    df = None
    errors = []

    # ---- 数据源1: stock_zh_index_daily（指数，也支持部分ETF） ----
    try:
        raw = ak.stock_zh_index_daily(symbol=stock_code)
        if raw is not None and not raw.empty and 'close' in raw.columns:
            df = raw.rename(columns={c: c.lower() for c in raw.columns})
            # 确保有 open/high/low/close/volume/date
            for col in ['date', 'open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df = None
                    break
            if df is not None:
                logger.debug(f"stock_zh_index_daily 获取 {stock_code} 成功，{len(df)} 条")
    except Exception as e:
        errors.append(f'stock_zh_index_daily: {e}')

    # ---- 数据源2: fund_etf_hist_em（东方财富ETF） ----
    if df is None:
        try:
            raw = ak.fund_etf_hist_em(
                symbol=stock_code, period='daily',
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust=''
            )
            if raw is not None and not raw.empty:
                col_map = {'日期': 'date', '开盘价': 'open', '最高价': 'high',
                           '最低价': 'low', '收盘价': 'close', '成交量': 'volume'}
                df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
                for col in ['date', 'open', 'high', 'low', 'close']:
                    if col not in df.columns:
                        df = None
                        break
                if df is not None:
                    logger.debug(f"fund_etf_hist_em 获取 {stock_code} 成功，{len(df)} 条")
        except Exception as e:
            errors.append(f'fund_etf_hist_em: {e}')

    # ---- 数据源3: stock_zh_a_hist（A股历史，ETF也可用） ----
    if df is None:
        try:
            raw = ak.stock_zh_a_hist(
                symbol=stock_code, period='daily',
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust=''
            )
            if raw is not None and not raw.empty:
                col_map = {'日期': 'date', '开盘': 'open', '最高': 'high',
                           '最低': 'low', '收盘': 'close', '成交量': 'volume'}
                df = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})
                for col in ['date', 'open', 'high', 'low', 'close']:
                    if col not in df.columns:
                        df = None
                        break
                if df is not None:
                    logger.debug(f"stock_zh_a_hist 获取 {stock_code} 成功，{len(df)} 条")
        except Exception as e:
            errors.append(f'stock_zh_a_hist: {e}')

    if df is None:
        logger.warning(f"获取 {stock_code} 失败: {'; '.join(errors)}")
        return pd.DataFrame()

    # 标准化
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')

    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # 过滤日期范围
    if 'date' in df.columns:
        df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

    df = df.dropna(subset=['close']).reset_index(drop=True)
    return df


def calculate_indicators_ema(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算趋势线指标（使用EMA指数移动平均）

    公式：
    1. 均价 = (最高价 + 最低价) / 2
    2. 趋势线 = 均价的20日指数移动平均(EMA)
       EMA_t = alpha × price_t + (1-alpha) × EMA_{t-1}
       alpha = 2 / (period + 1) = 2/21 ≈ 0.0952
    """
    df['hl2'] = (df['high'] + df['low']) / 2
    df['trend_line'] = df['hl2'].ewm(span=period, adjust=False).mean()
    df['deviation'] = (df['close'] - df['trend_line']) / df['trend_line'] * 100
    return df


def analyze_index(stock_code: str, code_type: str = 'etf', period: int = 20) -> dict:
    """分析单只指数/股票/ETF"""
    try:
        # 需要足够数据支撑 90日涨跌计算（至少 ~130 个交易日 ≈ 180 日历天）
        df = get_stock_data(stock_code, code_type=code_type, days=200)
        df = calculate_indicators_ema(df, period)

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        today_change = (latest['close'] - prev['close']) / prev['close'] * 100

        change_5d = 0
        change_20d = 0
        change_30d = 0
        change_40d = 0
        change_60d = 0
        change_90d = 0
        if len(df) > 5:
            change_5d = (df['close'].iloc[-1] - df['close'].iloc[-6]) / df['close'].iloc[-6] * 100
        if len(df) > 20:
            change_20d = (df['close'].iloc[-1] - df['close'].iloc[-21]) / df['close'].iloc[-21] * 100
        if len(df) > 30:
            change_30d = (df['close'].iloc[-1] - df['close'].iloc[-31]) / df['close'].iloc[-31] * 100
        if len(df) > 40:
            change_40d = (df['close'].iloc[-1] - df['close'].iloc[-41]) / df['close'].iloc[-41] * 100
        if len(df) > 60:
            change_60d = (df['close'].iloc[-1] - df['close'].iloc[-61]) / df['close'].iloc[-61] * 100
        if len(df) > 90:
            change_90d = (df['close'].iloc[-1] - df['close'].iloc[-91]) / df['close'].iloc[-91] * 100

        return {
            'code': stock_code,
            'current_price': latest['close'],
            'trend_line': latest['trend_line'],
            'deviation': latest['deviation'],
            'today_change': today_change,
            'change_5d': change_5d,
            'change_20d': change_20d,
            'change_30d': change_30d,
            'change_40d': change_40d,
            'change_60d': change_60d,
            'change_90d': change_90d,
        }

    except Exception as e:
        return {'code': stock_code, 'error': str(e)}


def display_analysis(results: list, output_file: str = None) -> str:
    """展示分析结果，可选择同时输出到文件

    Args:
        results: 分析结果列表
        output_file: 如果提供，将结果同时写入此文件

    Returns:
        str: 分析结果的文本内容
    """
    valid_results = [r for r in results if 'current_price' in r]
    valid_results.sort(key=lambda x: x.get('deviation', 0), reverse=True)

    lines = []
    header = '=' * 90
    lines.append(header)
    lines.append('宽基指数趋势大模型 - EMA版本')
    lines.append('   日期: ' + datetime.now().strftime('%Y年%m月%d日'))
    lines.append(header)
    lines.append('{:<4} {:<10} {:>10} {:>8} {:>8} {:>8} {:>8} {:>8} {:>8} {:>10} {:>8} {:<6}'.format(
        '强度', '指数', '现价', '今日', '5日', '20日', '30日', '40日', '60日', '90日', '趋势线', '偏离率', '信号'))
    lines.append('-' * 90)

    for i, r in enumerate(valid_results, 1):
        dev = r.get('deviation', 0)

        if dev > 5:
            signal = '极强'
        elif dev > 2:
            signal = '强势'
        elif dev > 0:
            signal = '偏强'
        elif dev > -2:
            signal = '偏弱'
        else:
            signal = '超卖'

        lines.append('{:<4} {:<10} {:>10.3f} {:>+7.2f}% {:>+7.2f}% {:>+7.2f}% {:>+7.2f}% {:>+7.2f}% {:>+7.2f}% {:>10.3f} {:>+7.2f}% {:<6}'.format(
            i, r['code'], r['current_price'], r['today_change'],
            r['change_5d'], r['change_20d'], r.get('change_30d', 0),
            r.get('change_40d', 0), r.get('change_60d', 0), r.get('change_90d', 0),
            r['trend_line'], dev, signal))

    lines.append(header)
    lines.append('趋势线 = (最高价+最低价)/2 的20日指数移动平均(EMA)')
    lines.append('EMA alpha = 2/(period+1) = 2/21 ≈ 0.0952')
    lines.append('偏离率 = (现价-趋势线)/趋势线 × 100%')
    lines.append('强度排序按偏离率数值，数值越大=短期走势越强')
    lines.append('EMA相比SMA对近期数据更敏感，反应更灵敏')
    lines.append(header)

    # 打印到终端
    for line in lines:
        print(line)

    # 写入文件
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f'\n分析结果已保存至: {output_file}')

    return '\n'.join(lines)


def results_to_dataframe(results: list) -> pd.DataFrame:
    """将分析结果转换为 DataFrame（用于统一 Excel 导出）

    Args:
        results: analyze_index 返回的结果列表

    Returns:
        pd.DataFrame: 包含所有指数分析结果的表格
    """
    valid_results = [r for r in results if 'current_price' in r]
    valid_results.sort(key=lambda x: x.get('deviation', 0), reverse=True)

    data = []
    for i, r in enumerate(valid_results, 1):
        dev = r.get('deviation', 0)
        if dev > 5:
            signal = '极强'
        elif dev > 2:
            signal = '强势'
        elif dev > 0:
            signal = '偏强'
        elif dev > -2:
            signal = '偏弱'
        else:
            signal = '超卖'

        data.append({
            '强度排名': i,
            '指数名称': r['code'],
            '现价': round(r['current_price'], 3),
            '今日涨跌(%)': round(r['today_change'], 2),
            '5日涨跌(%)': round(r['change_5d'], 2),
            '20日涨跌(%)': round(r['change_20d'], 2),
            '30日涨跌(%)': round(r.get('change_30d', 0), 2),
            '40日涨跌(%)': round(r.get('change_40d', 0), 2),
            '60日涨跌(%)': round(r.get('change_60d', 0), 2),
            '90日涨跌(%)': round(r.get('change_90d', 0), 2),
            '趋势线': round(r['trend_line'], 3),
            '偏离率(%)': round(dev, 2),
            '信号': signal,
        })

    return pd.DataFrame(data)


def run_index_analysis(output_file: str = None) -> dict:
    """运行宽基指数趋势分析（主入口）

    Args:
        output_file: 输出文本文件路径，None 则只输出到终端

    Returns:
        dict: {
            'text': 分析结果文本,
            'dataframe': DataFrame 表格,
            'results': 原始结果列表
        }
    """
    logger.info("开始宽基指数 EMA 趋势分析...")

    print('\n正在获取数据（EMA版本）...\n')

    results = []
    for item in DEFAULT_INDICES:
        code, name, code_type = item if len(item) == 3 else (item[0], item[1], 'etf')
        try:
            result = analyze_index(code, code_type=code_type)
            result['code'] = name
            results.append(result)
            print('OK ' + name)
        except Exception as e:
            print('FAIL ' + name + ': ' + str(e))
            logger.warning(f"指数 {name} 分析失败: {e}")

    text = ''
    df = pd.DataFrame()

    if results:
        text = display_analysis(results, output_file=output_file)
        df = results_to_dataframe(results)
        logger.info("宽基指数分析完成")

    else:
        logger.error("宽基指数分析无有效结果")

    return {'text': text, 'dataframe': df, 'results': results}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='宽基指数EMA趋势分析')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径')
    args = parser.parse_args()

    result = run_index_analysis(output_file=args.output)
    print('\n分析完成!')
