"""
统一基金列表获取模块

封装 pywencai 调用，一次查询返回基金代码 + 名称 + 类型。
所有分析模块通过此模块获取基金列表，避免重复 API 请求。
"""

import os
import sys
import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import logger


def get_funds_from_wencai(query=None):
    """使用问财选股获取基金列表和详细信息

    Args:
        query: 问财查询语句，为None时从环境变量 WENCAI_QUERY 读取，
               环境变量也为空时使用默认值

    Returns:
        pandas.DataFrame: 包含 基金代码, 基金简称, 投资类型，持仓概念 等列的数据
        None: 查询失败时返回 None
    """
    # 优先级：参数 > 环境变量 > 默认值
    if query is None:
        query = os.environ.get('WENCAI_QUERY')
    if not query:
        query = '场外基金近1年涨幅top5，投资类型，概念'

    logger.info(f"使用问财选股获取基金列表，查询条件：{query}")

    try:
        import pywencai

        fund_data = pywencai.get(
            query=query,
            query_type="fund",
            loop=True,
            per_page=100,
            sleep=1,
            log=True,
        )

        if fund_data is None:
            logger.error("pywencai.get() 返回 None")
            return None

        if not isinstance(fund_data, pd.DataFrame):
            logger.error(f"问财返回类型异常: {type(fund_data)}")
            return None

        if fund_data.empty:
            logger.error("问财返回的数据为空")
            return None

        logger.info(f"问财返回 {len(fund_data)} 条基金记录")
        logger.info(f"返回数据列名：{list(fund_data.columns)}")

        # 查找基金代码列
        fund_code_cols = [col for col in fund_data.columns if '代码' in col or 'code' in col.lower()]
        if not fund_code_cols:
            logger.error("未找到基金代码字段")
            return None

        fund_code_col = fund_code_cols[0]
        logger.info(f"使用 '{fund_code_col}' 作为基金代码列")

        # 标准化基金代码列（去掉 .OF 等后缀，提取6位数字）
        fund_data['基金代码'] = fund_data[fund_code_col].astype(str).str.split('.').str[0]
        fund_data['基金代码'] = fund_data['基金代码'].str.zfill(6).str[:6]

        # 查找基金简称列
        fund_name_cols = [col for col in fund_data.columns if '简称' in col or '名称' in col]
        if fund_name_cols:
            if fund_name_cols[0] != '基金简称':
                fund_data.rename(columns={fund_name_cols[0]: '基金简称'}, inplace=True)
        else:
            fund_data['基金简称'] = '未知'

        # 查找投资类型列
        invest_type_cols = [col for col in fund_data.columns if '投资类型' in col or '类型' in col]
        if invest_type_cols:
            if invest_type_cols[0] != '投资类型':
                fund_data.rename(columns={invest_type_cols[0]: '投资类型'}, inplace=True)
        else:
            fund_data['投资类型'] = '未知类型'

        # 识别并保留"持仓"相关列（十大持仓、重仓持股等）
        holding_cols = [col for col in fund_data.columns if '持仓' in col or '重仓' in col]
        for col in holding_cols:
            clean_name = col.strip()
            if clean_name != col and clean_name not in fund_data.columns:
                fund_data.rename(columns={col: clean_name}, inplace=True)
        if holding_cols:
            logger.info(f"识别到持仓相关列: {holding_cols}")

        # 识别并保留"概念/主题"相关列（所属概念、投资主题等）
        concept_cols = [col for col in fund_data.columns if '概念' in col or '主题' in col or '板块' in col]
        if concept_cols:
            logger.info(f"识别到概念相关列: {concept_cols}")

        logger.info(f"获取到 {len(fund_data)} 只基金的列表数据")
        logger.info(f"最终保留列名: {list(fund_data.columns)}")
        return fund_data

    except Exception as e:
        logger.error(f"问财选股失败：{str(e)}")
        import traceback
        logger.error(f"堆栈信息：{traceback.format_exc()}")
        return None


def get_fund_codes(query=None):
    """获取基金代码列表（简化版，只返回代码列表）

    Args:
        query: 问财查询语句

    Returns:
        list: 基金代码字符串列表，如 ['000001', '110022', ...]
    """
    fund_data = get_funds_from_wencai(query)
    if fund_data is not None:
        codes = fund_data['基金代码'].tolist()
        logger.info(f"获取到 {len(codes)} 个基金代码")
        return codes
    return []
