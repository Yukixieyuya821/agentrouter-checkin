# AgentRouter 每日签到

自动为 [AgentRouter](https://agentrouter.org) 站点每日签到领取免费额度，并通过 **SMTP 邮件**发送通知。

**支持两种模式：**
- **单用户模式**：配置 `AGENTROUTER_USERNAME` + `AGENTROUTER_PASSWORD`
- **多用户模式**：配置 `AGENTROUTER_ACCOUNTS`（允许多个账号批量签到）

---

## 一、准备工作

1. 用 GitHub 登录 https://agentrouter.org。
2. **绑定邮箱并设置密码**：进入「个人设置」→ 绑定邮箱并设置登录密码。
   - 登录时选择「邮箱」或「用户名」+ 密码登录；如需修改密码，可使用「忘记密码」。
3. **代理（可选）**：直连不可用时，准备 SOCKS5 / HTTP 代理，或含节点的 Clash / Mihomo 配置文件（Actions 可自动启动代理内核，见下文）。
4. **准备 SMTP 服务**：例如 Gmail、QQ 邮箱、企业邮箱或其他支持 SMTP 的邮箱服务。若服务商要求，请使用 SMTP 授权码而非网页登录密码。

---

## 二、配置

建议将密码、SMTP 授权码等敏感内容配置为 GitHub Actions 的 **Secrets**；普通地址或主机名可配置为 **Variables**。本地运行时，脚本会自动读取与 `checkin.py` 同目录的 `.env` 文件，已有的系统环境变量优先于 `.env`。

### 本地 `.env` 配置

复制示例文件并填写实际配置：

```powershell
Copy-Item .env.example .env
pip install -r requirements.txt
python checkin.py
```

脚本使用 `checkin.py` 所在目录定位 `.env`，因此从其他工作目录启动也能正确读取。`.env` 已加入 `.gitignore`，不会被 Git 提交；请勿把真实账号密码或 SMTP 授权码写入 `.env.example`。

### 账号配置

#### 单用户模式（二选一）

| 环境变量 | 值 | 说明 |
|--------------|-----|------|
| `AGENTROUTER_USERNAME` | `你的邮箱或用户名` | 登录账号，邮箱或 `github_<ID>`（**必需**） |
| `AGENTROUTER_PASSWORD` | `你的登录密码` | 登录密码（**必需**） |

#### 多用户模式（二选一）

| 环境变量 | 值 | 说明 |
|--------------|-----|------|
| `AGENTROUTER_ACCOUNTS` | `user1:pass1,user2:pass2` | 多账号列表（**替代**单用户模式） |

`AGENTROUTER_ACCOUNTS` 格式说明：
- 每个条目：`用户名:密码`
- 多个条目用**英文逗号**或**换行**分隔。
- user id 从登录响应自动获取，无需手动填写。
- 示例：
  ```
  admin@example.com:pass123
  test@example.com:pass456,admin2:pass789
  ```

### 邮件通知配置

| 环境变量 | 必需 | 示例 | 说明 |
|---|---:|---|---|
| `SMTP_HOST` | 是 | `smtp.gmail.com` | SMTP 服务器地址 |
| `SMTP_PORT` | 否 | `465` | SMTP 端口；未配置时，`ssl` 默认 `465`、`starttls` 默认 `587`、`none` 默认 `25` |
| `SMTP_SECURITY` | 否 | `ssl` | 加密方式：`ssl`（默认）、`starttls` 或 `none` |
| `SMTP_USERNAME` | 否 | `sender@example.com` | SMTP 登录用户名；不需要认证的服务器可不配 |
| `SMTP_PASSWORD` | 视服务商而定 | `smtp-app-password` | SMTP 登录密码或授权码；仅当配置了 `SMTP_USERNAME` 时用于登录 |
| `EMAIL_FROM` | 是 | `sender@example.com` | 发件人邮箱。也可写为 `签到机器人 <sender@example.com>` |
| `EMAIL_FROM_NAME` | 否 | `AgentRouter 签到机器人` | 发件人显示名称；会覆盖 `EMAIL_FROM` 中的显示名称 |
| `EMAIL_TO` | 是 | `owner@example.com,backup@example.com` | 收件人邮箱；支持逗号、分号或换行分隔多个收件人 |

> 未完整配置 `SMTP_HOST`、`EMAIL_FROM` 或 `EMAIL_TO` 时，签到仍会尝试执行，但结果邮件无法发送，工作流会标记失败。失败通知同样需要有效的 SMTP 配置。

#### GitHub Actions 环境变量传递示例

```yaml
env:
  AGENTROUTER_USERNAME: ${{ secrets.AGENTROUTER_USERNAME || vars.AGENTROUTER_USERNAME }}
  AGENTROUTER_PASSWORD: ${{ secrets.AGENTROUTER_PASSWORD || vars.AGENTROUTER_PASSWORD }}
  SOCKS5_PROXY: ${{ secrets.SOCKS5_PROXY || vars.SOCKS5_PROXY }}
  SMTP_HOST: ${{ secrets.SMTP_HOST || vars.SMTP_HOST }}
  SMTP_PORT: ${{ secrets.SMTP_PORT || vars.SMTP_PORT }}
  SMTP_SECURITY: ${{ secrets.SMTP_SECURITY || vars.SMTP_SECURITY }}
  SMTP_USERNAME: ${{ secrets.SMTP_USERNAME || vars.SMTP_USERNAME }}
  SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
  EMAIL_FROM: ${{ secrets.EMAIL_FROM || vars.EMAIL_FROM }}
  EMAIL_FROM_NAME: ${{ secrets.EMAIL_FROM_NAME || vars.EMAIL_FROM_NAME }}
  EMAIL_TO: ${{ secrets.EMAIL_TO || vars.EMAIL_TO }}
```

### GitHub Actions 使用 Clash / Mihomo 节点文件

不需要让自己的电脑开机，也不需要在电脑上启动代理软件。工作流会在 GitHub 的 Ubuntu 运行器中下载固定版本的 [Mihomo 内核](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.28)、校验 SHA-256、启动代理，签到结束后关闭内核并删除临时配置。

1. 在项目目录打开 PowerShell，运行以下命令（将路径替换为自己的配置文件）：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\encode_mihomo.ps1 -ConfigPath 'C:\path\to\your\mihomo-config.yaml'
   ```

   此命令仅对本次 PowerShell 进程放开脚本执行，不修改系统执行策略。脚本将文件进行 gzip 压缩和 Base64 编码，结果直接复制到剪贴板，不会打印节点密码。压缩用于满足 [GitHub Secret 的 48 KB 限制](https://docs.github.com/en/actions/reference/security/secrets)；编码本身不是加密，请把结果当作密码保管。

2. 在仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中，新建 **`MIHOMO_CONFIG_B64`**，粘贴剪贴板内容并保存。不要把原始文件或编码内容提交到 Git。
3. 将更新后的代码和工作流推送到 GitHub，在 **Actions → AgentRouter 每日签到 → Run workflow** 手动运行一次。

配置了 `MIHOMO_CONFIG_B64` 后，无需另外填写 `SOCKS5_PROXY`。工作流为每个节点创建一个仅运行器本机可访问的代理端口，签到脚本按文件顺序请求 AgentRouter 的 `/api/status`，选择首个返回成功 JSON 的节点；全部失败后仍按原逻辑尝试直连。节点越靠后，等待可能越久（每次请求超时 25 秒）。已有 `SOCKS5_PROXY` 在该模式下会被节点端口列表覆盖。

支持 YAML 中 `proxies` 下直接列出的节点（包括 Shadowsocks）。只提供订阅 URL / `proxy-providers` 的文件以及依赖 `dialer-proxy` 的链式代理不适用。运行器提取节点和 `hosts`，不沿用桌面端的分流规则、DNS 监听和管理面板；节点协议仍须由该版本 Mihomo 支持。使用 [Mihomo 的 listener `proxy` 字段](https://wiki.metacubex.one/en/config/inbound/listeners/) 将各端口绑定到对应节点。

删除 `MIHOMO_CONFIG_B64` 后，工作流恢复使用原有 `SOCKS5_PROXY` 或直连。节点失效时，重新编码更新后的文件并替换 Secret。

### 通用变量（两种模式都可使用）

| 环境变量 | 值 | 说明 |
|--------------|-----|------|
| `SOCKS5_PROXY` | `socks5://user:pass@host:1080` | SOCKS5 代理地址（可选），支持换行/逗号分隔多个代理 |
| `AGENTROUTER_BASE_URL` | `https://agentrouter.org` | 站点地址（可选，默认值如示例） |

### 模式判定逻辑

| 条件 | 模式 |
|------|------|
| `AGENTROUTER_USERNAME` 和 `AGENTROUTER_PASSWORD` 都存在 | **单用户模式** |
| 缺少 `AGENTROUTER_USERNAME` / `AGENTROUTER_PASSWORD` 任一，且 `AGENTROUTER_ACCOUNTS` 存在 | **多用户模式** |
| 以上均不满足 | 脚本报错退出 |

> 若两种模式都配置了，单用户优先。

---

## 三、邮件通知内容

### 单用户模式

邮件标题示例：`AgentRouter 签到通知 - 2026年08月27日`

邮件正文包括：
- 日期
- 脱敏后的签到账号
- 签到结果（新签到或今日已签到）
- 当前余额

### 多用户模式

邮件标题示例：`AgentRouter 签到汇总 - 2026年08月27日（3 个账号）`

正文以表格形式列出每个账号的签到结果与余额，并在末尾汇总成功账号的总余额。失败账号计入账号总数，但不计入总余额。

### 执行失败通知

GitHub Actions 任一步骤失败后，会启动独立的 `notify_failure` 作业，发送主题为 `AgentRouter 执行失败通知 - 日期` 的邮件。内容包含仓库、工作流、失败步骤、运行次数和本次 Actions 日志链接；不附加原始日志或节点配置。

- 覆盖检出代码、设置 Python、安装依赖、安装/启动代理、连接测试全部失败、登录签到失败，以及未处理异常。
- 查询余额失败会报告错误，不再显示为 `$0.00`。多账号模式会继续处理后续账号，并在汇总邮件中列出失败；任一账号失败都会让工作流标记失败。汇总邮件已成功发出时，不重复发送同一账号失败的通知。
- 结果邮件发送失败也会让工作流标记失败，并触发失败通知重试。
- 失败通知使用新的运行器、自带 Python 3 和标准库，不需要安装项目依赖或启动代理。SMTP 设置沿用现有 Secrets / Variables；发送失败最多尝试三次，间隔五秒，仍失败则在通知作业中明确报错。

不需要新增 Secret。SMTP 配置缺失、授权码错误或邮件服务器不可达时，邮件仍无法送达；GitHub 无法启动通知作业、通知代码检出失败或整个运行被取消时，也不能保证通知。单个代理不可用后成功切换节点属于恢复成功，不会单独触发失败邮件。

---

## 四、常见错误

| 错误日志 | 含义与处理 |
|---------|-----------|
| `aliyun_waf` | 请求被阿里云 WAF 拦截，当前 IP（或代理）不可用，请检查/更换 `SOCKS5_PROXY` |
| `用户名或密码错误` | 确认已在网站「个人设置」绑定邮箱并设置密码，且用户名/邮箱正确 |
| `未配置账号信息` | 未设置任何账号变量，请检查 `AGENTROUTER_USERNAME`+`AGENTROUTER_PASSWORD` 或 `AGENTROUTER_ACCOUNTS` |
| `AGENTROUTER_ACCOUNTS 解析后无有效账号` | `AGENTROUTER_ACCOUNTS` 格式错误，请检查是否遗漏冒号分隔符 |
| `缺少邮件配置` | 当前运行未读到 `SMTP_HOST`、`EMAIL_FROM` 或 `EMAIL_TO`；请在仓库 Actions 的 Secrets 或 Variables 中补齐同名配置（Secrets 优先）。本地 `.env` 不会自动上传到 Actions。更新工作流后请在最新分支上使用 Run workflow 创建新运行 |
| `SMTP_SECURITY 仅支持 ssl、starttls 或 none` | `SMTP_SECURITY` 配置值错误 |
| `邮件通知发送失败` | 检查 SMTP 主机、端口、加密方式、账号、授权码及发件人地址是否与服务商要求一致 |
