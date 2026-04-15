# 내장 라이브러리
import json
import os
import re
import time
import uuid
import urllib.parse

# 외부 라이브러리 (Lambda layer 추가 필요)
import boto3
import botocore
import requests

s3 = boto3.client('s3')
OCR_URL = os.environ.get('NAVER_OCR_URL')
SECRET_KEY = os.environ.get('NAVER_OCR_SECRET_KEY')
INTERNAL_TOKEN = os.environ.get('INTERNAL_WEB_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def lambda_handler(event, context):
    try:
        # S3 이벤트에서 분할된 파일 정보 추출
        bucket = event['Records'][0]['s3']['bucket']['name']
        raw_key = event['Records'][0]['s3']['object']['key']  # split/6d972bcb-b207-4c33-ac47-7816f4fafbc0_11강_Stochastic_methods_part_1.pdf
        key = urllib.parse.unquote_plus(raw_key)

        # 파일의 S3 URL 생성 (네이버 OCR에 전달할 경로)
        # S3 객체가 공개되어 있지 않다면 Presigned URL을 쓰거나
        # 직접 파일을 읽어서(Body) 보낼 수도 있지만, 여기서는 URL 방식을 유지합니다.
        region = "ap-northeast-2"
        image_url = f"https://{bucket}.s3.{region}.amazonaws.com/{raw_key}"

        # 네이버 OCR API 요청 페이로드 구성
        request_body = {
            "version": "V2",
            "requestId": str(uuid.uuid4()),
            "timestamp": int(round(time.time() * 1000)),
            "images": [
                {
                    "format": "pdf",
                    "name": str(uuid.uuid4()),
                    "url": image_url
                }
            ]
        }

        headers = {
            "X-OCR-SECRET": SECRET_KEY,
            "Content-Type": "application/json"
        }

        # 네이버 OCR API 호출
        ocr_response = requests.post(
            OCR_URL,
            headers=headers,
            json=request_body,
            timeout=180
        )
        ocr_data = ocr_response.json()

        # 결과 추출 (Full Text)
        # 네이버 응답 구조에 맞춰 텍스트 추출
        full_text = []
        if "images" in ocr_data:
            # 여러 페이지의 텍스트를 하나로 합침
            for img in ocr_data["images"]:
                if "fields" in img:
                    full_text.append(" ".join([field.get("inferText", "") for field in img["fields"]]))

        # 백엔드 웹훅으로 결과 전송
        fileKey = re.sub(r'_part_\d+', '', key.removeprefix("split/"))
        callback_payload = {
            "fileKey": f"origin/{fileKey}",
            "ocrText": ''.join(full_text),
            "partIndex": key.split('_part_')[-1].replace('.pdf', '') # 순서 맞추기용
            # "success": True
        }

        headers = {
            "X-INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Content-Type": "application/json"
        }

        print("Payload: " + json.dumps(callback_payload, indent=4, ensure_ascii=False))

        requests.post(
            WEBHOOK_URL,
            json=callback_payload,
            headers=headers,
            timeout=10
        )
        s3.delete_object(Bucket=bucket, Key=key)

        return {
            'statusCode': 200,
            'body': json.dumps('OCR Processed and Webhook sent')
        }

    except Exception as e:
        # error_payload = {
        #     "fileKey": key,
        #     "success": False,
        #     "reason": "SERVER_ERROR"
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