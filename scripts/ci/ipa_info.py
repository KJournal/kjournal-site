#!/usr/bin/env python3
"""서명 없는 IPA 에서 버전/번들 정보를 읽는다 (Android 의 apk_info.py 에 대응).

    from ipa_info import parse_ipa
    info = parse_ipa('dist/ios/KJournal-5.0-PB1-ios.ipa')
    # {'versionName': '5.0 PB1', 'versionCode': '1', 'bundleId': '...',
    #  'displayName': 'K저널', 'date': '2026-09-29'}

date 는 zip 안 항목의 mtime(빌드 시각)에서 뽑는다. 파일 mtime 을 쓰면 CI 체크아웃
시각으로 바뀌어 배포마다 날짜가 달라지므로 쓰지 않는다.
"""
import plistlib
import zipfile


def parse_ipa(path):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist()
                 if n.startswith('Payload/') and n.endswith('.app/Info.plist')]
        if not names:
            raise ValueError('Payload/*.app/Info.plist 를 찾지 못했습니다: %s' % path)
        # 확장(PlugIns·Watch) 안의 Info.plist 가 아니라 최상위 앱을 고른다.
        name = sorted(names, key=len)[0]
        info = plistlib.loads(z.read(name))

        app_prefix = name[:-len('Info.plist')]
        entries = [i for i in z.infolist()
                   if i.filename.startswith(app_prefix) and not i.is_dir()]
        date = ''
        if entries:
            dt = max(i.date_time for i in entries)
            date = '%04d-%02d-%02d' % (dt[0], dt[1], dt[2])

    return {
        'versionName': str(info.get('CFBundleShortVersionString', '')),
        'versionCode': str(info.get('CFBundleVersion', '')),
        'bundleId': str(info.get('CFBundleIdentifier', '')),
        'displayName': str(info.get('CFBundleDisplayName')
                           or info.get('CFBundleName') or ''),
        'date': date,
    }


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(parse_ipa(sys.argv[1]), ensure_ascii=False, indent=2))
