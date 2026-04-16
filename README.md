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
│   ├── pdfOcr                    # PDF OCR 처리 함수
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   └── pdfSplit                  # PDF 분할 처리 함수
│       ├── lambda_function.py
│       └── requirements.txt
├── README.md
└── requirements.txt              # 로컬 개발 및 테스트용 공통 의존성
```