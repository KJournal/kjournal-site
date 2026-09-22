#!/usr/bin/env bash
# ---------------------------------------------------------------
# 프라이버시 게이트
#   1) 추적 중인 텍스트 파일에서 개인 이메일 탐지
#   2) dist/*.apk 내부(dex/resources/assets)에서 개인 이메일 탐지
#   3) 서명 키/시크릿 파일이 추적되지 않는지 확인
#
#   bash scripts/ci/verify-no-email.sh
# ---------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# python3 가 없는 환경(일부 Windows)에서는 python 으로 폴백
PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$PYTHON" ]] || { echo "python3(또는 python) 이 필요합니다." >&2; exit 1; }

fail=0
ok()  { printf '\033[1;32m[ok]\033[0m   %s\n' "$*"; }
bad() { printf '\033[1;31m[fail]\033[0m %s\n' "$*"; fail=1; }

# 허용되는 (개인정보가 아닌) 주소들
ALLOW_RE='revenuecat\.com|android@android\.com|example\.com|example\.org|invalid|\.local|schemas\.android\.com|w3\.org|apache\.org|json-schema\.org|gnu\.org|github\.com|users\.noreply\.github\.com|noreply\.codeberg\.org|kotlinlang\.org|jetbrains\.com'
# 개인 메일 주소(로컬파트@도메인 형태만) — 스크립트 내 정규식 문자열과 혼동하지 않도록 한다
PERSONAL_RE='[A-Za-z0-9._%+-]+@(gmail\.com|naver\.com|daum\.net|kakao\.com|hanmail\.net|outlook\.com|hotmail\.com|yahoo\.[a-z.]+|protonmail\.com|proton\.me|icloud\.com|me\.com)'
EMAIL_RE='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'

mapfile -t FILES < <(git ls-files || true)
TEXT_FILES=()
for f in "${FILES[@]}"; do
  case "$f" in
    *.apk|*.aab|*.ipa|*.png|*.webp|*.jpg|*.jpeg|*.gif|*.jar|*.jks|*.keystore|*.so) continue ;;
  esac
  [[ -f "$f" ]] && TEXT_FILES+=("$f")
done

echo "── 1. 추적 파일 텍스트 스캔 ─────────────────────────────"
if [[ ${#TEXT_FILES[@]} -eq 0 ]]; then
  bad "git 저장소가 아니거나 추적 파일이 없습니다."
else
  hits=0
  for f in "${TEXT_FILES[@]}"; do
    while IFS= read -r m; do
      [[ -z "$m" ]] && continue
      if [[ ! "$m" =~ $ALLOW_RE ]]; then
        bad "이메일 의심: $f → $m"
        hits=$((hits+1))
      fi
    done < <(grep -Eoh "$EMAIL_RE" "$f" 2>/dev/null | sort -u || true)
  done
  [[ $hits -eq 0 ]] && ok "추적 텍스트 파일에 개인 이메일 없음"
fi

echo ""
echo "── 2. 개인 메일 주소 재검사 (강한 실패) ─────────────────"
if grep -REIn "$PERSONAL_RE" "${TEXT_FILES[@]}" 2>/dev/null | head -20; then
  bad "개인 메일 주소가 발견되었습니다"
else
  ok "개인 메일 주소 없음"
fi

echo ""
echo "── 3. 공개 APK 내부 스캔 ───────────────────────────────"
shopt -s nullglob
APKS=(dist/*.apk)
shopt -u nullglob

if [[ ${#APKS[@]} -eq 0 ]]; then
  ok "dist/ 에 APK 없음 (스킵)"
else
  for apk in "${APKS[@]}"; do
    if "$PYTHON" - "$apk" "$ALLOW_RE" <<'PY'
import re, sys, zipfile

apk, allow = sys.argv[1], sys.argv[2]
data = b''
with zipfile.ZipFile(apk) as z:
    for n in z.namelist():
        if n.endswith(('.dex', '.xml', '.json', '.txt', '.properties')):
            data += z.read(n)

pat = re.compile(rb'[A-Za-z0-9._%+-]*[A-Za-z][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.'
                 rb'(?:com|net|org|io|dev|app|kr|co|uk|de|fr|jp|cn|ru|info|biz|me|xyz|site|online|store|cloud|tech)\b')
allow_re = re.compile(allow.encode())

bad = set()
for m in pat.finditer(data):
    if not allow_re.search(m.group(0)):
        bad.add(m.group(0).decode('utf-8', 'replace'))

if bad:
    print(f'[fail] {apk} 내부에서 이메일 의심 {len(bad)}건:')
    for s in sorted(bad)[:20]:
        print('        ', s)
    sys.exit(1)
print(f'[ok]   {apk}: 개인 이메일 없음')
PY
    then
      :
    else
      fail=1
    fi
  done
fi

echo ""
echo "── 4. 시크릿/키 파일 추적 여부 ─────────────────────────"
leaked="$(git ls-files | grep -Ei '(^|/)(keystore\.jks|.*\.keystore|.*\.jks|keystore\.properties|\.env)$|base64$' || true)"
if [[ -n "$leaked" ]]; then
  bad "키/시크릿 파일이 추적되고 있습니다:"
  printf '       %s\n' $leaked
else
  ok "키/시크릿 파일 미추적"
fi

echo ""
if [[ $fail -ne 0 ]]; then
  printf '\033[1;31m프라이버시 게이트 실패\033[0m — docs/PRIVACY.md 를 확인하세요.\n'
  exit 1
fi
printf '\033[1;32m프라이버시 게이트 통과\033[0m\n'
