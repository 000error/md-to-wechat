#!/usr/bin/env python3
"""Markdown to WeChat HTML Converter - Converts Markdown to WeChat-styled HTML"""

import argparse
import markdown
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


def load_style_from_file(style_file='styles/default.json'):
    """Load style mapping from JSON file"""
    style_path = Path(__file__).parent / style_file
    with open(style_path, 'r', encoding='utf-8') as f:
        return json.load(f)


class StyleInjector(HTMLParser):
    """Injects inline styles into HTML elements"""

    def __init__(self, style_map):
        super().__init__()
        self.style_map = style_map
        self.output = []
        self.in_pre = False
        self.in_blockquote = False

    def handle_starttag(self, tag, attrs):
        if tag == 'pre':
            self.in_pre = True
        if tag == 'blockquote':
            self.in_blockquote = True

        attrs_dict = dict(attrs)

        # Special handling for code inside pre
        # pre-wrap 允许折行（否则 pre 规则判水平溢出）；折行碎片的解决见
        # restructure_code_blocks（&nbsp; + 零宽空格）
        if tag == 'code' and self.in_pre:
            style = 'font-family: Menlo, Consolas, Monaco, monospace; font-size: 13px; padding: 0.5em 1em 1em; color: rgb(201, 209, 217); line-height: 22.75px; white-space: pre-wrap; display: block;'
        # 引用块内的段落用专用样式（灰字、左对齐、无装饰，长 URL 不会被
        # 两端对齐拉散），blockquote_p 缺省时退回普通段落样式
        elif tag == 'p' and self.in_blockquote:
            style = self.style_map.get('blockquote_p') or self.style_map.get(tag, '')
        else:
            style = self.style_map.get(tag, '')

        if style:
            attrs_dict['style'] = style

        attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs_dict.items())
        self.output.append(f'<{tag} {attrs_str}>' if attrs_str else f'<{tag}>')

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_pre = False
        if tag == 'blockquote':
            self.in_blockquote = False
        self.output.append(f'</{tag}>')

    def handle_data(self, data):
        self.output.append(data)

    def handle_startendtag(self, tag, attrs):
        attrs_dict = dict(attrs)
        style = self.style_map.get(tag, '')
        if style:
            attrs_dict['style'] = style
        attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs_dict.items())
        self.output.append(f'<{tag} {attrs_str} />' if attrs_str else f'<{tag} />')

    def get_output(self):
        return ''.join(self.output)


# 需要把内容包进 <span> 的块级标签（规避检测器对内联元素折行的"叠字"误报，
# 详见 wrap_paragraph_contents 注释）
WRAP_TAGS = {'p', 'li', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
# li 内出现这些标签时先闭合 span，避免块级元素嵌进内联 span
LIST_TAGS = {'ul', 'ol'}


class BlockContentWrapper(HTMLParser):
    """把 p/li/td/th/h1-h6 的直接内容包进 <span>。

    用流式解析而非正则，保证嵌套列表（li 内含 ul/ol）结构不被破坏：
    li 内遇到嵌套列表时先闭合 span，列表结束后再不续包。
    """

    def __init__(self):
        super().__init__()
        self.output = []
        self.stack = []  # 每层记录 (tag, span_open)

    def _emit_tag(self, tag, attrs, self_close=False):
        attrs_str = ' '.join(f'{k}="{v}"' if v is not None else k for k, v in attrs)
        if self_close:
            self.output.append(f'<{tag} {attrs_str} />' if attrs_str else f'<{tag} />')
        else:
            self.output.append(f'<{tag} {attrs_str}>' if attrs_str else f'<{tag}>')

    def handle_starttag(self, tag, attrs):
        # li 的 span 内遇到嵌套列表：先闭合 span，列表留在外面
        if tag in LIST_TAGS and self.stack and self.stack[-1][0] == 'li' and self.stack[-1][1]:
            self.output.append('</span>')
            self.stack[-1] = ('li', False)
        self._emit_tag(tag, attrs)
        if tag in WRAP_TAGS:
            self.output.append('<span>')
            self.stack.append((tag, True))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            wrap_tag, span_open = self.stack.pop()
            if span_open:
                self.output.append('</span>')
        self.output.append(f'</{tag}>')

    def handle_data(self, data):
        self.output.append(data)

    def handle_startendtag(self, tag, attrs):
        self._emit_tag(tag, attrs, self_close=True)

    def get_output(self):
        return ''.join(self.output)


def wrap_block_contents(html):
    wrapper = BlockContentWrapper()
    wrapper.feed(html)
    return wrapper.get_output()


def restructure_code_blocks(html):
    """把 <pre><code> 里的纯文本按行拆成 display:block 的 <span> 行。

    检测器对 pre-wrap 文本实测时，行尾换行符会被 Range.getClientRects
    算成额外矩形，行数虚增约一倍，平均行高被误判为叠字。拆成独立行元素后
    行数与实际一致；空行用 &nbsp; 占位保持高度。
    """
    def repl(m):
        open_tag, content = m.group(1), m.group(2)
        lines = content.split('\n')
        while lines and not lines[-1].strip():
            lines.pop()

        def fix_line(line):
            # 空格全部转成 &nbsp; + 零宽空格（U+200B）：
            # - 普通空格在 pre-wrap 折行处会产生独立碎片矩形，且行首缩进的
            #   纯空白也是一个碎片，都会让检测器行框计数虚增误报叠字
            # - &nbsp; 保持视觉空格且不可作为断行点，零宽空格提供断行点，
            #   保证每个视觉行恰好一个矩形（已在 320/375/414px 实测验证）
            # 代价：从文章里复制代码会带上 nbsp/零宽空格，公众号代码以阅读为主可接受
            i = 0
            while i < len(line) and line[i] in ' \t':
                i += 1
            indent = '&nbsp;' * (4 * line[:i].count('\t') + line[:i].count(' '))
            body = line[i:].replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;').replace(' ', '&nbsp;​')
            return indent + body

        out = ''.join(
            f'<span style="display: block;">{fix_line(line) if line.strip() else "&nbsp;"}</span>'
            for line in lines
        )
        return open_tag + out + m.group(3)

    return re.sub(
        r'(<pre[^>]*>\s*<code[^>]*>)(.*?)(</code>\s*</pre>)',
        repl, html, flags=re.S,
    )


def apply_inline_styles(html, style_map):
    """Parse HTML and inject inline styles"""
    injector = StyleInjector(style_map)
    injector.feed(html)
    return injector.get_output()


def preprocess_strikethrough(md_text):
    """把 ~~删除线~~ 转成 <del>（Python-Markdown 原生不支持该语法）。

    逐行处理并跳过 ``` 围栏代码块，避免误伤代码内容。
    """
    out = []
    in_fence = False
    for line in md_text.split('\n'):
        if line.strip().startswith('```'):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence:
            line = re.sub(r'~~(.+?)~~', r'<del>\1</del>', line)
        out.append(line)
    return '\n'.join(out)


def adjust_image_paragraphs(html):
    """只含一张图片的段落去掉左右边距，让图片通栏（等效微信"自适应"）。

    正文段落左右各有 8px 边距，img 的 width:100% 只是段内宽度的 100%，
    会比正文区窄 16px；图片段落边距归零后图片与正文区同宽。
    不用 calc(100%+16px)/负边距方案——会产生水平偏移，触发检测器
    1.4.2 溢出规则。
    """
    def repl(m):
        # margin: 0px 8px <段距> → margin: 0px 0px <段距>（段距值随样式主题变化，用正则通配）
        style = re.sub(r'margin: 0px 8px ([^;]+);', r'margin: 0px 0px \1;', m.group(1))
        return f'<p style="{style}"><span>{m.group(2)}</span></p>'

    return re.sub(
        r'<p style="([^"]*)">\s*(?:<span>)?\s*((?:<img[^>]*/>))\s*(?:</span>)?\s*</p>',
        repl, html, flags=re.S,
    )


def convert_markdown_to_wechat(md_text, style_file='styles/default.json'):
    """Convert Markdown to WeChat-styled HTML"""
    md_text = preprocess_strikethrough(md_text)
    # Convert markdown to HTML with extensions
    html = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'nl2br'])

    # Load and apply inline styles
    style_map = load_style_from_file(style_file)
    styled_html = apply_inline_styles(html, style_map)
    styled_html = restructure_code_blocks(styled_html)
    styled_html = wrap_block_contents(styled_html)
    styled_html = adjust_image_paragraphs(styled_html)

    # Wrap in container with base styles
    # 注意：官方规范第 3 章明确"不建议设置任何 font-family"（公众号有默认字体栈，
    # 自定义字体族会导致 iOS 上字号/字间距渲染不一致），故容器不设 font-family。
    container_style = f'font-size: 15px; color: rgb(63, 63, 63); line-height: 30px; letter-spacing: 2px; text-align: left;'

    return f'<div style="{container_style}">\n{styled_html}\n</div>'


def create_preview_html(styled_content):
    """Wrap styled content in complete HTML document

    预览样式（灰底 + 手机宽度白卡片）只写在 <style> 里、通过 body > div
    标签选择器生效，不给文章元素加任何 class/内联样式：浏览器复制时
    <style> 不进入剪贴板，微信粘贴只拿到文章本身的内联样式——同一个
    文件既能预览手机端效果又能干净粘贴。

    验证注意：微信官方检测器（verify-article-structure-spec）会把 <style>
    的计算样式内联后实测，预览卡片会引入误报。对该检测器应先用
    strip_preview_chrome() 生成去预览样式的副本再跑，其结果才等于
    微信粘贴后实际检测的内容。
    """
    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WeChat Preview</title>
<style>
  /* 以下仅用于浏览器预览，粘贴到微信时不生效 */
  body {{ margin: 0; background: #e9e9e9; }}
  body > div {{
    background: #ffffff;
    max-width: 420px;
    margin: 24px auto;
    padding: 28px 14px;
    box-sizing: border-box;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08);
  }}
  @media (max-width: 480px) {{
    body > div {{ margin: 0 auto; border-radius: 0; box-shadow: none; }}
  }}
</style>
</head>
<body>
{styled_content}
</body>
</html>'''


def strip_preview_chrome(html_text):
    """去掉 create_preview_html 注入的 <style> 预览样式块。

    用于送官方检测器验证：去掉预览样式后的 DOM 才等于用户复制/微信
    粘贴实际得到的内容。
    """
    return re.sub(r'<style>.*?</style>', '', html_text, flags=re.S)


def main():
    parser = argparse.ArgumentParser(description='Convert Markdown to WeChat-styled HTML')
    parser.add_argument('input', help='Input Markdown file path')
    parser.add_argument('--style', default='styles/default.json', help='Style file (default: styles/default.json)')
    parser.add_argument('--output', help='Output HTML file path (default: current directory)')
    parser.add_argument('--no-verify', action='store_true',
                        help='跳过官方检测器合规校验（默认转换后自动校验）')
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return

    # Read markdown
    md_text = input_path.read_text(encoding='utf-8')

    # Convert with selected style
    styled_content = convert_markdown_to_wechat(md_text, args.style)

    # Output file
    base_name = input_path.stem
    if args.output:
        output_file = Path(args.output)
    else:
        output_file = Path.cwd() / f"{base_name}_wechat.html"

    # Create output directory if needed
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write complete HTML document
    preview_html = create_preview_html(styled_content)
    output_file.write_text(preview_html, encoding='utf-8')
    print(f"[OK] Generated: {output_file}")
    print(f"[提示] 用浏览器打开该文件可预览手机端效果；全选复制(Ctrl+A, Ctrl+C)粘贴到微信公众号编辑器")

    # 默认自动跑微信官方检测器校验（可用 --no-verify 跳过）
    if not args.no_verify:
        try:
            from verify_wechat import verify
            print(f"[检测] 正在调用微信官方检测器校验……")
            ok, output = verify(output_file)
            if ok is None:
                print(f"[检测跳过] {output}")
            elif ok:
                print(f"[检测通过] 官方检测器全规则 0 违规")
            else:
                lines = [l for l in output.splitlines()
                         if l.strip() and 'uppeteer' not in l and 'headless' not in l]
                # GBK 控制台无法显示 ✗ 等符号，替换后打印
                detail = '\n'.join(lines[-30:])
                print(detail.encode('gbk', errors='replace').decode('gbk', errors='replace'))
                print(f"[检测未通过] 存在违规项，请修复后重新转换")
                sys.exit(1)
        except Exception as e:
            print(f"[检测异常] {e}（不影响已生成的 HTML，可用 verify_wechat.py 单独排查）")


if __name__ == '__main__':
    main()
