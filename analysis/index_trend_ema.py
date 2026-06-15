"""
宽基指数趋势大模型 - EMA版本

指标计算（使用EMA指数移动平均）：
- 趋势线: (最高价 + 最低价) / 2 的20日指数移动平均(EMA)
- 偏离率: (现价 - 趋势线) / 趋势线 × 100%
- 强度排序: 按偏离率数值排序，数值最大=1（最强）

从 ff 项目迁移，重构为可调用函数接口。
"""

import baostock as bs
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger


# 默认分析指数列表
DEFAULT_INDICES = [
    # A股主要指数
    ('sh.000001', '上证指数'),
    ('sz.399001', '深证成指'),
    ('sz.399006', '创业板指'),

    # 宽基ETF
    ('sh.510050', '上证50'),
    ('sh.510300', '沪深300'),
    ('sh.510500', '中证500'),
    ('sh.512100', '中证1000'),
    ('sh.563300', '国证2000'),

    # 风格/策略ETF
    ('sz.159949', '创业板50'),
    ('sz.159967', '创成长'),
    ('sh.588000', '科创50'),
    ('sh.588220', '科创100'),
    ('sh.512890', '红利低波'),

    # 跨境ETF（QDII）
    ('sz.159920', '恒生ETF'),
    ('sh.513130', '恒生科技'),
    ('sh.513100', '纳指'),
    ('sh.513030', '德国'),
    ('sh.513520', '日经'),
    ('sh.513310', '中韩半导体'),
    ('sz.164824', '印度基金'),

    # 商品ETF
    ('sh.518880', '黄金'),
    ('sz.161226', '白银'),
    ('sz.159985', '豆粕'),
    ('sz.162411', '华宝油气'),
]


def get_stock_data(stock_code: str, days: int = 100, end_date: str = None) -> pd.DataFrame:
    """获取股票/指数数据"""
    bs.login()

    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days)).strftime('%Y-%m-%d')

    rs = bs.query_history_k_data_plus(
        stock_code,
        'date,code,open,high,low,close,volume',
        start_date=start_date,
        end_date=end_date,
        frequency='d'
    )

    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())

    bs.logout()

    df = pd.DataFrame(data_list, columns=rs.fields)

    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

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


def analyze_index(stock_code: str, period: int = 20) -> dict:
    """分析单只指数/股票"""
    try:
        df = get_stock_data(stock_code, days=period * 4)
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
    for code, name in DEFAULT_INDICES:
        try:
            result = analyze_index(code)
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
