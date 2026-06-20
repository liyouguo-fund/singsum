"""
场外基金趋势大模型 - WMA版本

核心算法：
1. WMA（线性加权移动平均）：权重从指定周期递减到1
2. 偏离率：衡量当前净值相对于趋势线的偏离程度
3. 布林带：基于标准差的价格通道
4. 5日高低价：平滑的价格区间表示
5. 均线多头排列：判断 MA10 > MA20 > MA30 > MA60 是否成立

从 ff 项目迁移，重构为函数接口，使用共享的 fund_fetcher 获取基金列表。
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger
from core.fund_fetcher import get_fund_codes

# 获取项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==================== 全局配置 ====================
# 中文字体自动检测
_chinese_fonts = []
for f in fm.findSystemFonts():
    try:
        fp = fm.FontProperties(fname=f)
        name = fp.get_name()
        if any(kw in name.lower() for kw in ['yahei', 'simhei', 'simsun', 'wqy', 'wenquanyi',
                                               'noto', 'droid', 'source han', 'fang', 'kai',
                                               'microsoft', 'pingfang', 'heiti', 'songti']):
            _chinese_fonts.append(name)
    except Exception:
        pass

_chinese_fonts = list(dict.fromkeys(_chinese_fonts))
_font_list = _chinese_fonts + ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei',
                                'Noto Sans CJK SC', 'Noto Sans SC',
                                'Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['font.sans-serif'] = _font_list
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['figure.dpi'] = 100

try:
    fm._load_fontmanager(try_read_cache=False)
except Exception:
    pass


def get_fund_data(fund_code, start_date=None):
    """获取基金净值数据（通过 xalpha 库）

    Args:
        fund_code: 基金代码（6位数字）
        start_date: 起始日期

    Returns:
        tuple: (DataFrame, fund_name) 或 (None, None)
    """
    import xalpha as xa

    if start_date is None:
        start_date = (datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d')

    fund_code = str(fund_code).zfill(6)

    print(f"正在获取基金 {fund_code} 的数据...")

    try:
        fund = xa.fundinfo(fund_code)
        df = fund.price.copy()
        df = df.reset_index()
        df = df.rename(columns={'netvalue': 'nav'})
        if 'nav' not in df.columns and 'totvalue' in df.columns:
            df['nav'] = df['totvalue']

        df = df[['date', 'nav']].copy()
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        df = df.dropna(subset=['nav']).reset_index(drop=True)

        if start_date:
            df = df[df['date'] >= start_date].copy()

        fund_name = getattr(fund, 'name', f'基金{fund_code}')
        print(f"获取到 {len(df)} 条净值数据（从 {df['date'].iloc[0]} 开始）")
        return df, fund_name

    except Exception as e:
        print(f"获取基金数据失败: {e}")
        return None, None


def calculate_wma(data, period=20):
    """计算线性加权移动平均 (WMA)"""
    weights = np.arange(1, period + 1)

    def weighted_avg(x):
        if len(x) < period:
            return np.nan
        return np.sum(weights * x) / weights.sum()

    return data.rolling(window=period).apply(weighted_avg, raw=True)


def calculate_indicators_wma_5dhl(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """计算完整的趋势指标体系"""
    df = df.copy()

    # 5日高低价
    df['high_5d'] = df['nav'].rolling(window=5).max()
    df['low_5d'] = df['nav'].rolling(window=5).min()
    df['hl2_5d'] = (df['high_5d'] + df['low_5d']) / 2

    # WMA趋势线
    df['trend_line'] = calculate_wma(df['hl2_5d'], period)

    # 布林带
    df['bb_mid'] = df['nav'].rolling(window=20).mean()
    bb_std = df['nav'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std

    # 偏离率
    df['deviation'] = (df['nav'] - df['trend_line']) / df['trend_line'] * 100

    # 各周期均线
    df['ma10'] = df['nav'].rolling(window=10).mean()
    df['ma20'] = df['nav'].rolling(window=20).mean()
    df['ma30'] = df['nav'].rolling(window=30).mean()
    df['ma60'] = df['nav'].rolling(window=60).mean()

    # 均线多头排列
    df['ma_bullish'] = (df['ma10'] > df['ma20']) & (df['ma20'] > df['ma30']) & (df['ma30'] > df['ma60'])

    return df


def analyze_fund(fund_code: str, fund_name: str = None, period: int = 20,
                 prefetched_df: pd.DataFrame = None) -> dict:
    """分析单只基金

    Args:
        fund_code: 基金代码
        fund_name: 基金名称（可选）
        period: WMA周期
        prefetched_df: 预取的数据（含 date, nav 列），为 None 则自行调用 xalpha 获取
    """
    try:
        auto_name = None
        if prefetched_df is not None and not prefetched_df.empty:
            df = prefetched_df.copy()
            auto_name = f'基金{fund_code}'
        else:
            df, auto_name = get_fund_data(fund_code)

        if df is None or len(df) < period + 5:
            return {
                'code': fund_code,
                'name': fund_name or auto_name or f'基金{fund_code}',
                'error': '数据不足'
            }

        df = calculate_indicators_wma_5dhl(df, period)

        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        today_change = (latest['nav'] - prev['nav']) / prev['nav'] * 100

        change_5d = 0
        change_20d = 0
        change_30d = 0
        change_40d = 0
        change_60d = 0
        change_90d = 0
        if len(df) > 5:
            change_5d = (df['nav'].iloc[-1] - df['nav'].iloc[-6]) / df['nav'].iloc[-6] * 100
        if len(df) > 20:
            change_20d = (df['nav'].iloc[-1] - df['nav'].iloc[-21]) / df['nav'].iloc[-21] * 100
        if len(df) > 30:
            change_30d = (df['nav'].iloc[-1] - df['nav'].iloc[-31]) / df['nav'].iloc[-31] * 100
        if len(df) > 40:
            change_40d = (df['nav'].iloc[-1] - df['nav'].iloc[-41]) / df['nav'].iloc[-41] * 100
        if len(df) > 60:
            change_60d = (df['nav'].iloc[-1] - df['nav'].iloc[-61]) / df['nav'].iloc[-61] * 100
        if len(df) > 90:
            change_90d = (df['nav'].iloc[-1] - df['nav'].iloc[-91]) / df['nav'].iloc[-91] * 100

        ma_bullish = '是' if latest['ma_bullish'] else '否'

        return {
            'code': fund_code,
            'name': fund_name or auto_name or f'基金{fund_code}',
            'current_price': latest['nav'],
            'high_5d': latest['high_5d'],
            'low_5d': latest['low_5d'],
            'trend_line': latest['trend_line'],
            'deviation': latest['deviation'],
            'today_change': today_change,
            'change_5d': change_5d,
            'change_20d': change_20d,
            'change_30d': change_30d,
            'change_40d': change_40d,
            'change_60d': change_60d,
            'change_90d': change_90d,
            'ma_bullish': ma_bullish,
            'df': df
        }

    except Exception as e:
        return {
            'code': fund_code,
            'name': fund_name or f'基金{fund_code}',
            'error': str(e)
        }


def display_single_result(result: dict, rank: int = None):
    """显示单只基金的分析结果"""
    if 'error' in result:
        print(f'FAIL {result["code"]}: {result["error"]}')
        return

    dev = result.get('deviation', 0)
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

    if rank is not None:
        print(f'{rank:>2}. {result["code"]}  {result["name"][:10]:<10} '
              f'{result["current_price"]:>8.4f}  {result["today_change"]:>+6.2f}%  '
              f'{result["deviation"]:>+7.2f}%  {signal}')
    else:
        print(f'    {result["code"]}  {result["name"][:10]:<10} '
              f'{result["current_price"]:>8.4f}  {result["today_change"]:>+6.2f}%  '
              f'{result["deviation"]:>+7.2f}%  {signal}')


def display_analysis(results: list, period: int = 20):
    """在终端显示分析结果表格"""
    valid_results = [r for r in results if 'current_price' in r]
    valid_results.sort(key=lambda x: x.get('deviation', 0), reverse=True)

    header = '=' * 140
    print(header)
    print('场外基金趋势大模型 - WMA版本（5日高低价）')
    print('   日期: ' + datetime.now().strftime('%Y年%m月%d日'))
    print(header)

    print('{:<4} {:<12} {:<8} {:>10} {:>7} {:>7} {:>7} {:>7} {:>7} {:>7} {:>7} {:>9} {:>7} {:<6} {:>4}'.format(
        '强度', '基金代码', '基金名称', '现价', '今日', '5日', '20日', '30日', '40日', '60日', '90日',
        '趋势线', '偏离率', '信号', '多头'))
    print('-' * 140)

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

        print('{:<4} {:<12} {:<8} {:>10.4f} {:>+6.2f}% {:>+6.2f}% {:>+6.2f}% {:>+6.2f}% {:>+6.2f}% {:>+6.2f}% {:>+6.2f}% {:>9.4f} {:>+6.2f}% {:<6} {:>4}'.format(
            i, r['code'], r['name'][:8], r['current_price'], r['today_change'],
            r['change_5d'], r['change_20d'], r.get('change_30d', 0),
            r.get('change_40d', 0), r.get('change_60d', 0), r.get('change_90d', 0),
            r['trend_line'], dev, signal, r.get('ma_bullish', '否')))

    print(header)
    print('【指标说明】')
    print('  5日高低价: 过去5个交易日的最高/最低净值')
    print(f'  趋势线   : 均价的{period}日线性加权移动平均(WMA)')
    print(f'  偏离率   : (现价-趋势线)/趋势线 × 100%')
    print('  强度排序 : 按偏离率数值，数值越大=短期走势越强')
    print('  多头排列 : ma10>ma20>ma30>ma60，满足为"是"，否则为"否"')
    print(header)


def export_to_excel(results: list, output_path: str = None):
    """将分析结果导出到Excel文件"""
    if output_path is None:
        output_dir = os.path.join(PROJECT_ROOT, 'output')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, '基金趋势分析.xlsx')

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
            '强度': i,
            '基金代码': r['code'],
            '基金名称': r['name'],
            '现价': round(r['current_price'], 4),
            '今日涨跌': f"{r['today_change']:+.2f}%",
            '5日涨跌': f"{r['change_5d']:+.2f}%",
            '20日涨跌': f"{r['change_20d']:+.2f}%",
            '30日涨跌': f"{r.get('change_30d', 0):+.2f}%",
            '40日涨跌': f"{r.get('change_40d', 0):+.2f}%",
            '60日涨跌': f"{r.get('change_60d', 0):+.2f}%",
            '90日涨跌': f"{r.get('change_90d', 0):+.2f}%",
            '5日最高': round(r['high_5d'], 4),
            '5日最低': round(r['low_5d'], 4),
            '趋势线': round(r['trend_line'], 4),
            '偏离率': f"{r['deviation']:+.2f}%",
            '信号': signal,
            '多头排列': r.get('ma_bullish', '否')
        })

    df = pd.DataFrame(data)
    df = df[['强度', '基金代码', '基金名称', '现价', '今日涨跌', '5日涨跌', '20日涨跌',
             '30日涨跌', '40日涨跌', '60日涨跌', '90日涨跌',
             '5日最高', '5日最低', '趋势线', '偏离率', '信号', '多头排列']]
    df.to_excel(output_path, index=False, engine='openpyxl')
    print(f'\nExcel表格已保存至: {output_path}')
    logger.info(f"Excel已保存至: {output_path}")

    return output_path


def get_deviation_color(dev):
    """根据偏离率获取颜色"""
    if dev > 5:
        return '#CD5C5C'
    elif dev > 2:
        return '#FF9999'
    elif dev > 0:
        return '#FFCCCC'
    elif dev > -2:
        return '#CCFFCC'
    else:
        return '#006400'


def plot_fund_trend(result: dict, save_path=None, buy2_dates=None, buy5_dates=None):
    """绘制基金趋势分析图表"""
    if 'df' not in result:
        print("无数据可绘制")
        return

    df = result['df'].copy()
    df['date'] = pd.to_datetime(df['date'])

    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(2, 1, height_ratios=[4, 2.5])
    fig.suptitle(f'{result["name"]} ({result["code"]}) 趋势分析 - WMA',
                 fontsize=16, fontweight='bold')

    # 上半部分：主图
    ax1 = fig.add_subplot(gs[0])

    colors = [get_deviation_color(d) for d in df['deviation']]
    dates_mpl = mdates.date2num(df['date'])
    width = np.diff(dates_mpl, append=dates_mpl[-1] + (dates_mpl[-1] - dates_mpl[-2]))

    all_data = pd.concat([df['nav'], df['high_5d'], df['low_5d'], df['trend_line'],
                          df['bb_upper'], df['bb_lower']], axis=1)
    y_min = all_data.min().min()
    y_max = all_data.max().max()
    y_pad = (y_max - y_min) * 0.1
    y_low, y_high = y_min - y_pad, y_max + y_pad

    for i in range(len(dates_mpl)):
        ax1.axvspan(dates_mpl[i] - width[i] / 2, dates_mpl[i] + width[i] / 2,
                    ymin=0, ymax=1, color=colors[i], alpha=0.3)

    ax1.plot(df['date'], df['nav'], label='净值', color='black', linewidth=2.5, zorder=10)
    ax1.plot(df['date'], df['trend_line'], label='趋势线(WMA)', color='blue', linewidth=2, zorder=5)
    ax1.plot(df['date'], df['high_5d'], label='5日最高', color='green', linestyle='--', alpha=0.8, zorder=3)
    ax1.plot(df['date'], df['low_5d'], label='5日最低', color='red', linestyle='--', alpha=0.8, zorder=3)
    ax1.fill_between(df['date'], df['low_5d'], df['high_5d'], color='gray', alpha=0.15, zorder=2)

    ax1.plot(df['date'], df['bb_upper'], label='布林带上轨', color='orange', linewidth=1.5, zorder=4)
    ax1.plot(df['date'], df['bb_mid'], label='布林带中轨', color='orange', linewidth=1, linestyle='--', zorder=4)
    ax1.plot(df['date'], df['bb_lower'], label='布林带下轨', color='orange', linewidth=1.5, zorder=4)
    ax1.fill_between(df['date'], df['bb_lower'], df['bb_upper'], color='orange', alpha=0.1, zorder=2)

    # 标记稳健策略/激进策略买入信号
    if buy2_dates is not None and len(buy2_dates) > 0:
        b2p = [df[df['date'] == d]['nav'].values[0] for d in buy2_dates if d in df['date'].values]
        b2d = [d for d in buy2_dates if d in df['date'].values]
        if b2d:
            ax1.scatter(b2d, b2p, marker='^', color='limegreen', s=180, zorder=20,
                       label='稳健策略买入', edgecolors='darkgreen', linewidths=1)
    if buy5_dates is not None and len(buy5_dates) > 0:
        b5p = [df[df['date'] == d]['nav'].values[0] for d in buy5_dates if d in df['date'].values]
        b5d = [d for d in buy5_dates if d in df['date'].values]
        if b5d:
            ax1.scatter(b5d, b5p, marker='D', color='dodgerblue', s=140, zorder=20,
                       label='激进策略买入', edgecolors='darkblue', linewidths=1)

    ax1.set_ylim(y_low, y_high)
    ax1.set_ylabel('净值', fontsize=12)
    ax1.set_title('净值、趋势线、5日高低价与布林带 (WMA)', fontsize=12)
    ax1.grid(True, alpha=0.3, zorder=1)
    ax1.xaxis_date()

    legend_elements = [
        Patch(facecolor='#CD5C5C', label='极强 (>5%)'),
        Patch(facecolor='#FF9999', label='强势 (2%~5%)'),
        Patch(facecolor='#FFCCCC', label='偏强 (0%~2%)'),
        Patch(facecolor='#CCFFCC', label='偏弱 (-2%~0%)'),
        Patch(facecolor='#006400', label='超卖 (<-2%)'),
        Line2D([0], [0], color='black', linewidth=2.5, label='净值'),
        Line2D([0], [0], color='blue', linewidth=2, label='趋势线(WMA)'),
        Line2D([0], [0], color='green', linestyle='--', label='5日最高'),
        Line2D([0], [0], color='red', linestyle='--', label='5日最低'),
        Line2D([0], [0], color='orange', linewidth=1.5, label='布林带上轨'),
        Line2D([0], [0], color='orange', linewidth=1, linestyle='--', label='布林带中轨'),
        Line2D([0], [0], color='orange', linewidth=1.5, label='布林带下轨'),
        Line2D([0], [0], marker='^', color='limegreen', label='稳健策略买入',
               markerfacecolor='limegreen', markeredgecolor='darkgreen',
               markersize=10, linewidth=0),
        Line2D([0], [0], marker='D', color='dodgerblue', label='激进策略买入',
               markerfacecolor='dodgerblue', markeredgecolor='darkblue',
               markersize=8, linewidth=0),
    ]
    ax1.legend(handles=legend_elements, loc='upper left', fontsize=8, ncol=2)

    # 下半部分：偏离率
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    bar_colors = ['red' if x >= 0 else 'green' for x in df['deviation']]
    ax2.bar(df['date'], df['deviation'], color=bar_colors, alpha=0.6, width=1)
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=1)
    ax2.axhline(y=5, color='red', linestyle='--', alpha=0.5, label='强势线(+5%)')
    ax2.axhline(y=2, color='orange', linestyle='--', alpha=0.5, label='弱势线(+2%)')
    ax2.set_ylabel('偏离率 (%)', fontsize=12)
    ax2.legend(loc='upper left', fontsize=10)
    ax2.set_title('偏离率 (WMA)', fontsize=12)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    plt.xticks(rotation=45)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight', facecolor='white')
        print(f"图表已保存至: {save_path}")

    plt.close(fig)


def results_to_dataframe(results: list) -> pd.DataFrame:
    """将基金趋势分析结果转换为 DataFrame（用于统一 Excel 导出）"""
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
            '基金代码': r['code'],
            '基金名称': r['name'],
            '现价': round(r['current_price'], 4),
            '今日涨跌(%)': round(r['today_change'], 2),
            '5日涨跌(%)': round(r['change_5d'], 2),
            '20日涨跌(%)': round(r['change_20d'], 2),
            '30日涨跌(%)': round(r.get('change_30d', 0), 2),
            '40日涨跌(%)': round(r.get('change_40d', 0), 2),
            '60日涨跌(%)': round(r.get('change_60d', 0), 2),
            '90日涨跌(%)': round(r.get('change_90d', 0), 2),
            '5日最高': round(r['high_5d'], 4),
            '5日最低': round(r['low_5d'], 4),
            '趋势线': round(r['trend_line'], 4),
            '偏离率(%)': round(dev, 2),
            '信号': signal,
            '多头排列': r.get('ma_bullish', '否'),
        })

    return pd.DataFrame(data)


def run_fund_trend_analysis(fund_codes: list = None,
                            prefetched_data: dict = None,
                            fund_name_map: dict = None) -> dict:
    """运行场外基金WMA趋势分析（主入口）

    Args:
        fund_codes: 基金代码列表，None 则从问财获取
        prefetched_data: 预取的历史数据 {fund_code: DataFrame(date, nav, ...)}
        fund_name_map: 基金代码→名称映射 {fund_code: fund_name}，来自问财真实名称

    Returns:
        dict: {'results', 'dataframe', 'excel_path', 'images_dir'}
    """
    logger.info("开始场外基金 WMA 趋势分析...")

    # 获取基金列表（优先使用传入列表，否则从问财获取）
    if fund_codes is None:
        fund_codes = get_fund_codes()

    if not fund_codes:
        logger.error("未获取到基金列表，终止分析")
        return {'results': [], 'excel_path': None, 'images_dir': None}

    period = 20

    # 创建输出目录
    today_str = datetime.now().strftime('%Y%m%d')
    output_dir = os.path.join(PROJECT_ROOT, 'output')
    images_dir = os.path.join(output_dir, f'基金趋势图_{today_str}')
    os.makedirs(images_dir, exist_ok=True)
    print(f"\n图片将保存到目录: {images_dir}")

    print('\n正在获取基金数据并计算指标...\n')
    print(f'{"排名":>2}  {"基金代码":<8}  {"基金名称":<10}  {"现价":>8}  {"今日涨跌":>7}  {"偏离率":>7}  {"信号"}')
    print('-' * 75)

    results = []
    for idx, code in enumerate(fund_codes, 1):
        try:
            # 传入预取数据和真实名称
            pdf = prefetched_data.get(code) if prefetched_data else None
            real_name = fund_name_map.get(code) if fund_name_map else None
            result = analyze_fund(code, fund_name=real_name, prefetched_df=pdf)
            results.append(result)

            if 'error' not in result:
                display_single_result(result, idx)

                # 计算策略信号（用于图表标记）
                buy2_dates = []
                buy5_dates = []
                try:
                    if 'df' in result:
                        from analysis.fund_signal import calculate_strategy_indicators
                        sdf = result['df'][['date', 'nav']].copy()
                        sdf = calculate_strategy_indicators(sdf)
                        buy2_dates = sdf[sdf['buy_signal_2'] == True]['date'].tolist()
                        buy5_dates = sdf[sdf['buy_signal_5'] == True]['date'].tolist()
                except Exception:
                    pass

                # 保存图表
                try:
                    clean_name = result['name']
                    for char in ['\\', '/', ':', '*', '?', '"', '<', '>', '|', '\t', '\n']:
                        clean_name = clean_name.replace(char, '_')
                    save_path = f'{images_dir}/{clean_name}_{result["code"]}.png'
                    plot_fund_trend(result, save_path, buy2_dates, buy5_dates)
                except Exception as e:
                    print(f"    绘图失败: {str(e)}")
            else:
                print(f'{idx:>2}. FAIL {code}: {result["error"]}')

        except Exception as e:
            print(f'{idx:>2}. FAIL {code}: {str(e)}')
            logger.warning(f"基金 {code} 分析失败: {e}")

    # 显示汇总表格
    if results:
        print('\n')
        display_analysis(results, period)
        excel_path = export_to_excel(results)

    logger.info(f"场外基金趋势分析完成，共分析 {len(results)} 只基金")
    print('\n分析完成!')

    # 构建 DataFrame
    df = results_to_dataframe(results) if results else pd.DataFrame()

    return {
        'results': results,
        'dataframe': df,
        'excel_path': os.path.join(output_dir, '基金趋势分析.xlsx'),
        'images_dir': images_dir,
    }


if __name__ == "__main__":
    run_fund_trend_analysis()
