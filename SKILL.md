---
name: "md-to-wechat"
description: "Markdown 转微信公众号 HTML 工具。用户给出 Markdown 文件路径即可全自动完成：图片迁移图床（配置已保存，无需询问）→ 转换带内联样式的公众号 HTML → 微信官方检测器自动合规校验。输出预览+粘贴双用途 HTML。触发词：转微信、转公众号、md转html、发布到公众号、排版。"
---

# Markdown 转微信公众号 HTML

## 使用场景

用户提供一个 Markdown 文件，希望转换为可直接粘贴进微信公众号编辑器的 HTML。本 skill 只做两件事：

1. **图片图床迁移**：检测文中所有图片，凡是不在用户指定图床上的（外链图、其他图床、本地图片），统一下载/上传到图床并替换链接
2. **格式转换**：将处理后的 Markdown 转换为带内联样式的微信公众号 HTML

不涉及文章创作、AI 配图等其它功能。

## 工作流程

### 第一步：图床配置（有已保存配置就跳过，别问用户）

**先读 `scripts/image_bed_config.json`：配置完整（provider + 密钥 + bucket + domain）就直接使用，整个流程无需任何对话确认，一口气跑完迁移、转换、合规校验并交付。**

仅当配置缺失或不完整时才询问用户：

- 询问使用哪个图床（目前脚本支持七牛云 qiniu）
- 七牛云需要 4 项：`access_key`、`secret_key`、`bucket`、`domain`（CDN 域名，不含 http:// 前缀）
- 用户提供后，用 Write/Edit 工具写入 `scripts/image_bed_config.json`（供脚本读取，之后永久免问），然后进入第二步
- 用户无法提供时，告知无法完成图床迁移，询问是否跳过迁移直接转换（见第三步）

### 第二步：迁移图片到图床

在 `scripts/` 目录下执行：

```bash
cd <skill目录>/scripts
python migrate_images.py <用户md文件路径> --output <输出md路径>
```

脚本行为：
- 扫描 `![](url)` 和 `<img src="...">` 两种图片引用
- 图片 URL 的域名与配置图床域名一致 → 跳过
- 外链图片 → 下载后上传图床，替换为新 URL
- 本地图片（相对路径基于 md 文件所在目录解析）→ 直接上传图床，替换为新 URL
- 输出新 Markdown 文件（默认 `<原名>_hosted.md`），原文件不改动

向用户简要报告迁移结果：共几张图、几张已在图床、几张新迁移、几张失败。
如有失败（网络错误、本地文件缺失等），列出失败的图片并请用户确认是否继续转换。

**如果文章没有任何图片**，跳过本步，直接用原文件进入第三步。

### 第三步：转换为微信公众号 HTML

```bash
python md2wechat.py <上一步输出的md文件> --output <输出html路径>
```

- 默认使用 `scripts/styles/default.json` 样式
- 输出完整 HTML 文件（默认 `<原名>_wechat.html`）
- **输出文件是"预览 + 粘贴"双用途**：浏览器打开时显示灰底白卡片的手机端预览效果（预览样式只写在 `<style>` 里、不含任何 class/内联样式，复制粘贴时不会带进微信）；全选复制粘贴到微信编辑器得到的就是纯净的文章内容
- **合规验证注意**：用微信官方检测器（verify-article-structure-spec）验证时，需先用 `md2wechat.py` 里的 `strip_preview_chrome()` 去掉 `<style>` 预览样式块再跑——检测引擎会把计算样式内联实测，预览卡片会引入与粘贴结果无关的误报

**默认样式标准（v1.0.0，2026-09-30 用户定稿的"135 编辑器疏朗风"，参照特工宇宙等主流公众号排版逐项校准）**：

- **正文/列表**：字号 15px、字间距 2px、行高 30px（2 倍）、段距 26px（≈空一行）、两端对齐（justify）——"低密度留白"排版：小字 + 宽字距 + 松行距 + 空行段距
- **标题字号层级**：h1 = 24px、h2 = 21px、h3 = 19px、h4 = 16px（h5/h6 = 16px）；**标题上间距为基础值 1.5 倍**（h1 36px、h2 38px、h3 28.5px、h4 38px、h5/h6 1.2em），与上文拉开、与下文贴近；h4 左侧 3px 黑色竖线装饰
- **图片**：通栏全宽（图片段落左右边距归零，等效微信"自适应"效果）、8px 圆角、无阴影
- **引用块**：浅灰细竖线（2px, rgb(216,216,216)）+ 文字缩进 18px + 灰字（rgb(127,127,127)）左对齐（引用内段落用独立样式项 `blockquote_p`，避免长 URL 被两端对齐拉散）
- **表格**：字号 15px，行高 1.6；行内代码 15px；代码块 13px/22.75px 深色底，按行拆分 + nbsp/零宽空格处理折行
- **容器**：15px / 30px / 字距 2px，不设 font-family（官方规范第 3 章）

**Markdown 源文件排版约定（配套）**：文章中的「功能 / 工作机制 / 作者介绍」等栏目标签统一使用 `####` 四级标题（不用加粗正文或列表项），标题独占一行、内容另起一行，保证转换后层级一致。

### 第四步：合规验证（自动，务必保留）

`md2wechat.py` 转换完成后会**自动调用微信官方检测器**（`wechat-checker/`，即官方开源的 verify-article-structure-spec 本地副本）对输出 HTML 跑全规则校验：

- 验证前会先剥离 `<style>` 预览样式块（`strip_preview_chrome`），检测结果等于微信粘贴后的实际内容
- 输出 `[检测通过]` 才算完成；输出 `[检测未通过]` 时转换以退出码 1 结束，**必须根据违规节点修复样式后重新转换**
- 可用 `--no-verify` 跳过（仅调试时用）
- 单独校验已有 HTML：`python verify_wechat.py <html文件>`

**硬性规则：每次修改 `styles/default.json` 或 `md2wechat.py` 的格式相关代码后，必须跑一次全格式回归**：

```bash
python md2wechat.py tests/full_format_fixture.md --output /tmp/regression.html
```

`tests/full_format_fixture.md` 覆盖了标题/长段落/加粗折行/列表/代码块/表格/图片/引用等全部格式，能触发历史上所有误报场景。检测通过才可交付。

**检测器首次部署**（skill 克隆到新机器后）：

```bash
cd wechat-checker
git clone https://github.com/wechatjs/verify-article-structure-spec.git .
cd cli && PUPPETEER_SKIP_DOWNLOAD=true npm install   # 跳过 Chromium 下载，用系统 Chrome
```

### 第五步：交付

向用户报告生成的文件路径，并提示：
> 用浏览器打开 HTML 文件，全选复制（Ctrl+A, Ctrl+C），粘贴到微信公众号编辑器即可。

## 依赖

```bash
pip install -r scripts/requirements.txt   # markdown, qiniu
```

首次运行如报 `ModuleNotFoundError`，先执行上述安装命令。

## 输出文件

```
<原md所在目录>/
├── 文章.md                # 用户原始文件（不改动）
├── 文章_hosted.md          # 图片已迁移到图床的 Markdown
└── 文章_wechat.html        # 微信公众号 HTML
```

## 注意事项

1. **不修改原文内容**：除图片 URL 替换外，不改动文章的任何文字
2. **配置安全**：图床密钥由用户每次运行时通过对话提供，只写入 `scripts/image_bed_config.json` 供脚本读取，不要回显给用户或上传到任何地方；`image_bed_config.json` 默认保持为空，不预置任何密钥
3. **图床扩展**：当前仅实现七牛云。用户要求其它图床（阿里云 OSS、腾讯云 COS）时，告知需要扩展 `migrate_images.py` 中的 uploader 类，可按 QiniuUploader 的模式协助添加
4. **失败的图片**：迁移失败的图片保留原链接并在报告中明确指出，由用户决定继续还是处理后重试

## 常见错误

| 错误 | 原因与解决 |
|------|-----------|
| `配置文件不存在` | 确认 `scripts/image_bed_config.json` 存在 |
| `图床配置不完整` | 回到第一步，通过对话索取并写入配置 |
| `Upload failed` | 检查七牛密钥、bucket、domain 是否正确，存储空间是否有配额 |
| `暂不支持的图床` | 仅支持 qiniu，需扩展脚本 |
| `ModuleNotFoundError: qiniu/markdown` | 执行 `pip install -r scripts/requirements.txt` |
| `本地图片不存在` | 本地图片路径基于 md 文件所在目录解析，检查相对路径是否正确 |
