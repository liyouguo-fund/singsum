# 基金分析综合系统

整合了以下两个项目，统一为一个分析系统，减少资源占用：

- **[ff](https://github.com/liyouguo-fund/ff)**: 宽基指数EMA趋势分析 + 场外基金WMA趋势分析（含趋势图）
- **[fund_signal](https://github.com/liyouguo/fund_signal)**: 场外基金技术指标信号分析（MA/RSI/MACD/CCI/布林带）

## 📋 项目简介

每天北京时间 **9:00** 自动运行三个分析模块，并通过 **QQ邮箱** 发送一份综合分析报告邮件：

1. **宽基指数趋势分析 (EMA)** — 分析A股主要指数和ETF的趋势信号
2. **场外基金趋势分析 (WMA)** — 分析场外基金趋势，生成Excel表格和趋势图
3. **基金技术信号分析** — 计算MA/RSI/MACD/CCI/布林带等技术指标，生成买卖信号

## 📁 项目结构

```
fund_analysis_system/
├── .github/workflows/
│   └── daily_report.yml          # 统一 GitHub Actions Workflow
├── core/
│   ├── __init__.py
│   ├── logger.py                 # 日志模块
│   ├── email_sender.py           # 统一邮件发送模块
│   └── fund_fetcher.py           # 共享基金列表获取（pywencai）
├── analysis/
│   ├── __init__.py
│   ├── index_trend_ema.py        # 宽基指数EMA趋势分析
│   ├── fund_trend_wma.py         # 场外基金WMA趋势分析
│   └── fund_signal.py            # 基金技术信号分析
├── requirements.txt              # Python依赖
└── README.md
```

## 🚀 部署步骤

### 1. Fork 或克隆本仓库

```bash
git clone <your-repo-url>
cd fund_analysis_system
```

### 2. 配置 GitHub Secrets

在仓库或组织页面：**Settings → Secrets and variables → Actions → Secrets**

> 组织级 Secrets 和仓库级 Secrets 使用方式完全相同（`${{ secrets.XXX }}`），组织级会自动继承到所有仓库。

| Secret 名称 | 必填 | 说明 | 示例值 |
|------------|------|------|--------|
| `MAIL_USERNAME` | ✅ | 邮箱地址 | `724429664@qq.com` |
| `MAIL_PASSWORD` | ✅ | 邮箱SMTP授权码 | `xxxxxxxxxxxxxx` |
| `MAIL_TO` | ✅ | 收件人邮箱地址 | `724429664@qq.com` |
| `MAIL_SMTP_SERVER` | ❌ | SMTP服务器地址 | `smtp.qq.com` |
| `MAIL_SMTP_PORT` | ❌ | SMTP服务器端口 | `465` |
| `WENCAI_QUERY` | ❌ | 问财查询语句 | `场外基金近1年涨幅top200` |

> **注意**：原来 fund_signal 项目使用 `SMTP_USER`/`SMTP_PASSWORD`/`RECIPIENTS`，整合后统一使用 `MAIL_*` 前缀。

### 3. 启用 GitHub Actions 权限

进入 Settings → Actions → General：
- 勾选 "Read and write permissions"
- 勾选 "Allow GitHub Actions to create and approve pull requests"

### 4. 手动触发测试

1. 进入 Actions 标签页
2. 选择 "每日基金分析综合报告" workflow
3. 点击 "Run workflow" 手动触发

## 📧 邮件内容说明

一封邮件包含所有分析结果：

- **正文**：宽基指数EMA趋势表格 + 基金技术信号统计
- **附件**：基金趋势分析Excel + 信号明细CSV
- **下载链接**：趋势图打包下载（GitHub Release）

## 🔧 自定义配置

### 修改分析时间

编辑 `.github/workflows/daily_report.yml` 中的 cron 表达式（UTC时间）：

```yaml
schedule:
  - cron: '0 1 * * *'   # UTC 1:00 = 北京时间 9:00
```

### 修改问财查询语句

方式一（推荐）：在 GitHub Secrets 中设置 `WENCAI_QUERY`
方式二：手动触发时在 `wencai_query` 输入框中填写

### 修改宽基指数列表

编辑 `analysis/index_trend_ema.py` 中的 `DEFAULT_INDICES` 列表。

## 📊 分析指标说明

### 宽基指数 (EMA)
- 趋势线 = (最高价+最低价)/2 的 20日 EMA
- 偏离率 = (现价-趋势线)/趋势线 × 100%

### 场外基金趋势 (WMA)
- 趋势线 = 5日高低价均值的 20日 WMA
- 偏离率 + 布林带 + 均线多头排列

### 技术信号
- MA均线、RSI、MACD、CCI、布林带 五大指标
- 信号类型：买入、卖出、机会买入、提示风险、持有

## ⚠️ 风险提示

- 技术指标仅供参考，不构成投资建议
- 基金投资有风险，入市需谨慎
- 建议结合基本面分析综合判断

## 📄 许可证

MIT License
