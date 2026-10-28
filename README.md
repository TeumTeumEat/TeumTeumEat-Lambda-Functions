### 개발환경 설정
```bash
# 의존성 설치
pip install -r requirements.txt
```

### 디렉터리 구조
```
.
├── .github
│   └── workflows
│       └── deploy-lambda.yaml    # GitHub Actions 배포 워크플로우
├── functions                     # Lambda 함수 모음
│   ├── lambdaEdge                # Lambda@Edge 함수 모음 (us-east-1 배포)
│   │   └── image-resizer         # 이미지 리사이징 함수
│   │       ├── index.js
│   │       ├── package.json
│   │       └── package-lock.json
│   ├── pdfOcr                    # PDF OCR 처리 함수
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   └── pdfSplit                  # PDF 분할 처리 함수
│       ├── lambda_function.py
│       └── requirements.txt
├── README.md
└── requirements.txt              # 로컬 개발 및 테스트용 공통 의존성
```

### 새 함수 추가하기
`main`, `dev` 브랜치에 push하면 GitHub Actions가 변경된 함수만 배포합니다.
워크플로우는 **이미 존재하는 함수의 코드만 업데이트**하므로, 아래 작업을 먼저 해야 합니다.

#### Lambda (Python)
1. AWS 콘솔에서 **디렉터리명과 같은 이름**으로 함수 생성 (`AWS_REGION` 변수의 리전)
2. `deploy-lambda.yaml`의 `deploy` job `matrix.function_dir`에 함수명 추가

#### Lambda@Edge (Node.js)
1. AWS 콘솔에서 **디렉터리명과 같은 이름**으로 함수 생성
   - 리전 **us-east-1**, 아키텍처 **x86_64** (Lambda@Edge 제약)
   - 실행 역할 신뢰 정책에 `edgelambda.amazonaws.com` 추가
2. 버전을 하나 발행해서 CloudFront behavior에 **처음 한 번은 직접 연결** (이후 버전 교체는 워크플로우가 자동 처리)
3. `deploy-lambda.yaml`의 `deploy-edge` job `matrix.function_dir`에 함수명 추가
4. `package-lock.json` 커밋 (배포 시 `npm ci` 사용)

> **Lambda@Edge 주의사항**
> - 환경변수 사용 불가
> - Lambda가 직접 생성하는 응답은 헤더 포함 최대 1MB
> - CloudWatch 로그는 us-east-1이 아니라 **요청을 처리한 엣지와 가까운 리전**에 `/aws/lambda/us-east-1.<함수명>`으로 생성됨 (국내는 보통 ap-northeast-2)

### 함수별 참고사항

#### image-resizer
origin-response에서 쿼리 파라미터(`w`, `h`, `f`, `q`)로 S3 이미지를 변환합니다. 허용 값은 `index.js` 상단 상수 참고.
변환할 수 없는 경우 원본을 그대로 반환하므로, 원본이 나오면 로그를 확인하세요.

콘솔 설정
- 런타임 `nodejs24.x`, 메모리 1024MB 이상 권장
- 실행 역할에 이미지 버킷 `s3:GetObject` 권한
- CloudFront 캐시 정책의 캐시 키에 쿼리 문자열 `w`, `h`, `f`, `q` **반드시 포함** (누락 시 파라미터가 전달되지 않음)
