import numpy as np
from paddleocr import PaddleOCR

print("PaddleOCR version:", __import__('paddleocr').__version__)

ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
print("OCR object created:", type(ocr))

# Blank white image — no text should be detected
img = np.ones((200, 400, 3), dtype='uint8') * 255
result = ocr.ocr(img, cls=True)
print("OCR result type:", type(result))
print("Result length:", len(result) if result else 0)
print("Result[0]:", result[0] if result else None)
print("SUCCESS")
