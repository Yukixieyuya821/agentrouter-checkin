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
3. **准备代理**：一个能访问该站点且未被 WAF 拦截的 SOCKS5 / HTTP 代理（国内 / 香港 / 新加坡 IP）。
4. **准备 SMTP 服务**：例如 Gmail、QQ 邮箱、企业邮箱或其他支持 SMTP 的邮箱服务。若服务商要求，请使用 SMTP 授权码而非网页登录密码。

---

## 二、配置

建议将密码、SMTP 授权码等敏感内容配置为 GitHub Actions 的 **Secrets**；普通地址或主机名可配置为 **Variables**。脚本本身均通过环境变量读取，本地配置可参考 `.env.example`。

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

> 未完整配置 `SMTP_HOST`、`EMAIL_FROM` 或 `EMAIL_TO` 时，签到仍会继续完成，但会记录日志并跳过邮件发送。

#### GitHub Actions 环境变量传递示例

```yaml
env:
  AGENTROUTER_USERNAME: ${{ secrets.AGENTROUTER_USERNAME || vars.AGENTROUTER_USERNAME }}
  AGENTROUTER_PASSWORD: ${{ secrets.AGENTROUTER_PASSWORD || vars.AGENTROUTER_PASSWORD }}
  SOCKS5_PROXY: ${{ secrets.SOCKS5_PROXY || vars.SOCKS5_PROXY }}
  SMTP_HOST: ${{ vars.SMTP_HOST }}
  SMTP_PORT: ${{ vars.SMTP_PORT }}
  SMTP_SECURITY: ${{ vars.SMTP_SECURITY }}
  SMTP_USERNAME: ${{ secrets.SMTP_USERNAME || vars.SMTP_USERNAME }}
  SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
  EMAIL_FROM: ${{ secrets.EMAIL_FROM || vars.EMAIL_FROM }}
  EMAIL_FROM_NAME: ${{ vars.EMAIL_FROM_NAME }}
  EMAIL_TO: ${{ secrets.EMAIL_TO || vars.EMAIL_TO }}
```

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

---

## 四、常见错误

| 错误日志 | 含义与处理 |
|---------|-----------|
| `aliyun_waf` | 请求被阿里云 WAF 拦截，当前 IP（或代理）不可用，请检查/更换 `SOCKS5_PROXY` |
| `用户名或密码错误` | 确认已在网站「个人设置」绑定邮箱并设置密码，且用户名/邮箱正确 |
| `未配置账号信息` | 未设置任何账号变量，请检查 `AGENTROUTER_USERNAME`+`AGENTROUTER_PASSWORD` 或 `AGENTROUTER_ACCOUNTS` |
| `AGENTROUTER_ACCOUNTS 解析后无有效账号` | `AGENTROUTER_ACCOUNTS` 格式错误，请检查是否遗漏冒号分隔符 |
| `缺少邮件配置` | 未配置 `SMTP_HOST`、`EMAIL_FROM` 或 `EMAIL_TO`；补齐后即可发送邮件 |
| `SMTP_SECURITY 仅支持 ssl、starttls 或 none` | `SMTP_SECURITY` 配置值错误 |
| `邮件通知发送失败` | 检查 SMTP 主机、端口、加密方式、账号、授权码及发件人地址是否与服务商要求一致 |
