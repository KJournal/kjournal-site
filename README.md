# kjournal-site

KJournal Android 배포 저장소. **GitHub Pages** 로 다음을 제공한다.

- **다운로드/메인 사이트**: <https://kjournal.github.io/kjournal-site/>
- **F-Droid 커스텀 저장소**: <https://kjournal.github.io/kjournal-site/fdroid/repo>
- **OTA 업데이트 정보**: <https://kjournal.github.io/kjournal-site/ota/version.json>
- **OTA APK 다운로드 경로**: `https://kjournal.github.io/kjournal-site/apk/<파일명>.apk`

## 구조

| 경로 | 내용 |
|---|---|
| `dist/` | 배포할 APK (앱 저장소 CI 가 커밋/푸시) |
| `site/index.html` | 다운로드 페이지 템플릿 (`__VERSION__` 등 치환) |
| `fdroid/metadata/<pkg>/` | F-Droid 메타데이터 (제목/설명/아이콘/체인지로그) |
| `fdroid/repo-landing.html` | 저장소 주소를 브라우저로 열었을 때의 안내 페이지 |
| `fdroid/icon.png` | 앱/저장소 아이콘 |
| `scripts/site/build-site.py` | `site/` + `dist/` → `public/` 조립 (+ OTA JSON) |
| `scripts/fdroid/build-index.py` | fdroidserver 없이 `index-v1` 저장소 생성 + 서명 |
| `scripts/ci/` | `apk_info.py`, 메타데이터/프라이버시 검사 |
| `.github/workflows/deploy.yml` | main push/수동 실행 → `public/` 빌드 → Pages 배포 |

## 배포 흐름

```
앱 저장소(KJournal/KJournal) main push
  └─ APK 빌드·서명 → Release 자산 + 이 저장소 dist/ 로 APK/체인지로그 푸시
       └─ 이 저장소 main push → deploy.yml
            ├─ F-Droid index-v1 생성/서명
            ├─ OTA version.json 생성
            └─ GitHub Pages 배포
```

## 필요한 시크릿 (Settings → Secrets and variables → Actions)

| 시크릿 | 설명 |
|---|---|
| `FDROID_KEYSTORE_BASE64` | F-Droid 저장소 index 서명 키스토어(base64) |
| `FDROID_KEYSTORE_PASS` | 키스토어 비밀번호 |
| `FDROID_KEY_PASS` | 키 비밀번호 |
| `FDROID_KEY_ALIAS` | 키 별칭 (기본 `kjournal`) |

## 로컬 빌드

```bash
# F-Droid 키가 있으면 fdroid/keystore.jks 로 두고:
FDROID_KEYSTORE_PASS=... FDROID_KEY_PASS=... python3 scripts/site/build-site.py
# 키가 없으면 F-Droid 저장소 없이 페이지만:
python3 scripts/site/build-site.py --skip-index
```

## 라이선스

GPL-3.0. `NOTICE.md` 참고.
