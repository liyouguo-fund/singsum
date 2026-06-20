"""
统一邮件发送模块

合并自:
- ff/send_email.py: 文本正文 + Excel附件 + 趋势图下载链接
- fund_signal/email_sender.py: HTML 信号统计报告

统一使用 MAIL_* 环境变量命名约定。
"""

import smtplib
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from email import encoders
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger


def _load_config():
    """加载邮件配置（统一使用 MAIL_* 环境变量）"""
    config = {
        'smtp_server': os.environ.get('MAIL_SMTP_SERVER', 'smtp.qq.com').strip(),
        'smtp_user': os.environ.get('MAIL_USERNAME', '').strip(),
        'smtp_password': os.environ.get('MAIL_PASSWORD', '').strip(),
        'recipients': os.environ.get('MAIL_TO', '').strip(),
    }

    # SMTP 端口处理
    smtp_port_env = os.environ.get('MAIL_SMTP_PORT', '465').strip()
    try:
        config['smtp_port'] = int(smtp_port_env)
    except ValueError:
        logger.warning(f"无效的 MAIL_SMTP_PORT: {smtp_port_env}，使用默认值 465")
        config['smtp_port'] = 465

    if not config['smtp_server']:
        config['smtp_server'] = 'smtp.qq.com'

    return config


def send_email(subject=None, body_text=None, body_html=None,
               attachment_paths=None, download_url=None):
    """发送邮件（支持纯文本 + HTML 正文 + 附件 + 下载链接）

    Args:
        subject: 邮件主题（默认含日期）
        body_text: 纯文本正文
        body_html: HTML 正文（优先级高于 body_text）
        attachment_paths: 附件文件路径列表
        download_url: 趋势图下载链接（追加到正文末尾）

    Returns:
        bool: 发送成功返回 True，失败返回 False
    """
    config = _load_config()

    # 检查必填配置
    if not config['smtp_user']:
        logger.error("未设置 MAIL_USERNAME 环境变量，无法发送邮件")
        return False
    if not config['smtp_password']:
        logger.error("未设置 MAIL_PASSWORD 环境变量，无法发送邮件")
        return False
    if not config['recipients']:
        logger.error("未设置 MAIL_TO 环境变量，无法发送邮件")
        return False

    # 默认主题
    today = datetime.now().strftime('%Y-%m-%d')
    if subject is None:
        subject = f'【基金分析综合报告】{today}'

    logger.info(f"开始发送邮件：{subject}")

    try:
        # 创建邮件
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subject
        msg['From'] = config['smtp_user']
        msg['To'] = config['recipients']

        # ---- 构建正文 ----
        if body_html:
            # 使用 HTML 正文
            html_content = body_html
        elif body_text:
            # 将纯文本转为 HTML
            html_body = body_text.replace('\n', '<br>\n')
            html_content = f"""
            <html>
            <head><meta charset="utf-8">
            <style>
                body {{ font-family: 'Microsoft YaHei', 'SimHei', Arial, sans-serif; }}
                pre {{ font-family: 'Consolas', 'Courier New', monospace; font-size: 13px; line-height: 1.5; }}
            </style>
            </head>
            <body>
                <pre>{html_body}</pre>
            </body>
            </html>
            """
        else:
            html_content = f'<p>基金分析报告 - {today}</p>'

        # 追加下载链接
        if download_url:
            download_section = f"""
            <hr>
            <h3>📊 趋势图下载</h3>
            <p>趋势图文件已上传至 GitHub Release，请点击下方链接下载：</p>
            <p><a href="{download_url}">{download_url}</a></p>
            """
            # 在 </body> 前插入
            if '</body>' in html_content:
                html_content = html_content.replace('</body>', download_section + '\n</body>')
            else:
                html_content += download_section

        # 添加页脚
        footer = f"""
        <hr>
        <p style="color: #888; font-size: 12px;">
            本邮件由 GitHub Action 自动发送 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
        """
        if '</body>' in html_content:
            html_content = html_content.replace('</body>', footer + '\n</body>')
        else:
            html_content += footer

        msg.attach(MIMEText(html_content, 'html', 'utf-8'))

        # ---- 添加附件 ----
        if attachment_paths:
            for file_path in attachment_paths:
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    with open(file_path, 'rb') as f:
                        attachment = MIMEApplication(f.read())
                        filename = os.path.basename(file_path)
                        attachment.add_header(
                            'Content-Disposition', 'attachment',
                            filename=("utf-8", "", filename)
                        )
                        msg.attach(attachment)
                        logger.info(f"  已添加附件: {filename} ({os.path.getsize(file_path)} bytes)")
                else:
                    logger.warning(f"  附件不存在或为空: {file_path}")

        # ---- 发送邮件 ----
        logger.info(f"连接 SMTP 服务器: {config['smtp_server']}:{config['smtp_port']}")
        server = smtplib.SMTP_SSL(config['smtp_server'], config['smtp_port'])
        server.login(config['smtp_user'], config['smtp_password'])
        server.send_message(msg)
        server.quit()

        logger.info(f"邮件发送成功！收件人: {config['recipients']}")
        return True

    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP 认证失败，请检查 MAIL_USERNAME 和 MAIL_PASSWORD")
        return False
    except Exception as e:
        logger.error(f"邮件发送失败: {str(e)}")
        import traceback
        logger.error(f"堆栈: {traceback.format_exc()}")
        return False


def build_signal_html_report(signal_csv_path, index_analysis_text=None, report_date=None):
    """构建包含信号统计的 HTML 报告

    合并了 fund_signal 的信号统计功能和 ff 的宽基指数分析正文。

    Args:
        signal_csv_path: 信号明细 CSV 文件路径
        index_analysis_text: 宽基指数分析结果文本（可选）
        report_date: 报告日期

    Returns:
        str: HTML 格式的邮件正文
    """
    if report_date is None:
        report_date = datetime.now().strftime('%Y-%m-%d')

    import pandas as pd

    html_parts = [f"""
    <html>
    <body style="font-family: Arial, sans-serif;">
        <h2 style="color: #2c3e50;">📊 基金分析综合报告</h2>
        <div style="margin-bottom: 20px;">
            <strong>报告日期：</strong>{report_date}<br>
        </div>
    """]

    # 第一部分：宽基指数趋势分析
    if index_analysis_text:
        index_html = index_analysis_text.replace('\n', '<br>\n')
        html_parts.append(f"""
        <h3 style="color: #e74c3c;">📈 宽基指数趋势分析 (EMA)</h3>
        <pre style="font-family: 'Consolas', 'Courier New', monospace; font-size: 13px;
                     line-height: 1.5; background: #f8f8f8; padding: 10px;
                     border-left: 4px solid #e74c3c;">
{index_html}
        </pre>
        """)

    # 第二部分：基金信号统计
    if signal_csv_path and os.path.exists(signal_csv_path):
        try:
            signal_df = pd.read_csv(signal_csv_path)

            def count_signals(series):
                counts = series.value_counts().to_dict()
                return {
                    '买入': counts.get('买入', 0),
                    '卖出': counts.get('卖出', 0),
                    '持有': counts.get('持有', 0),
                    '机会买入': counts.get('机会买入', 0),
                    '提示风险': counts.get('提示风险', 0),
                }

            html_parts.append(f"""
        <h3 style="color: #3498db;">📊 基金技术信号统计</h3>
        <div style="margin-bottom: 15px;">
            <strong>分析基金数：</strong>{signal_df['基金代码'].nunique()}<br>
            <strong>总记录数：</strong>{len(signal_df)}<br>
        </div>
            """)

            # 各指标信号
            signal_indicators = [
                ('布林带信号', '🔶 布林带信号', '#e67e22'),
                ('均线信号', '🔷 均线信号', '#3498db'),
                ('RSI信号', '📊 RSI信号', '#2ecc71'),
                ('macd信号', '📈 MACD信号', '#9b59b6'),
                ('cci信号', '📉 CCI信号', '#1abc9c'),
            ]

            for col_name, title, color in signal_indicators:
                if col_name in signal_df.columns:
                    counts = count_signals(signal_df[col_name])
                    html_parts.append(f"""
            <h4 style="color: {color};">{title}</h4>
            <ul>
                <li>买入：<span style="color: #27ae60;">{counts['买入']}个</span></li>
                <li>机会买入：<span style="color: #2ecc71;">{counts['机会买入']}个</span></li>
                <li>卖出：<span style="color: #e74c3c;">{counts['卖出']}个</span></li>
                <li>提示风险：<span style="color: #e67e22;">{counts['提示风险']}个</span></li>
                <li>持有：<span style="color: #f39c12;">{counts['持有']}个</span></li>
            </ul>
                    """)

            # 买卖点策略信号
            strategy_cols = []
            if '稳健策略' in signal_df.columns:
                strategy_cols.append(('稳健策略', '🟢 稳健策略(买点2)', '#27ae60'))
            if '激进策略' in signal_df.columns:
                strategy_cols.append(('激进策略', '🔵 激进策略(买点5)', '#2980b9'))
            if '卖出信号' in signal_df.columns:
                strategy_cols.append(('卖出信号', '🔴 卖出信号', '#e74c3c'))

            if strategy_cols:
                html_parts.append("""
            <h3 style="color: #2c3e50;">🎯 买卖点策略信号</h3>
                """)
                for col_name, title, color in strategy_cols:
                    vc = signal_df[col_name].value_counts().to_dict()
                    items = ''.join([f'<li>{k}：<span style="color: {color};">{v}个</span></li>'
                                    for k, v in sorted(vc.items(), key=lambda x: -x[1])])
                    html_parts.append(f"""
            <h4 style="color: {color};">{title}</h4>
            <ul>{items}</ul>
                    """)
        except Exception as e:
            logger.warning(f"构建信号统计 HTML 失败: {e}")

    # 操作建议和风险提示
    html_parts.append(f"""
        <h3 style="color: #2c3e50;">💡 操作建议</h3>
        <ol>
            <li>买入/机会买入信号：关注基本面，考虑逐步建仓</li>
            <li>卖出/提示风险信号：评估持仓，考虑减仓或止盈</li>
            <li>持有信号：继续观察，等待明确信号</li>
        </ol>

        <h3 style="color: #2c3e50;">⚠️ 风险提示</h3>
        <ol>
            <li>技术指标仅供参考，不构成投资建议</li>
            <li>市场波动较大，建议结合基本面分析</li>
            <li>基金投资有风险，入市需谨慎</li>
        </ol>

        <p style="color: #7f8c8d;">祝投资顺利！</p>
    </body>
    </html>
    """)

    return '\n'.join(html_parts)
