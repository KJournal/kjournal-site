#!/usr/bin/env bash
# ---------------------------------------------------------------
# F-Droid 메타데이터 검사
#   - 메타데이터 디렉터리명이 실제 APK 의 packageName 과 일치하는지
#   - 필수 파일(title/short_description/full_description) 존재 여부
#   - short_description 길이(80자) 제한
#   - 체인지로그 파일명이 versionCode(숫자)인지
#   - APK 의 versionCode 와 체인지로그 존재 여부
# ---------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="$(command -v python3 || command -v python || true)"
[[ -n "$PYTHON" ]] || { echo "python3(또는 python) 이 필요합니다." >&2; exit 1; }

fail=0
ok()  { printf '\033[1;32m[ok]\033[0m   %s\n' "$*"; }
bad() { printf '\033[1;31m[fail]\033[0m %s\n' "$*"; fail=1; }

shopt -s nullglob
APKS=(dist/*.apk)
shopt -u nullglob

if [[ ${#APKS[@]} -eq 0 ]]; then
  bad "dist/ 에 APK 가 없습니다."
  exit 1
fi

for apk in "${APKS[@]}"; do
  read -r pkg vcode vname < <("$PYTHON" "$REPO_ROOT/scripts/ci/apk_info.py" "$apk")
  echo "APK: $apk → pkg=${pkg:-?} versionCode=${vcode:-?} versionName=${vname:-?}"
  [[ -n "$pkg" ]] || { bad "패키지명을 읽지 못했습니다."; continue; }

  MDIR="fdroid/metadata/$pkg"
  [[ -d "$MDIR" ]] || { bad "메타데이터 디렉터리 없음: $MDIR"; continue; }

  for loc in "$MDIR"/*/; do
    loc="$(basename "$loc")"
    for f in title.txt short_description.txt full_description.txt; do
      [[ -f "$MDIR/$loc/$f" ]] || bad "누락: $MDIR/$loc/$f"
    done
    if [[ -f "$MDIR/$loc/short_description.txt" ]]; then
      len=$(wc -m < "$MDIR/$loc/short_description.txt" | tr -d ' ')
      [[ "$len" -le 80 ]] || bad "$loc/short_description.txt 길이 초과: ${len}자 (<=80)"
    fi
    if [[ -d "$MDIR/$loc/changelogs" ]]; then
      for cl in "$MDIR/$loc/changelogs"/*; do
        base="$(basename "$cl")"
        [[ "$base" =~ ^[0-9]+\.txt$ ]] || bad "체인지로그 파일명은 <versionCode>.txt 여야 합니다: $cl"
      done
    fi
  done

  if [[ -n "$vcode" ]]; then
    for loc in "$MDIR"/*/; do
      loc="$(basename "$loc")"
      [[ -f "$MDIR/$loc/changelogs/$vcode.txt" ]] || \
        printf '\033[1;33m[warn]\033[0m %s/changelogs/%s.txt 없음 (선택)\n' "$loc" "$vcode"
    done
  fi
  ok "$pkg 메타데이터 검사 완료"
done

echo
[[ $fail -eq 0 ]] || { echo "F-Droid 메타데이터 검사 실패"; exit 1; }
echo "F-Droid 메타데이터 검사 통과"
