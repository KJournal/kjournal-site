#!/usr/bin/env python3
"""fdroidserver 없이 F-Droid 커스텀 저장소(index-v1)를 만든다.

생성물:
    <out>/index-v1.json          인덱스 본문
    <out>/index-v1.jar           위 파일을 담고 저장소 키로 서명한 JAR (클라이언트가 검증)
    <out>/<pkg>_<vc>.apk         APK
    <out>/icons/<pkg>.<vc>.png   앱 아이콘
    <out>/icon.png               저장소 아이콘
    <out>/<pkg>/<locale>/changelogs/<vc>.txt  체인지로그

사용:
    python3 scripts/fdroid/build-index.py --out public/fdroid/repo

참고: index-v1 은 모든 F-Droid 버전이 지원한다(최신 버전은 v2 가 있으면 우선 사용하고,
없으면 v1 로 폴백). 여기서는 v1 만 생성한다.
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DIST = ROOT / 'dist'
FDROID_DIR = ROOT / 'fdroid'
sys.path.insert(0, str(ROOT / 'scripts' / 'ci'))

# Windows 콘솔(cp949)에서도 한글/기호 출력이 깨지지 않도록
try:
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

from apk_info import parse_apk  # noqa: E402

INDEX_VERSION = 30000
LOCALES = ('en-US', 'ko')
REPO_NAME = 'Menhera Network (KJournal)'
REPO_DESCRIPTION = 'KJournal 한국어 배포판 저장소입니다. 섭취 기록과 효과 타임라인, 실시간 알림을 지원합니다.'


def log(msg):
    print(f'[fdroid] {msg}')


def find_tool(name):
    """PATH → JAVA_HOME → 흔한 JDK 설치 경로 순으로 실행 파일을 찾는다."""
    exe = shutil.which(name)
    if exe:
        return exe
    candidates = []
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        candidates.append(pathlib.Path(java_home) / 'bin' / name)
    for base in ('C:/Program Files/Java', 'C:/Program Files/Eclipse Adoptium',
                 'C:/Program Files/Microsoft', 'C:/Program Files/Amazon Corretto'):
        p = pathlib.Path(base)
        if p.is_dir():
            for d in sorted(p.iterdir(), reverse=True):
                candidates.append(d / 'bin' / name)
    for c in candidates:
        for suffix in ('', '.exe'):
            cand = pathlib.Path(str(c) + suffix)
            if cand.is_file():
                return str(cand)
    raise FileNotFoundError(f'{name} 를 찾을 수 없습니다. JDK 를 설치하거나 PATH 에 추가하세요.')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def repo_fingerprint(keystore, alias, storepass):
    """저장소 서명 키 인증서의 SHA-256 지문을 콜론 형식으로 반환."""
    if not storepass or not pathlib.Path(keystore).is_file():
        return ''
    out = subprocess.run([find_tool('keytool'), '-list', '-v', '-keystore', str(keystore),
                          '-alias', alias, '-storepass', storepass],
                         capture_output=True, text=True)
    m = re.search(r'SHA256:\s*([0-9A-Fa-f:]+)', out.stdout)
    return m.group(1).strip().upper() if m else ''


def keytool_cert_digests(apk):
    """APK 서명 인증서의 MD5 / SHA-256 지문(콜론 없는 소문자 hex)을 반환.

    JDK 17+ 의 keytool 은 MD5 지문을 출력하지 않으므로 -rfc(PEM) 로 받아 직접 계산한다.
    """
    out = subprocess.run([find_tool('keytool'), '-printcert', '-jarfile', str(apk), '-rfc'],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f'keytool 실패: {out.stderr.strip()}')

    m = re.search(r'-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----',
                  out.stdout, re.S)
    if not m:
        raise RuntimeError('인증서 PEM 을 찾지 못했습니다')
    der = base64.b64decode(re.sub(r'\s+', '', m.group(1)))
    return hashlib.md5(der).hexdigest(), hashlib.sha256(der).hexdigest()


def read_text(path, default=''):
    p = pathlib.Path(path)
    if not p.is_file():
        return default
    return p.read_text(encoding='utf-8').strip()


def read_locale_metadata(pkg):
    """fdroid/metadata/<pkg>/<locale>/... 를 읽어 localized/아이콘 정보를 만든다."""
    localized = {}
    base = FDROID_DIR / 'metadata' / pkg
    for loc in LOCALES:
        d = base / loc
        if not d.is_dir():
            continue
        entry = {}
        name = read_text(d / 'title.txt')
        summary = read_text(d / 'short_description.txt')
        description = read_text(d / 'full_description.txt')
        if name:
            entry['name'] = name
        if summary:
            entry['summary'] = summary
        if description:
            entry['description'] = description
        if entry:
            localized[loc] = entry
    return localized


def build(args):
    apks = sorted(DIST.glob('*.apk'))
    if args.apk:
        apks = [pathlib.Path(args.apk)]
    if not apks:
        log('dist/ 에 APK 가 없습니다.')
        return 1

    if not args.keystore.exists():
        log(f'키스토어가 없습니다: {args.keystore}')
        return 1
    if not args.storepass or not args.keypass:
        log('키스토어/키 비밀번호가 필요합니다 (--storepass/--keypass 또는 fdroid/keystore.properties).')
        return 1

    out: pathlib.Path = args.out
    icons_dir = out / 'icons'
    # 기존에 배포된 파일을 지우지 않는다 (이전 버전 APK/아이콘 유지)
    out.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    icon_src = FDROID_DIR / 'icon.png'
    if not icon_src.is_file():
        log(f'아이콘 없음: {icon_src}')
        return 1
    shutil.copy2(icon_src, out / 'icon.png')

    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)

    # ── dist 의 모든 APK 를 버전으로 등록 (이전 버전 유지) ──────
    packages = {}
    for a in apks:
        try:
            info = parse_apk(a)
        except Exception as e:  # noqa: BLE001
            log(f'APK 파싱 실패: {a} ({e})')
            continue
        pkg = info['package']
        vcode = str(info['versionCode'])
        apk_name = f'{pkg}_{vcode}.apk'
        if a.resolve() != (out / apk_name).resolve():
            shutil.copy2(a, out / apk_name)
        icon_name = f'{pkg}.{vcode}.png'
        shutil.copy2(icon_src, icons_dir / icon_name)
        sig_md5, signer = keytool_cert_digests(a)
        packages.setdefault(pkg, []).append({
            'added': now,
            'antiFeatures': [],
            'apkName': apk_name,
            'hash': sha256_file(out / apk_name),
            'hashType': 'sha256',
            'minSdkVersion': int(info['minSdkVersion'] or 0),
            'packageName': pkg,
            'sig': sig_md5,
            'signer': signer,
            'size': (out / apk_name).stat().st_size,
            'targetSdkVersion': int(info['targetSdkVersion'] or 0),
            'uses-permission': [[p, None] for p in info['permissions']],
            'versionCode': int(info['versionCode']),
            'versionName': info['versionName'],
        })

    if not packages:
        log('등록할 APK 가 없습니다.')
        return 1

    # ── 체인지로그 복사 ────────────────────────────────────────
    for pkg in packages:
        base_meta = FDROID_DIR / 'metadata' / pkg
        for loc in LOCALES:
            cl_dir = base_meta / loc / 'changelogs'
            if cl_dir.is_dir():
                dst = out / pkg / loc / 'changelogs'
                dst.mkdir(parents=True, exist_ok=True)
                for f in cl_dir.glob('*.txt'):
                    shutil.copy2(f, dst / f.name)

    # ── 앱 항목 (패키지별, 최신 버전 기준) ─────────────────────
    apps = []
    for pkg, versions in sorted(packages.items()):
        versions.sort(key=lambda v: v['versionCode'])
        newest = versions[-1]
        localized = read_locale_metadata(pkg)
        apps.append({
            'categories': [],
            'suggestedVersionName': newest['versionName'],
            'suggestedVersionCode': str(newest['versionCode']),
            'description': localized.get('ko', localized.get('en-US', {})).get('description', ''),
            'donate': '',
            'issueTracker': '',
            'license': 'GPL-3.0-or-later',
            'sourceCode': 'https://github.com/isaakhanimann/psychonautwiki-journal-android',
            'summary': localized.get('ko', localized.get('en-US', {})).get('summary', ''),
            'webSite': '',
            'added': now,
            'icon': f"{pkg}.{newest['versionCode']}.png",
            'packageName': pkg,
            'lastUpdated': now,
            'localized': localized,
        })

    index = {
        'repo': {
            'timestamp': now,
            'version': INDEX_VERSION,
            'name': REPO_NAME,
            'icon': 'icon.png',
            'address': args.repo_url.rstrip('/'),
            'description': REPO_DESCRIPTION,
            'mirrors': [],
        },
        'requests': {'install': [], 'uninstall': []},
        'apps': apps,
        'packages': packages,
    }

    (out / 'index-v1.json').write_text(
        json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    # ── 저장소 디렉터리를 브라우저로 열었을 때 보여줄 안내 페이지 ──
    # (F-Droid 클라이언트는 index-v1.jar 등 개별 파일만 요청하므로 영향 없음)
    fpr = repo_fingerprint(args.keystore, args.alias, args.storepass)
    landing_tpl = FDROID_DIR / 'repo-landing.html'
    if landing_tpl.is_file():
        newest_pkg = apps[0]['packageName']
        newest_ver = apps[0]['suggestedVersionCode']
        html = (landing_tpl.read_text(encoding='utf-8')
                .replace('__REPO_URL__', index['repo']['address'])
                .replace('__REPO_HOST__', re.sub(r'^https?://', '', index['repo']['address']))
                .replace('__FINGERPRINT_NOHYPHEN__', fpr.replace(':', '').lower())
                .replace('__FINGERPRINT__', fpr or '(미확인)')
                .replace('__APK_NAME__', f'{newest_pkg}_{newest_ver}.apk')
                .replace('__APP_ID__', newest_pkg)
                .replace('__VERSION__', f"{apps[0]['suggestedVersionName']} (versionCode {newest_ver})"))
        (out / 'index.html').write_text(html, encoding='utf-8')

    # ── index-v1.jar 생성 + 서명 ───────────────────────────────
    jar_path = out / 'index-v1.jar'
    with zipfile.ZipFile(jar_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(out / 'index-v1.json', 'index-v1.json')

    jarsigner = find_tool('jarsigner')
    # F-Droid 클라이언트는 index-v1.jar 의 매니페스트 다이제스트로 SHA1-Digest 만 지원한다.
    # (공식 f-droid.org 저장소의 index-v1.jar 도 SHA1-Digest + SHA1withRSA 로 서명되어 있다)
    # JDK 17+ 는 SHA1 서명을 기본 차단하므로 해당 제한을 해제하고 서명한다.
    res = subprocess.run([
        jarsigner,
        '-J-Djdk.jar.disabledAlgorithms=MD2, MD5',
        '-keystore', str(args.keystore),
        '-storepass', args.storepass,
        '-keypass', args.keypass,
        '-sigalg', 'SHA1withRSA',
        '-digestalg', 'SHA1',
        str(jar_path), args.alias,
    ], capture_output=True, text=True)
    if res.returncode != 0:
        log('jarsigner 실패:')
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        return 1

    # ── 결과 요약 ──────────────────────────────────────────────
    log(f'저장소 생성: {out}')
    for p in sorted(out.rglob('*')):
        if p.is_file():
            print(f'    {p.relative_to(out)}  ({p.stat().st_size} B)')
    print()
    log(f'저장소 주소 : {index["repo"]["address"]}')
    for a in apps:
        pkg = a['packageName']
        vs = packages[pkg]
        log(f'앱          : {pkg}  버전 {len(vs)}개 (최신 {a["suggestedVersionName"]} / {a["suggestedVersionCode"]})')
        for v in vs:
            log(f'   - {v["versionName"]} ({v["versionCode"]})  {v["apkName"]}  {v["hash"][:16]}...')
    print()
    log('F-Droid 앱에서 아래 주소를 저장소로 추가하세요:')
    print(f'    {index["repo"]["address"]}')

    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'public' / 'fdroid' / 'repo'))
    ap.add_argument('--apk', default=None, help='기본: dist/ 의 마지막 APK')
    ap.add_argument('--repo-url', default='https://kjournal.github.io/kjournal-site/fdroid/repo')
    ap.add_argument('--keystore', default=str(FDROID_DIR / 'keystore.jks'))
    ap.add_argument('--alias', default='kjournal')
    ap.add_argument('--storepass', default=None)
    ap.add_argument('--keypass', default=None)
    args = ap.parse_args()
    args.out = pathlib.Path(args.out)
    args.keystore = pathlib.Path(args.keystore)

    # 비밀번호/별칭: 인자 > 환경변수 > fdroid/keystore.properties 순으로 읽는다
    # (CI 에서는 조직 시크릿이 환경변수로 주입된다)
    args.storepass = args.storepass or os.environ.get('FDROID_KEYSTORE_PASS')
    args.keypass = args.keypass or os.environ.get('FDROID_KEY_PASS')
    env_alias = os.environ.get('FDROID_KEY_ALIAS')
    if env_alias:
        args.alias = env_alias

    props = FDROID_DIR / 'keystore.properties'
    if props.is_file():
        kv = {}
        # PowerShell Set-Content 로 만든 파일에는 BOM 이 있을 수 있다
        for line in props.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                kv[k.strip()] = v.strip()
        args.storepass = args.storepass or kv.get('FDROID_KEYSTORE_PASS')
        args.keypass = args.keypass or kv.get('FDROID_KEY_PASS')
        args.alias = kv.get('FDROID_KEY_ALIAS', args.alias)

    # CI: 키스토어를 base64 시크릿에서 복원
    ks_b64 = os.environ.get('FDROID_KEYSTORE_BASE64')
    if ks_b64 and not args.keystore.is_file():
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp()) / 'fdroid-keystore.jks'
        tmp.write_bytes(base64.b64decode(ks_b64))
        args.keystore = tmp
        log('키스토어를 FDROID_KEYSTORE_BASE64 에서 복원했습니다')

    return build(args)


if __name__ == '__main__':
    sys.exit(main())
