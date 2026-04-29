### 개요

`gerrit-review`는 로컬 Git 체크아웃을 기준으로 Gerrit 리뷰를 조회하고, 특히 AI 리뷰어가 남긴 인라인 코멘트를 실제 코드와 호출 경로에 비춰 검증하는 스킬이다. Gerrit 변경 번
호, 현재 `HEAD`, 커밋 메시지의 `Change-Id`를 이용해 대상 리뷰를 찾고, 코멘트가 실제 결함인지, 과장된 지적인지, 오탐인지 분류한다.

### 사용 목적

- Gerrit 패치셋에 달린 AI 리뷰 코멘트의 타당성을 코드 근거로 판단한다.
- 오탐 코멘트에 대해 짧고 사실적인 Gerrit 답변 초안을 만든다.
- 실제 문제가 맞는 코멘트에 대해 최소 수정 방향을 정리한다.
- Gerrit draft comment를 생성하거나, 명시적 확인을 받은 뒤 기존 draft를 게시한다.
- 계정 설정, SSH 접근, 패치셋 불일치, REST 인증 문제를 분리해 진단한다.

### 입력 예시

```text
현재 HEAD에 연결된 Gerrit 리뷰에서 AI 리뷰어 코멘트를 분석해줘.
```

```text
Gerrit change 123456의 현재 patch set에 달린 AI 코멘트가 맞는지 검증하고 답변 초안을 만들어줘.
```

```text
오탐으로 판단된 코멘트만 Gerrit draft comment로 생성해줘.
```

```text
이미 만들어둔 draft를 실제 게시해줘. 대상 change와 patch set을 보여준 뒤 확인을 받아줘.
```

### 출력 예시

```text
사실
- 대상 변경: 123456, patch set 7
- 로컬 HEAD와 Gerrit currentPatchSet revision이 일치합니다.
- AI 리뷰어 인라인 코멘트 3개를 확인했습니다.

추측
- 2개 코멘트는 실제 호출 경로상 도달 불가능해 false_positive로 판단됩니다.
- 1개 코멘트는 락 순서에 대한 추가 확인이 필요해 needs_more_context로 분류됩니다.

Gerrit reply drafts
- file/path/Foo.java:120
  [Codex로 생성됨] 이 경로에서는 bar가 null이 될 수 없습니다. 호출자는 Foo#create에서 non-null 값만 전달하고, 중간 분기에서도 값을 재할당하지 않습니다.

Posting status
- draft only, not published
```

### 활용 팁

- 먼저 `scripts/configure_account.py --show`로 계정 설정 상태를 확인한다.
- Gerrit 대상이 불명확하면 변경 번호를 직접 전달하는 것이 가장 빠르다.
- 로컬 `HEAD`와 Gerrit current patch set이 다르면 분석 결과가 틀어질 수 있으므로 먼저 패치셋을 맞춘다.
- 오탐 판단은 반드시 파일명과 라인 근거를 함께 남긴다.
- draft 생성과 실제 게시를 분리해서 사용한다. draft 요청은 리뷰어에게 보이는 게시가 아니다.
- 답변 초안은 짧게 유지하고, 리뷰어의 표현을 반박하기보다 실제 코드 경로를 설명한다.

### 주의사항

- 계정 설정이 없거나 불완전하면 Gerrit 조회, draft 생성, 게시 작업을 진행하지 않는다.
- 비밀번호, 인증 헤더, Gerrit base URL 같은 민감 정보는 명령줄 인자나 출력에 노출하지 않는다.
- `진행해`, `올려`, `계속해` 같은 모호한 표현만으로 draft 게시나 실제 코멘트 게시를 수행하지 않는다.
- 실제 게시 전에는 대상 change, patch set, 코멘트 수, notify 값, dry-run JSON을 보여주고 두 번째 명시적 확인을 받아야 한다.
- 로컬 `HEAD`와 Gerrit current patch set revision이 다르면 사용자가 불일치를 명시적으로 수락하기 전까지 실제 게시를 하지 않는다.
- 이 스킬은 리뷰 코멘트 검증과 답변 준비용이다. submit, abandon, restore, rebase, move, label vote는 기본 작업 범위에 포함하지 않는다.
