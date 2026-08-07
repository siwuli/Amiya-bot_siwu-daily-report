# -*- coding: UTF-8 -*-
"""
打包脚本：把 siwu-daily-report 插件打包为 zip。

版本号自动读取自 main.py 中的 version=，输出 plugins/siwu-daily-report-<version>.zip。
用法（在项目根目录下执行）：
    python pluginsServer/siwu-daily-report-1_0/build.py
"""

import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def plugin_version() -> str:
    """从 main.py 中读取插件版本号（version='x.y.z'）"""
    with open(os.path.join(PLUGIN_DIR, 'main.py'), encoding='utf-8') as f:
        src = f.read()
    m = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", src)
    return m.group(1) if m else '1.0.0'


def output_zip() -> str:
    return os.path.join(ROOT, 'plugins', f'siwu-daily-report-{plugin_version()}.zip')


def _add_dir(zf: zipfile.ZipFile, src_dir: str):
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith(('.pyc', '.pyo')):
                continue
            full = os.path.join(root, f)
            arcname = os.path.relpath(full, PLUGIN_DIR).replace('\\', '/')
            print(f'  + {arcname}')
            zf.write(full, arcname=arcname)


def build():
    output = output_zip()
    os.makedirs(os.path.dirname(output), exist_ok=True)

    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in os.listdir(PLUGIN_DIR):
            if f == os.path.basename(__file__) or f.startswith('__pycache__'):
                continue
            full = os.path.join(PLUGIN_DIR, f)
            if os.path.isfile(full):
                print(f'  + {f}')
                zf.write(full, arcname=f)
            elif os.path.isdir(full) and f == 'report':
                _add_dir(zf, full)

    print(f'\ncreated: {output} ({os.path.getsize(output)} bytes)')
    return output


if __name__ == '__main__':
    build()
