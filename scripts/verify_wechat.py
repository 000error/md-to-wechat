#!/usr/bin/env python3
"""用微信官方检测器 (verify-article-structure-spec) 校验 HTML 合规性

用法：
    python verify_wechat.py <文章_wechat.html>

流程：先剥离 <style> 预览样式块（strip_preview_chrome，剥离后的 DOM 才等于
微信粘贴实际检测的内容），再调用官方 CLI（puppeteer + 本机 Chrome）跑全规则。

检测器首次部署：
    cd wechat-checker/cli
    PUPPETEER_SKIP_DOWNLOAD=true npm install   # 跳过 Chromium 下载，用系统 Chrome
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from md2wechat import strip_preview_chrome

SKILL_DIR = Path(__file__).parent.parent
CHECKER_CLI = SKILL_DIR / 'wechat-checker' / 'cli'

BROWSER_CANDIDATES = [
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
]


def find_browser():
    for p in BROWSER_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def verify(html_path):
    """校验 HTML 文件，返回 (是否合规, 检测器输出文本)"""
    if not (CHECKER_CLI / 'package.json').exists():
        return None, (f"官方检测器未安装: {CHECKER_CLI}\n"
                      f"安装方法见本文件 docstring（git clone + npm install）")
    browser = find_browser()
    if not browser:
        return None, "未找到 Chrome/Edge 浏览器，检测器需要 puppeteer 驱动"

    html = Path(html_path).read_text(encoding='utf-8')
    stripped = strip_preview_chrome(html)

    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False,
                                     encoding='utf-8') as f:
        f.write(stripped)
        tmp = f.name

    env = dict(os.environ)
    env['PUPPETEER_EXECUTABLE_PATH'] = browser
    try:
        proc = subprocess.run(
            ['npm.cmd', 'run', 'check', tmp],
            cwd=str(CHECKER_CLI), env=env,
            capture_output=True, timeout=300,
            encoding='utf-8', errors='replace',  # 检测器输出含 UTF-8 特殊字符，Windows 默认 GBK 会解码失败
        )
        output = (proc.stdout or '') + (proc.stderr or '')
    finally:
        os.unlink(tmp)

    ok = 'isValid：true' in output or 'isValid: true' in output
    return ok, output


def safe_print(text):
    """控制台安全打印：Windows GBK 控制台无法显示 ✗/━ 等符号，替换掉"""
    print(text.encode('gbk', errors='replace').decode('gbk', errors='replace'))


def main():
    parser = argparse.ArgumentParser(description='微信官方检测器合规校验')
    parser.add_argument('input', help='待校验的 HTML 文件路径')
    args = parser.parse_args()

    ok, output = verify(args.input)
    if ok is None:
        print(f"[跳过] {output}")
        sys.exit(2)

    # 只回显检测结果主体（去掉 puppeteer 弃用警告等噪音）
    lines = [l for l in output.splitlines()
             if l.strip() and 'Puppeteer' not in l and 'headless' not in l
             and 'chrome-for-testing' not in l and 'puppeteer' not in l.lower()]
    safe_print('\n'.join(lines))
    if ok:
        print('\n[合规] 官方检测器全规则通过')
        sys.exit(0)
    else:
        print('\n[违规] 存在不合规项，请根据上方节点信息修复')
        sys.exit(1)


if __name__ == '__main__':
    main()
