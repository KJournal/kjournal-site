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
        f = FDROID_DIR / 'metadata' / 'com.jiwxn3.KJournal' / loc / 'changelogs' / f'{version_code}.txt'
        if f.is_file():
            text = f.read_text(encoding='utf-8').strip()
            # 날짜 줄과 '변경' 류 머리말은 본문에서 제외
            header = {'변경', '변경 사항', '변경사항', 'changes', 'change'}
            lines = [l for l in text.splitlines()
                     if l.strip() and not changelog_date(l) and l.strip().lower() not in header]
            return '\n'.join(lines).strip()
    return '버그 수정 및 안정성 개선'


def changelog_date_for(version_code):
    for loc in ('ko', 'en-US'):
        f = FDROID_DIR / 'metadata' / 'com.jiwxn3.KJournal' / loc / 'changelogs' / f'{version_code}.txt'
        if f.is_file():
            d = changelog_date(f.read_text(encoding='utf-8'))
            if d:
                return d
    return ''


DATE_RE = re.compile(r'^(?:날짜|date|released?)\s*[:：]\s*(\d{4}-\d{2}-\d{2})\s*$', re.I)
BARE_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def changelog_date(text):
    """changelog txt 에서 첫 날짜 줄을 찾는다 (`날짜: 2026-09-23` 또는 `2026-09-23`)."""
    for raw in text.splitlines():
        s = raw.strip()
        m = DATE_RE.match(s)
        if m:
            return m.group(1)
        if BARE_DATE_RE.match(s):
            return s
    return ''


def render_changelog(text):
    """체인지로그 텍스트를 사이트용 HTML 로 변환한다.

    맨 앞의 빈 줄/`변경` 류 머리말/날짜 줄과 첫 'KJournal ...' 제목 줄은 생략한다.
    """
    lines = text.splitlines()
    if lines and lines[0].strip().lower().startswith('kjournal'):
        lines = lines[1:]
    skip = {'변경', '변경 사항', '변경사항', 'changes', 'change'}
    while lines and (not lines[0].strip() or lines[0].strip().lower() in skip
                     or changelog_date(lines[0])):
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


def link_lines(site_url):
    """체인지로그/릴리즈노트 끝에 붙일 주소 줄 (사이트 + GitHub)."""
    return ['사이트: %s/' % site_url.rstrip('/'),
            'GitHub: https://github.com/KJournal']


def with_site_link(text, site_url):
    """체인지로그 끝에 사이트·GitHub 주소 줄을 붙인다 (이미 있으면 중복 추가 안 함)."""
    lines = (text or '').strip().splitlines()
    for line in link_lines(site_url):
        if not any(l.strip() == line for l in lines):
            lines.append(line)
    return '\n'.join(lines)


def ota_hold_version_code():
    """릴리즈 보류 중 OTA 팝업을 막기 위한 홀드 버전코드.

    저장소 루트의 `.ota_hold` 파일에 숫자가 있으면 version.json 의 versionCode 를
    그 값으로 고정한다(설치본보다 크지 않게 두어 업데이트 팝업이 뜨지 않게 함).
    홀드를 해제하려면 파일을 지우면 된다.
    """
    f = ROOT / '.ota_hold'
    if f.is_file():
        try:
            return int(f.read_text(encoding='utf-8').strip())
        except Exception:  # noqa: BLE001
            return None
    return None


def write_ota_json(apk, info, site_url, filename='version.json'):
    """앱 OTA(check) 가 읽는 version.json(또는 beta-version.json) 을 만든다."""
    vcode = int(info.get('versionCode') or 0)
    doc = {
        'versionCode': ota_hold_version_code() or vcode,
        'versionName': info.get('versionName') or '',
        'date': changelog_date_for(vcode),
        'downloadUrl': f"{site_url.rstrip('/')}/apk/{apk.name}",
        'changelog': with_site_link(changelog_for(apk, vcode), site_url),
        'sha256': sha256(apk).lower(),
    }
    outdir = PUBLIC / 'ota'
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / filename).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return doc


def write_release_notes_json(site_url):
    """앱 릴리즈노트 화면이 읽는 전체 버전 노트 목록(ota/release-notes.json)."""
    pkg = 'com.jiwxn3.KJournal'
    entries, seen = [], set()
    for loc in ('ko', 'en-US'):
        cdir = FDROID_DIR / 'metadata' / pkg / loc / 'changelogs'
        if not cdir.is_dir():
            continue
        for f in sorted(cdir.glob('*.txt')):
            if not f.stem.isdigit() or int(f.stem) in seen:
                continue
            seen.add(int(f.stem))
            text = f.read_text(encoding='utf-8')
            lines = [l.strip() for l in text.splitlines()]
            lines = [l for l in lines
                     if l and l not in ('변경', '변경 사항', 'Changes', 'Change')
                     and not changelog_date(l)]
            name = ''
            if lines and lines[0].lower().startswith('kjournal'):
                name = lines[0][len('KJournal'):].strip()
                lines = lines[1:]
            lines = [(l[2:].strip() if l.startswith('- ') else l) for l in lines]
            for line in link_lines(site_url):
                if not any(l.strip() == line for l in lines):
                    lines.append(line)
            entries.append({'versionCode': int(f.stem), 'versionName': name,
                            'date': changelog_date(text), 'notes': lines})
    entries.sort(key=lambda x: x['versionCode'], reverse=True)
    outdir = PUBLIC / 'ota'
    outdir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, ensure_ascii=False, indent=2) + '\n'
    # 정식/배타 채널이 서로 다른 릴리즈노트 엔드포인트를 본다.
    (outdir / 'release-notes.json').write_text(payload, encoding='utf-8')
    (outdir / 'beta-release-notes.json').write_text(payload, encoding='utf-8')
    return entries


def _newest_apk(folder):
    """폴더에서 versionCode 가 가장 큰 APK 를 고른다(없으면 None)."""
    if not folder.is_dir():
        return None
    apks = sorted(folder.glob('*.apk'))
    if not apks:
        return None

    def _vcode(p):
        try:
            return int(parse_apk(p)['versionCode'] or 0)
        except Exception:  # noqa: BLE001
            return 0
    apks.sort(key=_vcode, reverse=True)
    return apks[0]


def _default_channels():
    """채널별 APK 를 고른다.

    - 정식(메인): `dist/*.apk` 중 versionCode 최고
    - 배타: `dist/beta/*.apk` 중 versionCode 최고 (없으면 배타 버튼 숨김)
    """
    return _newest_apk(DIST), _newest_apk(DIST / 'beta')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', default=None, help='(레거시) 단일 APK — 지정 시 메인으로 사용')
    ap.add_argument('--main-apk', default=None, help='메인(안정) 다운로드 APK')
    ap.add_argument('--beta-apk', default=None, help='배타(테스트) 다운로드 APK')
    ap.add_argument('--version', default=None, help='메인 표시 버전 라벨 (기본: APK 파일명 기반)')
    ap.add_argument('--beta-version', default=None, help='배타 표시 버전 라벨 (기본: APK 파일명 기반)')
    ap.add_argument('--repo-url', default=DEFAULT_REPO)
    ap.add_argument('--site-url', default=DEFAULT_SITE)
    ap.add_argument('--skip-index', action='store_true', help='F-Droid 저장소 생성을 건너뛴다')
    args = ap.parse_args()

    explicit_main = args.main_apk or args.apk
    if explicit_main:
        apk = pathlib.Path(explicit_main)
        beta = pathlib.Path(args.beta_apk) if args.beta_apk else None
    else:
        apk, default_beta = _default_channels()
        beta = pathlib.Path(args.beta_apk) if args.beta_apk else default_beta

    if apk is None:
        print('dist/ 에 APK 가 없습니다.', file=sys.stderr)
        return 1
    if not apk.is_file():
        print(f'APK 를 찾을 수 없습니다: {apk}', file=sys.stderr)
        return 1

    if beta is not None and not beta.is_file():
        print(f'배타 APK 를 찾을 수 없습니다: {beta}', file=sys.stderr)
        return 1
    if beta is not None and beta.resolve() == apk.resolve():
        beta = None

    info = parse_apk(apk)
    version = args.version or apk.stem.replace('KJournal-', '')
    digest = sha256(apk)
    size_mb = f'{apk.stat().st_size / (1024 * 1024):.1f}'

    if beta is not None:
        binfo = parse_apk(beta)
        bversion = args.beta_version or beta.stem.replace('KJournal-', '')
        bdigest = sha256(beta)
        bsize_mb = f'{beta.stat().st_size / (1024 * 1024):.1f}'
    else:
        binfo, bversion, bdigest, bsize_mb = {}, '', '', ''

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    shutil.copy2(apk, PUBLIC / apk.name)
    # OTA 다운로드 경로 (앱의 허용 prefix 안에 있어야 함)
    (PUBLIC / 'apk').mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk, PUBLIC / 'apk' / apk.name)

    if beta is not None:
        if not (PUBLIC / beta.name).exists():
            shutil.copy2(beta, PUBLIC / beta.name)
        bdst = PUBLIC / 'apk' / beta.name
        if not bdst.exists():
            shutil.copy2(beta, bdst)

    icon = FDROID_DIR / 'icon.png'
    if icon.is_file():
        shutil.copy2(icon, PUBLIC / 'icon.png')

    fingerprint = repo_fingerprint()

    template = (SITE / 'index.html').read_text(encoding='utf-8')
    changelog_html = render_changelog(changelog_for(apk, info.get('versionCode')))
    main_date = changelog_date_for(info.get('versionCode'))
    if beta is not None:
        beta_changelog_html = render_changelog(changelog_for(beta, binfo.get('versionCode')))
        beta_date = changelog_date_for(binfo.get('versionCode'))
    else:
        beta_changelog_html = ''
        beta_date = ''
    html_out = (template
            .replace('__CHANNEL__', '정식')
            .replace('__MAIN_DATE__', main_date or '-')
            .replace('__MAIN_VERSION__', version)
            .replace('__MAIN_VERSION_NAME__', info.get('versionName') or '-')
            .replace('__MAIN_VERSION_CODE__', info.get('versionCode') or '-')
            .replace('__MAIN_APK__', apk.name)
            .replace('__MAIN_SIZE__', size_mb)
            .replace('__MAIN_SHA256__', digest)
            .replace('__BETA_DATE__', beta_date or '-')
            .replace('__BETA_VERSION__', bversion)
            .replace('__BETA_VERSION_NAME__', binfo.get('versionName') or '-')
            .replace('__BETA_VERSION_CODE__', binfo.get('versionCode') or '-')
            .replace('__BETA_APK__', beta.name if beta is not None else '')
            .replace('__BETA_SIZE__', bsize_mb)
            .replace('__BETA_SHA256__', bdigest)
            .replace('__BETA_CHANGELOG__', beta_changelog_html)
            .replace('__BETA_HIDDEN__', '' if beta is not None else 'hidden')
            # 레거시 토큰(단일 APK 템플릿 호환) — 메인 기준
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

    # ── OTA version.json (정식) ─────────────────────────────────
    ota = write_ota_json(apk, info, args.site_url)

    # ── OTA beta-version.json (배타) ────────────────────────────
    if beta is not None:
        bota = write_ota_json(beta, binfo, args.site_url, 'beta-version.json')
        print(f'  OTA(beta)  : {args.site_url.rstrip("/")}/ota/beta-version.json  (versionCode {bota["versionCode"]})')

    # ── 릴리즈노트 전체 목록(앱 릴리즈노트 화면용) ──────────────
    notes = write_release_notes_json(args.site_url)
    print(f'릴리즈노트 {len(notes)}개 버전: ' + ', '.join(str(n["versionCode"]) for n in notes[:6]))

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
