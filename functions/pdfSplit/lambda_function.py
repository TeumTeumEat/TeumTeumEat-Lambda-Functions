# 내장 라이브러리
import io
import json
import math
import os
import re
import time
import urllib.parse

# 외부 라이브러리 (Lambda layer 추가 필요)
import boto3
import requests
from PyPDF2 import PdfReader, PdfWriter

s3 = boto3.client('s3')
INTERNAL_TOKEN = os.environ.get('INTERNAL_WEB_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def lambda_handler(event, context):
    try:
        # S3 이벤트 정보 추출
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key'] # origin/6d972bcb-b207-4c33-ac47-7816f4fafbc0_11강_Stochastic_methods.pdf
        key = urllib.parse.unquote_plus(key)
        filename = key.split('/')[-1].replace(".pdf", "")
        origin_file_name = filename.split('_', 1)[1]

        # S3에서 파일 읽기
        response = s3.get_object(Bucket=bucket, Key=key)
        file_content = response['Body'].read()

        # PDF 읽기
        reader = PdfReader(io.BytesIO(file_content))

        headers = {
            "X-INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Content-Type": "application/json"
        }
        # 암호화 여부 체크
        if reader.is_encrypted:
            print("PDF is encrypted")
            print("fileKey: " + key)
            error_payload = {
                "fileName": origin_file_name,
                "fileKey": key,
                "totalParts": 0,
                "needOcr": False,
                "rawContent": "암호화된 PDF입니다. LLM 생성 시 사용자에게 암호화된 PDF로는 생성할 수 없다고 알립니다.",
                "estimateTime": 0
                # "success": False,
                # "reason": "ENCRYPTED_FILE"
            }
            requests.post(
                WEBHOOK_URL,
                json=error_payload,
                headers=headers,
                timeout=10
            )
            return {
                'statusCode': 400,
                'body': json.dumps('Encrypted file handled.')
            }

        total_pages = len(reader.pages)

        # 4. OCR 필요 여부 검사 [1페이지는 제목인 경우가 많으므로 중간 페이지 검사]
        target_page_idx = total_pages // 2
        page = reader.pages[target_page_idx]
        start_time = time.time()
        text = page.extract_text()
        end_time = time.time()

        totalParts = 0
        needOcr = False
        all_text = []

        if check_text_quality(text):
            sample_page_ms = (end_time - start_time) * 1000
            estimateTime = sample_page_ms * total_pages
            estimateTime = max(round(estimateTime, -3), 4000)
        # 임계값 이하. OCR 호출 필요
        else:
            needOcr = True
            totalParts = math.ceil(total_pages / 10)
            if total_pages > 10:
                estimateTime = 30 + totalParts
            else:
                estimateTime = total_pages * 3

        # 예상 소요 시간 서버로 먼저 전송
        init_payload = {
            "fileName": origin_file_name,
            "fileKey": key,
            "totalParts": totalParts,
            "needOcr": True, # 아마도 의도된 True (백엔드 코드 분석 해봐야함)
            "estimateTime": estimateTime
            # "success": True
        }
        requests.post(
            WEBHOOK_URL,
            json=init_payload,
            headers=headers,
            timeout=10
        )

        # 텍스트 추출 또는 OCR 호출
        if not needOcr:
            for page in reader.pages:
                all_text.append(page.extract_text())  # [].append .join 이 성능이 더 나을지?

        # OCR : 분할 key들을 저장
        split_keys = []

        init_payload = {
            "fileName": origin_file_name,
            "fileKey": key,
            "totalParts": totalParts,
            "needOcr": needOcr,
            "rawContent": "\n".join(all_text),
            "estimateTime": estimateTime
            # "success": True
        }

        requests.post(
            WEBHOOK_URL,
            json=init_payload,
            headers=headers,
            timeout=10
        )
        s3.delete_object(Bucket=bucket, Key=key)
        print("fileName" + str(origin_file_name))
        print("fileKey" + str(key))
        print("totalParts" + str(totalParts))
        print("needOcr" + str(needOcr))
        print(f"rawContent(앞 30자): {all_text[:30]}")
        print("estimateTime" + str(estimateTime))

        if needOcr:
            # 10페이지 단위 분할
            for start in range(0, total_pages, 10):
                writer = PdfWriter()
                end = min(start + 10, total_pages)

                for i in range(start, end):
                    writer.add_page(reader.pages[i])

                # 메모리 버퍼에 저장
                output_buffer = io.BytesIO()
                writer.write(output_buffer)
                output_buffer.seek(0)

                # S3 업로드
                output_key = f"split/{filename}_part_{start // 10}.pdf"
                s3.put_object(
                    Bucket=bucket,
                    Key=output_key,
                    Body=output_buffer.getvalue(),
                    ContentType='application/pdf'
                )
                split_keys.append(output_key)
                # 네이버 OCR API가 1초당 1개의 요청을 최대로 하고있어, 분할 파일 생성에 1초 간격을 두어 API를 호출하도록 설정
                time.sleep(1)

        return {
            'statusCode': 200,
            'body': json.dumps(f'Successfully split into {len(split_keys)} files')
        }


    except Exception as e:
        # # 에러 유형 판별
        # if isinstance(e, requests.exceptions.Timeout):
        #     reason = "TIMEOUT"
        # elif "encrypted" in str(e).lower():
        #     reason = "ENCRYPTED_FILE"
        # else:
        #     reason = "SERVER_ERROR"

        # error_payload = {
        #     "fileKey": key,
        #     "success": False,
        #     "reason": reason
        # }

        # try:
        #     requests.post(
        #         WEBHOOK_URL,
        #         json=error_payload,
        #         headers=headers,
        #         timeout=5
        #     )
        # except Exception as webhook_error:
        #     print(f"Webhook Failed: {str(webhook_error)}")

        print(f"Lambda Error: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e), 'reason': reason})
        }

def check_text_quality(text):
    # 텍스트가 없거나 10글자 미만이라면 False
    if not text or len(text.strip()) < 10:
        return False

    # 가독성 있는 문자(정상 한글, 영어, 숫자, 기본 문장부호) 추출
    # 이 범위에 없는 문자는 모두 '노이즈'로 간주
    printable_pattern = re.compile(r'[가-힣a-zA-Z0-9\s.,!?()\-:/%]')
    printable_chars = printable_pattern.findall(text)

    cleanliness_ratio = len(printable_chars) / len(text)

    # [임계값] 깨진 문자가 전체의 30% 이상이면 OCR 진행
    if cleanliness_ratio < 0.7:
        return False

    # 유효 단어 추출 (정규 표현식 강화)
    # 한글: 완전한 글자(2자 이상)
    # 영어: 모음이 포함된 3자 이상의 단어
    kor_words = re.findall(r'[가-힣]{2,}', text)
    eng_words = re.findall(r'\b(?=[a-zA-Z]*[aeiouAEIOU])[a-zA-Z]{3,}\b', text)

    total_valid_count = len(kor_words) + len(eng_words)

    # [임계값] 청결도는 높으나 유효 단어가 너무 적은 경우 (그림 위주 판정)
    if total_valid_count < 5:
        return False

    return True