#!/usr/bin/env python3
"""Migrate images in a Markdown file to the configured image bed.

Scans a Markdown file for images (both ![](url) syntax and <img src> tags),
checks whether each image is already hosted on the configured image bed domain,
and re-uploads any that are not (remote URLs are downloaded first, local files
are uploaded directly). Writes a new Markdown file with replaced URLs.

Usage:
    python migrate_images.py <input.md> [--config image_bed_config.json] [--output out.md]
"""

import argparse
import json
import re
import sys
import tempfile
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import urlopen, Request


# ---------------------------------------------------------------------------
# Image bed uploaders
# ---------------------------------------------------------------------------

class ImageBedUploader(ABC):
    """Abstract base class for image bed uploaders"""

    @abstractmethod
    def upload(self, file_path):
        """Upload file and return URL"""
        pass

    @abstractmethod
    def matches(self, url):
        """Return True if the URL is already hosted on this image bed"""
        pass


class QiniuUploader(ImageBedUploader):
    """Qiniu cloud uploader"""

    def __init__(self, config):
        from qiniu import Auth
        self.access_key = config['access_key']
        self.secret_key = config['secret_key']
        self.bucket = config['bucket']
        self.domain = config['domain'].rstrip('/').replace('http://', '').replace('https://', '')
        self.auth = Auth(self.access_key, self.secret_key)

    def upload(self, file_path):
        from qiniu import put_file
        ext = Path(urlparse(str(file_path)).path).suffix or '.jpg'
        key = f"{uuid.uuid4().hex}{ext}"
        token = self.auth.upload_token(self.bucket, key)
        ret, info = put_file(token, key, str(file_path))
        if info.status_code != 200:
            raise Exception(f"Upload failed: {info}")
        # 注意：七牛 clouddn.com 测试域名的 https 证书错配（浏览器会拦截），只能用 http
        return f"http://{self.domain}/{key}"

    def matches(self, url):
        host = urlparse(url).netloc
        return host == self.domain


def load_config(config_path=None):
    """Load image bed configuration"""
    script_dir = Path(__file__).parent
    if config_path is None:
        config_file = script_dir / 'image_bed_config.json'
    else:
        config_file = Path(config_path)
        if not config_file.is_absolute():
            config_file = script_dir / config_file
    if not config_file.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_file}")
    with open(config_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def config_is_empty(config):
    """Check whether the active provider's credentials are filled in"""
    provider = config.get('provider', '')
    section = config.get(provider, {})
    return not all(str(v).strip() for v in section.values())


def get_uploader(config):
    """Get uploader instance based on provider"""
    provider = config.get('provider', '')
    if provider == 'qiniu':
        return QiniuUploader(config['qiniu'])
    raise ValueError(
        f"暂不支持的图床: {provider or '(未设置)'}。"
        f"目前仅实现了七牛云(qiniu)，请在 image_bed_config.json 中配置 provider=qiniu"
    )


# ---------------------------------------------------------------------------
# Image scanning and migration
# ---------------------------------------------------------------------------

# Markdown image syntax: ![alt](url) or ![alt](url "title")
MD_IMG_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
# HTML img tag: <img src="url" ...>
HTML_IMG_RE = re.compile(r'<img\s[^>]*?src=["\']([^"\']+)["\']', re.IGNORECASE)

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}


def is_remote(url):
    return url.startswith('http://') or url.startswith('https://')


def download_image(url, dest_dir):
    """Download a remote image to dest_dir, return local path"""
    ext = Path(urlparse(url).path).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        ext = '.jpg'
    dest = Path(dest_dir) / f"{uuid.uuid4().hex}{ext}"
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=30) as resp, open(dest, 'wb') as f:
        f.write(resp.read())
    return dest


def migrate_images(md_file, config_path=None, output_file=None):
    """Migrate all non-image-bed images in md_file to the configured image bed.

    Returns (output_path, stats_dict).
    """
    md_path = Path(md_file)
    content = md_path.read_text(encoding='utf-8')

    config = load_config(config_path)
    if config_is_empty(config):
        raise ValueError(
            f"图床配置不完整: provider={config.get('provider')!r} 的字段存在空值，"
            f"请先在 image_bed_config.json 中补全配置"
        )
    uploader = get_uploader(config)

    # Collect unique image references: markdown syntax + html img tags
    md_imgs = [(m.group(0), m.group(2)) for m in MD_IMG_RE.finditer(content)]
    html_imgs = [(m.group(1), m.group(1)) for m in HTML_IMG_RE.finditer(content)]
    all_refs = md_imgs + [(full, url) for full, url in html_imgs
                          if url not in {u for _, u in md_imgs}]

    stats = {'total': len(all_refs), 'kept': 0, 'migrated': 0, 'failed': 0}

    if not all_refs:
        print("[信息] 文章中没有图片，无需迁移")
    else:
        print(f"[信息] 检测到 {len(all_refs)} 张图片，图床域名: {uploader.domain}")

    tmp_dir = tempfile.mkdtemp(prefix='md2wechat_imgs_')

    for full_match, url in all_refs:
        if is_remote(url) and uploader.matches(url):
            print(f"[跳过] 已在图床上: {url}")
            stats['kept'] += 1
            continue
        try:
            if is_remote(url):
                print(f"[下载] {url}")
                local_path = download_image(url, tmp_dir)
            else:
                # Local path: resolve relative to the markdown file
                # (URL-decode first: editors often encode spaces as %20)
                local_path = Path(unquote(url))
                if not local_path.is_absolute():
                    local_path = md_path.parent / unquote(url)
                if not local_path.exists():
                    raise FileNotFoundError(f"本地图片不存在: {local_path}")
            print(f"[上传] {local_path.name} -> 图床")
            new_url = uploader.upload(local_path)
            print(f"[成功] {new_url}")
            # Replace URL inside the original markdown match to keep alt/title intact
            new_match = full_match.replace(url, new_url)
            content = content.replace(full_match, new_match)
            stats['migrated'] += 1
        except Exception as e:
            print(f"[失败] {url}: {e}", file=sys.stderr)
            stats['failed'] += 1

    if output_file is None:
        output_file = md_path.parent / f"{md_path.stem}_hosted{md_path.suffix}"
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')

    print(f"[完成] 共 {stats['total']} 张图片: "
          f"已在图床 {stats['kept']}，新迁移 {stats['migrated']}，失败 {stats['failed']}")
    print(f"[完成] 新文件: {output_path}")
    return output_path, stats


def main():
    parser = argparse.ArgumentParser(
        description='Migrate Markdown images to the configured image bed')
    parser.add_argument('markdown', help='Input Markdown file path')
    parser.add_argument('--config', default=None,
                        help='Image bed config file (default: image_bed_config.json next to script)')
    parser.add_argument('--output', help='Output Markdown file path '
                                         '(default: <name>_hosted.md next to input)')
    args = parser.parse_args()

    md_path = Path(args.markdown)
    if not md_path.exists():
        print(f"[错误] 文件不存在: {md_path}", file=sys.stderr)
        sys.exit(1)

    try:
        _, stats = migrate_images(args.markdown, args.config, args.output)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(2)

    if stats['failed']:
        sys.exit(3)


if __name__ == '__main__':
    main()
