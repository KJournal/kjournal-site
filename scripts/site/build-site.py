#!/usr/bin/env python3
"""site/ 템플릿 + dist/ APK 로 GitHub Pages 배포용 public/ 을 조립한다.

    public/index.html                 다운로드 페이지
    public/<apk 파일명>                APK
    public/apk/<apk 파일명>            APK (OTA 다운로드 경로)
    public/ota/version.json           OTA 업데이트 정보
    public/icon.png                   앱 아이콘
    public/robots.txt
    public/fdroid/repo/...            F-Droid 커스텀 저장소 (index-v1.jar + APK + 아이콘)

사용:
    python3 scripts/site/build-site.py [--apk dist/KJournal-5-PB6.apk] [--version "5 PB6"]
                                       [--repo-url https://kjournal.github.io/kjournal-site/fdroid/repo]
                                       [--site-url https://kjournal.github.io/kjournal-site]
"""
import argparse
import hashlib
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
PUBLIC = ROOT / 'public'
SITE = ROOT / 'site'
DIST = ROOT / 'dist'
FDROID_DIR = ROOT / 'fdroid'
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))
sys.path.insert(0, str(ROOT / 'scripts' / 'fdroid'))

try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

from apk_info import parse_apk  # noqa: E402

DEFAULT_SITE = 'https://kjournal.github.io/kjournal-site'
DEFAULT_REPO = DEFAULT_SITE + '/fdroid/repo'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def keystore_pass():
    props = FDROID_DIR / 'keystore.properties'
    if not props.is_file():
        return None
    for line in props.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('FDROID_KEYSTORE_PASS='):
            return line.split('=', 1)[1].strip()
    return None


def repo_fingerprint():
    """F-Droid 저장소 서명 키의 SHA-256 지문을 콜론 형식으로 반환."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(
            'kj_build_index', ROOT / 'scripts' / 'fdroid' / 'build-index.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        find_tool = mod.find_tool
    except Exception:
        return ''
    pw = keystore_pass()
    ks = FDROID_DIR / 'keystore.jks'
    if not pw or not ks.is_file():
        return ''
    out = subprocess.run([find_tool('keytool'), '-list', '-v', '-keystore', str(ks),
                          '-alias', 'kjournal', '-storepass', pw],
                         capture_output=True, text=True)
    m = re.search(r'SHA256:\s*([0-9A-Fa-f:]+)', out.stdout)
    return m.group(1).strip().upper() if m else ''


def changelog_for(apk, version_code):
    for loc in ('ko', 'en-US'):
        f = FDROID_DIR / 'metadata' / 'com.isaakhanimann.journal.kr4812.premiumtest' / loc / 'changelogs' / f'{version_code}.txt'
        if f.is_file():
            return f.read_text(encoding='utf-8').strip()
    return '버그 수정 및 안정성 개선'


def render_changelog(text):
    """체인지로그 텍스트를 사이트용 HTML 로 변환한다 (첫 'KJournal ...' 제목 줄은 생략)."""
    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith('kjournal'):
        lines = lines[1:]
    items, paras = [], []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s.startswith(('- ', '* ', '• ')):
            items.append(html.escape(s[2:].strip()))
        elif re.match(r'^\d+[.)]\s*', s):
            items.append(html.escape(re.sub(r'^\d+[.)]\s*', '', s)))
        else:
            paras.append(html.escape(s))
    out = []
    if paras:
        out.append('<p>' + '<br>'.join(paras) + '</p>')
    if items:
        out.append('<ul>' + ''.join('<li>%s</li>' % i for i in items) + '</ul>')
    return '\n    '.join(out) if out else '<p>버그 수정 및 안정성 개선</p>'


def write_ota_json(apk, info, site_url):
    """앱 OTA(check) 가 읽는 version.json 을 만든다."""
    vcode = int(info.get('versionCode') or 0)
    doc = {
        'versionCode': vcode,
        'versionName': info.get('versionName') or '',
        'downloadUrl': f"{site_url.rstrip('/')}/apk/{apk.name}",
        'changelog': changelog_for(apk, vcode),
        'sha256': sha256(apk).lower(),
    }
    outdir = PUBLIC / 'ota'
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'version.json').write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', default=None, help='배포할 APK (기본: dist/ 에서 versionCode 최고)')
    ap.add_argument('--version', default=None, help='표시 버전 라벨 (기본: APK 파일명 기반)')
    ap.add_argument('--repo-url', default=DEFAULT_REPO)
    ap.add_argument('--site-url', default=DEFAULT_SITE)
    ap.add_argument('--skip-index', action='store_true', help='F-Droid 저장소 생성을 건너뛴다')
    args = ap.parse_args()

    if args.apk:
        apk = pathlib.Path(args.apk)
    else:
        apks = sorted(DIST.glob('*.apk'))
        if not apks:
            print('dist/ 에 APK 가 없습니다.', file=sys.stderr)
            return 1

        def _vcode(p):
            try:
                return int(parse_apk(p)['versionCode'] or 0)
            except Exception:  # noqa: BLE001
                return 0
        apk = max(apks, key=_vcode)

    if not apk.is_file():
        print(f'APK 를 찾을 수 없습니다: {apk}', file=sys.stderr)
        return 1

    info = parse_apk(apk)
    version = args.version or apk.stem.replace('KJournal-', '')
    digest = sha256(apk)
    size_mb = f'{apk.stat().st_size / (1024 * 1024):.1f}'

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    shutil.copy2(apk, PUBLIC / apk.name)
    # OTA 다운로드 경로 (앱의 허용 prefix 안에 있어야 함)
    (PUBLIC / 'apk').mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk, PUBLIC / 'apk' / apk.name)

    icon = FDROID_DIR / 'icon.png'
    if icon.is_file():
        shutil.copy2(icon, PUBLIC / 'icon.png')

    fingerprint = repo_fingerprint()

    template = (SITE / 'index.html').read_text(encoding='utf-8')
    changelog_html = render_changelog(changelog_for(apk, info.get('versionCode')))
    html_out = (template
            .replace('__VERSION__', version)
            .replace('__VERSION_NAME__', info.get('versionName') or '-')
            .replace('__VERSION_CODE__', info.get('versionCode') or '-')
            .replace('__APP_ID__', info.get('package') or '-')
            .replace('__APK__', apk.name)
            .replace('__SIZE__', size_mb)
            .replace('__SHA256__', digest)
            .replace('__CHANGELOG__', changelog_html)
            .replace('__FDROID_REPO_URL__', args.repo_url.rstrip('/'))
            .replace('__FDROID_REPO_HOST__', re.sub(r'^https?://', '', args.repo_url.rstrip('/')))
            .replace('__FDROID_FINGERPRINT_URI__', (fingerprint or '').replace(':', '').lower())
            .replace('__FDROID_FINGERPRINT__', fingerprint or '(미확인)'))
    (PUBLIC / 'index.html').write_text(html_out, encoding='utf-8')
    (PUBLIC / 'robots.txt').write_text('User-agent: *\nAllow: /\n', encoding='utf-8')

    # ── OTA version.json ───────────────────────────────────────
    ota = write_ota_json(apk, info, args.site_url)

    # ── F-Droid 커스텀 저장소 ───────────────────────────────────
    if not args.skip_index:
        cmd = [sys.executable, str(ROOT / 'scripts' / 'fdroid' / 'build-index.py'),
               '--out', str(PUBLIC / 'fdroid' / 'repo'),
               '--repo-url', args.repo_url.rstrip('/')]
        res = subprocess.run(cmd)
        if res.returncode != 0:
            print('F-Droid 저장소 생성 실패', file=sys.stderr)
            return res.returncode

    print('public/ 준비 완료')
    print(f'  APK        : {apk.name} ({size_mb} MB)')
    print(f'  버전       : {version} (versionCode {info.get("versionCode")})')
    print(f'  SHA256     : {digest}')
    print(f'  사이트     : {args.site_url.rstrip("/")}')
    print(f'  OTA JSON   : {args.site_url.rstrip("/")}/ota/version.json  (versionCode {ota["versionCode"]})')
    print(f'  F-Droid    : {args.repo_url.rstrip("/")}')
    print(f'  저장소 지문: {fingerprint or "-"}')
    for p in sorted(PUBLIC.rglob('*')):
        if p.is_file():
            print(f'  - {p.relative_to(PUBLIC)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
