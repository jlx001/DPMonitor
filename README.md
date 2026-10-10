# DeepSeek Monitor

Windows 系统托盘工具，实时显示 DeepSeek API 用量信息。

## 功能

- 系统托盘图标，点击弹出毛玻璃面板
- 显示账户余额、当日/本月消耗
- 按平台接口动态展示各模型 token 用量详情：模型名全部来自接口，
  主界面只显示当日有调用记录的模型（模型重命名或新增无需改代码，
  设置里可永久隐藏指定模型）
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

运行日志写在 `%APPDATA%\DeepSeekMonitor\app.log`（便于开机自启时排查）。

### 网络与代理

应用默认直连 DeepSeek 接口，忽略环境变量代理与 Windows 系统代理；
设置页的“使用系统代理”开关打开后，余额查询、平台用量与网关转发都会
改用系统代理（保留系统绕过列表语义）。glass 主题背景图随程序打包，
界面本身不再请求外部资源。

另有“绕过虚拟网卡/VPN”开关（默认开启）：开启时出网 socket 绑定物理网卡
地址（自动探测，可在配置里用 `direct_interface_ip` 手填），FlyingBird 等
TAP/TUN 虚拟网卡不会再接管监控程序与 Codex 转发流量；探测不到物理网卡
或关闭该开关时，按系统默认路由出网。该开关与“使用系统代理”互斥。

### 开机自启

开启后同时写入两个登录触发点，任一失效仍可启动：

- 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- 启动文件夹快捷方式 `...\Start Menu\Programs\Startup\DeepSeekMonitor.lnk`

程序每次启动都会校验这两个位置是否指向当前可执行文件（换版本、挪目录后自动
修正），设置页会显示校验结果；重复触发由单实例互斥锁兜底，不会启动两份。
启动更新版本时会结束正在运行的旧版本并由新版本接管，旧版本不会再顶掉新版。

## 多 SK 智能调度网关（Codex 接入）

应用内置一个本地网关（127.0.0.1:8787），可为 Codex 配置多个 DeepSeek SK，
按对话绑定并智能分摊用量。

### 接入步骤

1. 打开应用 → 设置 → “SK 管理”
2. 新增至少两个 SK：填写名称、API Key、配额权重（如 sk1=1、sk2=2 即 1/3、2/3）、
   每日/每月费用上限、可用时段，可勾选一个默认 SK 用于兜底
3. 点击“接入网关”：自动备份并修改 `~/.codex/config.toml`，
   把 `[model_providers.deepseek]` 的 `base_url` 指向本地网关
4. 重启一次 Codex 生效（仅此一次；之后切换 SK 无需重启）

### 调度规则

- 一段对话从建立到结束固定使用同一个 SK，对话内不切换
- 新建对话时按“目标份额 − 实际份额”选择最欠账的 SK，趋近配置的配额比例
- 单对话费用超过阈值（默认 5 元）时弹窗提示建议新建对话
- 服务器方错误：401 自动切换健康 SK 并重试；402/429/5xx 中断对话并透传错误，
  对应 SK 标记熔断，新对话不再选它
- SK 费用上限/时段等本地限制只提示不中断，由用户决定扩限或结束

### 还原

SK 管理页点击“还原直连”即可恢复备份的 config.toml（重启 Codex 生效）。

### 说明

- SK 明文存于 Windows 凭据管理器，网关仅监听 127.0.0.1
- 费用由响应 usage × 价格表估算（价格可在 SK 管理页修改），
  并通过 `/user/balance` 轮询校准真实余额
- 用量数据存于 `%APPDATA%\DeepSeekMonitor\usage.db`

### 模型价格

价格表按平台返回的模型名分别配置，单位元/百万 token：

| 模型 | 闲时（缓存命中/未命中/输出） | 高峰 |
| --- | --- | --- |
| deepseek-flash（V4.1-Flash） | 0.02 / 1 / 4 | ×2 |
| deepseek-v4-pro（V4-Pro-0813） | 0.15 / 4.5 / 13.5 | ×2 |
| deepseek-v4-flash、…-vision-exp、…-expires-on-0910 | 同 flash | ×2 |
| 其他模型 | 取默认价（同 flash） | ×2 |

默认值来自官方刊例价（USD × 6.67），并用本账号账单逐日反推核对：闲时为高峰
一半，高峰时段为周一至周五 09:00-12:00、14:00-18:00（对应 UTC 01:00-04:00、
06:00-10:00）。SK 管理页可选中模型逐个改价。

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
