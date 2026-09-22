#!/usr/bin/env python3
"""APK 의 binary AndroidManifest.xml(AXML)에서 메타데이터를 읽는다.

사용:
    python3 scripts/ci/apk_info.py dist/KJournal-5-PB4.apk
출력:
    <packageName> <versionCode> <versionName>

라이브러리로도 사용:
    from apk_info import parse_apk
    info = parse_apk('dist/KJournal-5-PB4.apk')
    # info['package'], info['versionCode'], info['versionName'],
    # info['minSdkVersion'], info['targetSdkVersion'], info['permissions']

외부 도구(aapt) 없이 동작하도록 AXML 을 최소 파싱한다.
"""
import struct
import sys
import zipfile

STRING_POOL = 0x0001
RESOURCE_MAP = 0x0180
START_ELEMENT = 0x0102

ATTR_NAME = 0x01010003
ATTR_VERSION_CODE = 0x0101021B
ATTR_VERSION_NAME = 0x0101021C
ATTR_MIN_SDK = 0x0101020C
ATTR_TARGET_SDK = 0x01010270

TYPE_STRING = 0x03
TYPE_INT_DEC = 0x10
TYPE_INT_HEX = 0x11


def read_string_pool(data, pos):
    count, _style_count, flags, strings_start, _styles_start = struct.unpack_from('<IIIII', data, pos + 8)
    utf8 = bool(flags & (1 << 8))
    offsets = [struct.unpack_from('<I', data, pos + 28 + 4 * i)[0] for i in range(count)]
    strings = []
    base = pos + strings_start
    for off in offsets:
        p = base + off
        if utf8:
            _chars, blen = struct.unpack_from('<BB', data, p)
            p += 2
            strings.append(data[p:p + blen].decode('utf-8', 'replace'))
        else:
            clen = struct.unpack_from('<H', data, p)[0]
            p += 2
            strings.append(data[p:p + clen * 2].decode('utf-16-le', 'replace'))
    return strings


def parse_manifest(data):
    """AndroidManifest.xml(AXML) 바이트를 파싱해 필요한 값들을 dict 로 돌려준다."""
    magic = struct.unpack_from('<I', data, 0)[0]
    if magic != 0x00080003:
        raise ValueError('AXML 매직이 아닙니다')

    pos = 8
    strings = []
    resmap = []
    info = {
        'package': '',
        'versionCode': '',
        'versionName': '',
        'minSdkVersion': '',
        'targetSdkVersion': '',
        'permissions': [],
    }

    while pos < len(data):
        ctype, header_size, chunk_size = struct.unpack_from('<HHI', data, pos)
        if chunk_size == 0:
            break

        if ctype == STRING_POOL:
            strings = read_string_pool(data, pos)
        elif ctype == RESOURCE_MAP:
            n = (chunk_size - header_size) // 4
            resmap = [struct.unpack_from('<I', data, pos + header_size + 4 * i)[0] for i in range(n)]
        elif ctype == START_ELEMENT:
            name_idx = struct.unpack_from('<I', data, pos + 20)[0]
            element = strings[name_idx] if name_idx < len(strings) else ''
            attr_start, attr_size, attr_count = struct.unpack_from('<HHH', data, pos + 24)
            base = pos + 16 + attr_start

            for i in range(attr_count):
                a = base + i * attr_size
                _ns, a_name, a_raw = struct.unpack_from('<III', data, a)
                a_type = data[a + 15]
                a_data = struct.unpack_from('<I', data, a + 16)[0]
                res_id = resmap[a_name] if a_name < len(resmap) else 0

                def str_val():
                    if a_type == TYPE_STRING and a_data < len(strings):
                        return strings[a_data]
                    if a_raw != 0xFFFFFFFF and a_raw < len(strings):
                        return strings[a_raw]
                    return ''

                if res_id == ATTR_VERSION_CODE:
                    info['versionCode'] = str(a_data) if a_type in (TYPE_INT_DEC, TYPE_INT_HEX) else ''
                elif res_id == ATTR_VERSION_NAME:
                    info['versionName'] = str_val()
                elif res_id == ATTR_MIN_SDK:
                    info['minSdkVersion'] = str(a_data) if a_type in (TYPE_INT_DEC, TYPE_INT_HEX) else str_val()
                elif res_id == ATTR_TARGET_SDK:
                    info['targetSdkVersion'] = str(a_data) if a_type in (TYPE_INT_DEC, TYPE_INT_HEX) else str_val()
                elif element == 'uses-permission' and res_id == ATTR_NAME:
                    v = str_val()
                    if v:
                        info['permissions'].append(v)
                elif element == 'manifest' and res_id == 0:
                    plain = strings[a_name] if a_name < len(strings) else ''
                    if plain == 'package':
                        info['package'] = str_val()
        pos += chunk_size

    info['permissions'] = sorted(set(info['permissions']))
    return info


def parse_apk(path):
    """APK 파일에서 매니페스트 정보를 읽는다."""
    with zipfile.ZipFile(path) as z:
        data = z.read('AndroidManifest.xml')
    return parse_manifest(data)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    info = parse_apk(sys.argv[1])
    print(f"{info['package']} {info['versionCode']} {info['versionName']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
