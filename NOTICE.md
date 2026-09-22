# NOTICE / 라이선스 고지

## 원본

이 배포판은 아래 프로젝트를 기반으로 한다.

- **KJournal (PsychonautWiki Journal)**
  - 소스: https://github.com/isaakhanimann/psychonautwiki-journal-android
  - 저작자: Isaak Hanimann
  - 라이선스: **GNU General Public License v3.0 (GPL-3.0)**

## 라이선스

이 저장소와 `dist/` 의 APK 는 **GPL-3.0** 으로 배포된다.
GPL-3.0 전문은 https://www.gnu.org/licenses/gpl-3.0.html 에서 확인할 수 있다.

GPL-3.0 에 따라:

- 이 바이너리를 재배포할 때는 **해당 소스 코드를 함께 제공**해야 한다.
- 원본 저작자 표시와 라이선스 고지를 유지해야 한다.
- 수정한 경우 수정 사실을 명시해야 한다.

## 수정 내역 (요약)

원본 대비 변경 사항은 `recon/BUGFIX-notification-crash.md` 와 GitHub Release 노트에 기록한다.

- 한국어 UI 및 문구
- 타임라인 실시간 알림(포그라운드 서비스) 및 위젯
- 자체 업데이트(OTA) 도구
- 버그 수정: FGS 권한 크래시, 한국어 문자열 길이 크래시, 알림 토글/아이콘 상태

## 서드파티

앱에 포함된 서드파티 라이브러리(AndroidX/Compose, kotlinx.serialization, Room, RevenueCat 등)는
각 라이선스를 따른다. RevenueCat SDK 는 별도 라이선스 약관이 적용된다.

## 소스 제공 (GPL 대응)

GPL-3.0 준수를 위해, 배포하는 APK 에 대응하는 소스는 아래 중 하나로 제공한다.

- 본 저장소의 릴리즈 태그 (예: `v5.0.4`) — private 인 경우 접근 권한 부여 필요
- 공개 미러 저장소: `menhera_network/fdroid-repo` 의 `sources/` 디렉터리 또는 Release 첨부
