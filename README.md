# DeepSeek Monitor

Windows 系统托盘工具，实时显示 DeepSeek API 用量信息。

## 功能

- 系统托盘图标，点击弹出毛玻璃面板
- 显示账户余额、当日/本月消耗
- V4 Flash / V4 Pro 模型 token 用量详情
- 七日用量柱状图（月/周切换，按模型拆分 tooltip）
- 5 款主题：毛玻璃、科技风、极客、可爱、简约
- 窗口拖拽、位置记忆、点击外部自动隐藏

## 安装

```bash
# 创建虚拟环境
conda create -n deepseek-monitor python=3.12 -y
conda activate deepseek-monitor

# 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
python main.py
```

## 打包

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "DeepSeekMonitor" --add-data "web;web" --hidden-import keyring.backends.Windows --hidden-import pystray._win32 main.py
```

## 配置

1. 登录 [platform.deepseek.com](https://platform.deepseek.com)
2. F12 → Network → 复制任意 API 请求的 `Authorization` 和 `Cookie`
3. 粘贴到应用的设置页面

凭据存储在 Windows 凭据管理器中，其他设置在 `%APPDATA%\DeepSeekMonitor\config.json`

## 技术栈

- Python 3.12 + pywebview (WebView2)
- pystray 系统托盘
- Win32 API 亚克力毛玻璃
- Chart.js 图表
- keyring 凭据存储

## 项目结构

```
├── main.py              # 入口：托盘 + WebView + 桥接
├── api/deepseek.py      # Platform API 客户端
├── config/settings.py   # 配置管理
├── web/
│   ├── index.html       # 主界面 + 设置
│   ├── css/style.css    # 5 款主题样式
│   └── js/app.js        # 前端逻辑
├── build.py             # 打包脚本
└── requirements.txt
```
