"""
基金分析综合系统 - 统一入口

运行三个分析模块，将所有数据写入一个 Excel 文件，并发送综合邮件报告。

使用方式：
    python main.py                          # 运行全部三个分析
    python main.py --skip-index            # 跳过宽基指数分析
    python main.py --skip-trend            # 跳过基金趋势分析
    python main.py --skip-signal           # 跳过基金信号分析
    python main.py --days 5                # 信号分析保留5天数据
    python main.py --wencai "场外基金近1年涨幅top50"
    python main.py --no-email              # 不发送邮件
"""

import sys
import os
import argparse
import pandas as pd
from datetime import datetime

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.logger import logger
from core.email_sender import send_email, build_signal_html_report


def merge_fund_data(trend_df: pd.DataFrame, signal_df: pd.DataFrame) -> pd.DataFrame:
    """合并基金趋势分析和信号分析为一个表格

    以 基金代码 为 key，趋势数据（一行一基金）left join 信号最新数据。

    Args:
        trend_df: 基金趋势分析 DataFrame（含 基金代码, 基金名称, 现价, 涨跌, 趋势线, 信号等）
        signal_df: 基金信号 DataFrame（含 基金代码, 均线信号, RSI信号, MACD信号等，多行/基金）

    Returns:
        pd.DataFrame: 合并后的单表
    """
    # ---- 处理信号数据：取每只基金最新一条 ----
    signal_latest = pd.DataFrame()
    if not signal_df.empty:
        sig = signal_df.copy()
        # 确保有日期列用于排序
        if '净值日期' in sig.columns:
            sig['净值日期'] = pd.to_datetime(sig['净值日期'], errors='coerce')
            sig = sig.sort_values('净值日期')
            signal_latest = sig.groupby('基金代码').last().reset_index()
        else:
            signal_latest = sig.groupby('基金代码').last().reset_index()

        # 只保留核心信号列（避免和趋势列重名冲突）
        signal_cols = ['基金代码', '投资类型', '净值日期',
                       '均线信号', 'RSI', 'RSI信号',
                       'cci值', 'cci信号', 'macd值', 'macd信号', '布林带信号']
        signal_cols = [c for c in signal_cols if c in signal_latest.columns]
        signal_latest = signal_latest[signal_cols]

    # ---- 处理趋势数据 ----
    if not trend_df.empty:
        trend = trend_df.copy()
        # 重命名趋势的"信号"列避免冲突
        if '信号' in trend.columns:
            trend = trend.rename(columns={'信号': '趋势信号'})
        # 统一 基金代码 为字符串类型
        if '基金代码' in trend.columns:
            trend['基金代码'] = trend['基金代码'].astype(str).str.zfill(6).str[:6]
    else:
        trend = pd.DataFrame()

    # ---- 统一 signal_latest 的 基金代码 类型 ----
    if not signal_latest.empty and '基金代码' in signal_latest.columns:
        signal_latest['基金代码'] = signal_latest['基金代码'].astype(str).str.zfill(6).str[:6]

    # ---- 合并 ----
    if not trend.empty and not signal_latest.empty:
        combined = trend.merge(signal_latest, on='基金代码', how='outer', suffixes=('', '_sig'))
        # 如果信号表有 基金简称 但趋势表已有 基金名称，优先用趋势表
        if '基金名称' in combined.columns and '基金简称' in combined.columns:
            combined['基金名称'] = combined['基金名称'].fillna(combined['基金简称'])
            combined = combined.drop(columns=['基金简称'], errors='ignore')
    elif not trend.empty:
        combined = trend
        if '信号' in combined.columns:
            combined = combined.rename(columns={'信号': '趋势信号'})
    elif not signal_latest.empty:
        combined = signal_latest
    else:
        combined = pd.DataFrame()

    # ---- 列顺序优化：基金信息 → 趋势指标 → 信号 ----
    preferred_order = [
        '强度排名', '基金代码', '基金名称', '投资类型',
        '现价', '今日涨跌(%)', '5日涨跌(%)', '20日涨跌(%)',
        '30日涨跌(%)', '40日涨跌(%)', '60日涨跌(%)', '90日涨跌(%)',
        '5日最高', '5日最低', '趋势线', '偏离率(%)', '趋势信号', '多头排列',
        '净值日期',
        '均线信号', 'RSI', 'RSI信号',
        'cci值', 'cci信号', 'macd值', 'macd信号', '布林带信号',
    ]
    # 动态插入持仓/概念列到投资类型后面
    extra_info_cols = [c for c in combined.columns
                       if ('持仓' in c or '概念' in c or '主题' in c or '板块' in c)
                       and c not in preferred_order]
    # 找到 '投资类型' 的位置，把 extra_info_cols 插在它后面
    if '投资类型' in preferred_order and extra_info_cols:
        insert_pos = preferred_order.index('投资类型') + 1
        for i, col in enumerate(extra_info_cols):
            preferred_order.insert(insert_pos + i, col)

    existing_cols = [c for c in preferred_order if c in combined.columns]
    other_cols = [c for c in combined.columns if c not in existing_cols]
    combined = combined[existing_cols + other_cols]

    return combined


def main():
    parser = argparse.ArgumentParser(description='基金分析综合系统')
    parser.add_argument('--skip-index', action='store_true', help='跳过宽基指数分析')
    parser.add_argument('--skip-trend', action='store_true', help='跳过基金趋势分析')
    parser.add_argument('--skip-signal', action='store_true', help='跳过基金信号分析')
    parser.add_argument('--days', type=int, default=10, help='信号分析保留数据天数')
    parser.add_argument('--wencai', type=str, default=None, help='问财查询语句')
    parser.add_argument('--no-email', action='store_true', help='不发送邮件')
    args = parser.parse_args()

    report_date = datetime.now().strftime('%Y-%m-%d')
    today_str = datetime.now().strftime('%Y%m%d')

    logger.info("=" * 80)
    logger.info(f"基金分析综合系统启动 - {report_date}")
    logger.info("=" * 80)

    # 创建输出目录
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
    os.makedirs(output_dir, exist_ok=True)

    # 统一的 Excel 文件路径
    unified_excel = os.path.join(output_dir, f'基金分析综合报告_{today_str}.xlsx')

    # Excel writer（逐 sheet 写入）
    excel_writer = pd.ExcelWriter(unified_excel, engine='openpyxl')

    # ---- 1. 宽基指数 EMA 趋势分析 ----
    index_text = ''
    if not args.skip_index:
        logger.info(">>> 步骤 1/3: 宽基指数趋势分析 (EMA)")
        try:
            from analysis.index_trend_ema import run_index_analysis
            index_result = run_index_analysis(
                output_file=os.path.join(output_dir, '宽基指数分析结果.txt')
            )
            index_text = index_result.get('text', '')
            index_df = index_result.get('dataframe', pd.DataFrame())

            if not index_df.empty:
                index_df.to_excel(excel_writer, sheet_name='宽基指数趋势', index=False)
                logger.info(f"宽基指数趋势数据已写入 Excel ({len(index_df)} 条)")
            else:
                logger.warning("宽基指数分析无数据")
        except Exception as e:
            logger.error(f"宽基指数分析失败: {e}")

    # ---- 2. 场外基金 WMA 趋势分析 ----
    trend_df = pd.DataFrame()
    trend_images_dir = ''
    if not args.skip_trend:
        logger.info(">>> 步骤 2/3: 场外基金趋势分析 (WMA)")
        try:
            from analysis.fund_trend_wma import run_fund_trend_analysis
            trend_result = run_fund_trend_analysis()
            trend_df = trend_result.get('dataframe', pd.DataFrame())
            trend_images_dir = trend_result.get('images_dir', '')
            if not trend_df.empty:
                logger.info(f"基金趋势分析完成 ({len(trend_df)} 条)")
            else:
                logger.warning("基金趋势分析无数据")
        except Exception as e:
            logger.error(f"基金趋势分析失败: {e}")

    # ---- 3. 基金技术信号分析 ----
    signal_df = pd.DataFrame()
    signal_csv = None
    if not args.skip_signal:
        logger.info(">>> 步骤 3/3: 基金技术信号分析")
        try:
            from analysis.fund_signal import run_fund_signal_analysis
            signal_result = run_fund_signal_analysis(
                days_to_keep=args.days,
                wencai_query=args.wencai
            )
            signal_df = signal_result.get('dataframe', pd.DataFrame())
            signal_csv = signal_result.get('csv_path')
            if not signal_df.empty:
                logger.info(f"基金信号分析完成 ({len(signal_df)} 条)")
            else:
                logger.warning("基金信号分析无数据")
        except Exception as e:
            logger.error(f"基金信号分析失败: {e}")

    # ---- 合并基金趋势 + 信号 → 一个 Sheet ----
    if not trend_df.empty or not signal_df.empty:
        logger.info(">>> 合并基金趋势与信号数据...")
        combined_fund_df = merge_fund_data(trend_df, signal_df)
        if not combined_fund_df.empty:
            combined_fund_df.to_excel(excel_writer, sheet_name='基金综合分析', index=False)
            logger.info(f"基金综合分析已写入 Excel ({len(combined_fund_df)} 条)")
        else:
            logger.warning("基金合并数据为空")

    # 关闭 Excel writer（保存文件）
    excel_writer.close()
    logger.info(f"综合报告已保存至: {unified_excel}")

    # ---- 4. 发送邮件 ----
    if not args.no_email:
        logger.info(">>> 发送综合邮件报告")

        # 构建 HTML 报告
        html_body = build_signal_html_report(
            signal_csv_path=signal_csv,
            index_analysis_text=index_text,
            report_date=report_date
        )

        # 准备附件
        attachments = [unified_excel]

        # 发送邮件
        success = send_email(
            subject=f'【基金分析综合报告】{report_date}',
            body_html=html_body,
            attachment_paths=attachments,
        )

        if success:
            logger.info("邮件发送成功")
        else:
            logger.error("邮件发送失败")
    else:
        logger.info("跳过邮件发送（--no-email）")

    logger.info("=" * 80)
    logger.info("基金分析综合系统运行完成")
    logger.info(f"输出文件: {unified_excel}")
    logger.info("=" * 80)

    print(f"\n{'=' * 60}")
    print(f"  基金分析综合报告已生成")
    print(f"  日期: {report_date}")
    print(f"  文件: {unified_excel}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
