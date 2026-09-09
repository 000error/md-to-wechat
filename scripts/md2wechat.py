#!/usr/bin/env python3
"""Markdown to WeChat HTML Converter - Converts Markdown to WeChat-styled HTML"""

import argparse
import markdown
import json
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

    def handle_starttag(self, tag, attrs):
        if tag == 'pre':
            self.in_pre = True

        attrs_dict = dict(attrs)

        # Special handling for code inside pre
        if tag == 'code' and self.in_pre:
            style = 'font-family: Menlo, Consolas, Monaco, monospace; font-size: 13px; padding: 0.5em 1em 1em; color: rgb(201, 209, 217); line-height: 1.75; white-space: pre-wrap; display: block;'
        else:
            style = self.style_map.get(tag, '')

        if style:
            attrs_dict['style'] = style

        attrs_str = ' '.join(f'{k}="{v}"' for k, v in attrs_dict.items())
        self.output.append(f'<{tag} {attrs_str}>' if attrs_str else f'<{tag}>')

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_pre = False
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


def apply_inline_styles(html, style_map):
    """Parse HTML and inject inline styles"""
    injector = StyleInjector(style_map)
    injector.feed(html)
    return injector.get_output()


def convert_markdown_to_wechat(md_text, style_file='styles/default.json'):
    """Convert Markdown to WeChat-styled HTML"""
    # Convert markdown to HTML with extensions
    html = markdown.markdown(md_text, extensions=['tables', 'fenced_code', 'nl2br'])

    # Load and apply inline styles
    style_map = load_style_from_file(style_file)
    styled_html = apply_inline_styles(html, style_map)

    # Wrap in container with base styles
    base_font = '-apple-system-font, BlinkMacSystemFont, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif'
    container_style = f'font-family: {base_font}; font-size: 16px; color: rgb(63, 63, 63); line-height: 1.75; letter-spacing: 2px;'

    return f'<div style="{container_style}">\n{styled_html}\n</div>'


def create_preview_html(styled_content):
    """Wrap styled content in complete HTML document"""
    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WeChat Preview</title>
</head>
<body>
{styled_content}
</body>
</html>'''


def main():
    parser = argparse.ArgumentParser(description='Convert Markdown to WeChat-styled HTML')
    parser.add_argument('input', help='Input Markdown file path')
    parser.add_argument('--style', default='styles/default.json', help='Style file (default: styles/default.json)')
    parser.add_argument('--output', help='Output HTML file path (default: current directory)')
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
    print(f"[提示] 用浏览器打开该文件，全选复制(Ctrl+A, Ctrl+C)，然后粘贴到微信公众号编辑器")


if __name__ == '__main__':
    main()
