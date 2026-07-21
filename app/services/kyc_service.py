import boto3
import requests
import io
import base64
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import hashlib
import json
from app.core.config import settings
import logging
import re

# Optional dependencies for advanced KYC features
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    face_recognition = None

import importlib.util
DEEPFACE_AVAILABLE = importlib.util.find_spec("deepface") is not None

logger = logging.getLogger(__name__)

class KYCService:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        self.rekognition_client = boto3.client(
            'rekognition',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        self.ocr_api_key = getattr(settings, 'OCR_API_KEY', 'helloworld')
        
    async def upload_document_to_s3(self, file, user_id: int, doc_type: str) -> str:
        """Upload document to S3 with proper organization"""
        try:
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_hash = hashlib.md5(file.read()).hexdigest()[:8]
            file.seek(0)  # Reset file pointer
            
            filename = f"kyc/{user_id}/{doc_type}_{timestamp}_{file_hash}.jpg"
            
            # Upload to S3
            self.s3_client.upload_fileobj(
                file,
                'salon-connect-kyc',  # Create this bucket in AWS S3
                filename,
                ExtraArgs={
                    'ContentType': 'image/jpeg',
                    'ACL': 'private'  # Or 'public-read' if you want public URLs
                }
            )
            
            # Generate pre-signed URL (valid for 7 days)
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': 'salon-connect-kyc',
                    'Key': filename
                },
                ExpiresIn=604800  # 7 days
            )
            
            logger.info(f"Document uploaded to S3: {filename}")
            return url
            
        except Exception as e:
            logger.error(f"Error uploading to S3: {str(e)}")
            raise
    
    async def extract_document_data(self, image_url: str) -> Dict[str, Any]:
        """Extract text from ID document using OCR"""
        try:
            # Download image
            response = requests.get(image_url)
            image_bytes = io.BytesIO(response.content)
            
            # Convert to base64 for OCR API
            encoded_string = base64.b64encode(image_bytes.getvalue()).decode()
            
            # Call OCR.space API
            payload = {
                'apikey': self.ocr_api_key,
                'base64Image': f'data:image/jpeg;base64,{encoded_string}',
                'language': 'eng',
                'isOverlayRequired': False,
                'scale': True,
                'OCREngine': 2  # Engine 2 is more accurate
            }
            
            result = requests.post(
                'https://api.ocr.space/parse/image',
                data=payload,
                timeout=30
            )
            
            ocr_result = result.json()
            
            if ocr_result.get('IsErroredOnProcessing'):
                logger.warning(f"OCR Error: {ocr_result.get('ErrorMessage')}")
                return {}
            
            # Parse extracted text
            parsed_text = ocr_result.get('ParsedResults', [{}])[0].get('ParsedText', '')
            
            # Extract specific fields (this is simplified - you'd want more sophisticated parsing)
            extracted_data = {
                'raw_text': parsed_text,
                'id_number': self._extract_id_number(parsed_text),
                'full_name': self._extract_name(parsed_text),
                'date_of_birth': self._extract_date(parsed_text),
                'confidence': ocr_result.get('ParsedResults', [{}])[0].get('FileParseExitCode', 0)
            }
            
            logger.info(f"OCR extracted data: {extracted_data}")
            return extracted_data
            
        except Exception as e:
            logger.error(f"OCR extraction failed: {str(e)}")
            return {}
    
    def _extract_id_number(self, text: str) -> Optional[str]:
        """Extract ID number from text"""
        # Look for Ghana Card format: GHA-XXXXXXXXX-X
        import re
        patterns = [
            r'GHA-\d{9}-\d',  # Ghana Card
            r'\d{6}[A-Z]\d{2}[A-Z]',  # Passport-like
            r'[A-Z]\d{6,8}',  # License formats
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
    
    def _extract_name(self, text: str) -> Optional[str]:
        """Extract name from text using basic NLP"""
        # This is simplified - in production, use proper NLP libraries
        lines = text.split('\n')
        for line in lines[:5]:  # Check first 5 lines
            line = line.strip()
            if (len(line.split()) >= 2 and  # At least 2 words
                any(word.istitle() for word in line.split()) and  # Has title case
                len(line) < 50):  # Not too long
                return line
        return None
    
    def _extract_date(self, text: str) -> Optional[str]:
        """Extract date from text"""
        import re
        date_patterns = [
            r'\d{2}/\d{2}/\d{4}',
            r'\d{2}-\d{2}-\d{4}',
            r'\d{4}-\d{2}-\d{2}',
            r'\d{2} \w+ \d{4}',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return None
    
    async def verify_document_authenticity(self, front_url: str, back_url: Optional[str] = None) -> Dict[str, Any]:
        """Verify if document is authentic using AWS Rekognition"""
        try:
            # Download images
            front_response = requests.get(front_url)
            back_response = requests.get(back_url) if back_url else None
            
            # Use AWS Rekognition for document analysis
            front_bytes = front_response.content
            back_bytes = back_response.content if back_response else None
            
            # Analyze document with Rekognition
            front_analysis = self.rekognition_client.detect_text(
                Image={'Bytes': front_bytes}
            )
            
            # Check for security features
            security_checks = {
                'has_text': len(front_analysis.get('TextDetections', [])) > 0,
                'has_printed_text': any(
                    detection.get('Type') == 'LINE' 
                    for detection in front_analysis.get('TextDetections', [])
                ),
                'text_confidence': np.mean([
                    detection.get('Confidence', 0) 
                    for detection in front_analysis.get('TextDetections', []) 
                    if detection.get('Type') == 'LINE'
                ]) if front_analysis.get('TextDetections') else 0
            }
            
            # Additional checks for specific ID types
            is_valid = (
                security_checks['has_text'] and 
                security_checks['has_printed_text'] and
                security_checks['text_confidence'] > 80
            )
            
            return {
                'is_valid': is_valid,
                'security_checks': security_checks,
                'text_detections': len(front_analysis.get('TextDetections', [])),
                'confidence': security_checks['text_confidence']
            }
            
        except Exception as e:
            logger.error(f"Document verification failed: {str(e)}")
            return {'is_valid': False, 'error': str(e)}
    
    async def compare_faces(self, id_photo_url: str, selfie_url: str) -> Dict[str, Any]:
        """Compare faces from ID and selfie using multiple methods"""
        try:
            if not (FACE_RECOGNITION_AVAILABLE or DEEPFACE_AVAILABLE):
                return {
                    'score': 0,
                    'is_match': False,
                    'error': 'Face comparison libraries are not available in this deployment',
                    'methods_scores': {},
                    'degraded': True
                }
            # We always have AWS Rekognition; other methods are optional below.
            # Download images
            id_response = requests.get(id_photo_url)
            selfie_response = requests.get(selfie_url)
            
            methods_scores = {}
            # Method 1: Face Recognition Library (if available)
            if FACE_RECOGNITION_AVAILABLE:
                id_image = face_recognition.load_image_file(io.BytesIO(id_response.content))
                selfie_image = face_recognition.load_image_file(io.BytesIO(selfie_response.content))
                id_encodings = face_recognition.face_encodings(id_image)
                selfie_encodings = face_recognition.face_encodings(selfie_image)
                if id_encodings and selfie_encodings:
                    face_distance = face_recognition.face_distance([id_encodings[0]], selfie_encodings[0])[0]
                    methods_scores['face_recognition'] = max(0, 1 - face_distance)
                else:
                    methods_scores['face_recognition'] = 0
            
            # Method 2: DeepFace (if available) — imported lazily, it pulls in TensorFlow
            if DEEPFACE_AVAILABLE:
                from deepface import DeepFace
                deepface_result = DeepFace.verify(
                    img1_path=id_photo_url,
                    img2_path=selfie_url,
                    model_name='Facenet',
                    distance_metric='cosine',
                    enforce_detection=False
                )
                methods_scores['deepface'] = 1 - deepface_result.get('distance', 1)
            
            # Method 3: AWS Rekognition (always available)
            rekognition_result = self.rekognition_client.compare_faces(
                SourceImage={'Bytes': id_response.content},
                TargetImage={'Bytes': selfie_response.content},
                SimilarityThreshold=70
            )
            rekognition_matches = rekognition_result.get('FaceMatches', [])
            methods_scores['aws_rekognition'] = rekognition_matches[0].get('Similarity', 0) / 100 if rekognition_matches else 0
            
            # Aggregate available scores
            available_scores = [s for s in methods_scores.values() if s is not None]
            threshold = getattr(settings, 'FACE_MATCHING_THRESHOLD', 0.75)
            if not available_scores:
                return {
                    'score': 0,
                    'is_match': False,
                    'error': 'No face comparison methods available',
                    'methods_scores': methods_scores,
                    'degraded': True
                }
            final_score_weighted = float(np.mean(available_scores))
            final_is_match = final_score_weighted >= threshold
            
            return {
                'score': round(final_score_weighted, 3),
                'is_match': final_is_match,
                'threshold': threshold,
                'methods_scores': methods_scores,
                'confidence': 'high' if final_is_match and final_score_weighted > 0.85 else 'medium',
                'details': {
                    'rekognition_matches': len(rekognition_matches)
                },
                'degraded': not FACE_RECOGNITION_AVAILABLE or not DEEPFACE_AVAILABLE
            }
            
        except Exception as e:
            logger.error(f"Face comparison failed: {str(e)}")
            return {
                'score': 0,
                'is_match': False,
                'error': str(e),
                'method': 'combined'
            }
    
    async def check_liveness(self, selfie_url: str) -> Dict[str, Any]:
        """Check if selfie is live (not a photo of a photo)"""
        try:
            if not CV2_AVAILABLE:
                return {
                    'is_live': False,
                    'confidence': 'unknown',
                    'error': 'OpenCV is not available in this deployment',
                    'degraded': True
                }
            # Download image
            response = requests.get(selfie_url)
            image_bytes = io.BytesIO(response.content)
            
            # Convert to OpenCV format
            image = cv2.imdecode(np.frombuffer(image_bytes.getvalue(), np.uint8), cv2.IMREAD_COLOR)
            
            # Basic liveness checks
            # 1. Check for multiple faces (should be exactly 1)
            face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            
            # 2. Check image quality (blur detection)
            blur_value = cv2.Laplacian(image, cv2.CV_64F).var()
            
            # 3. Check for screen reflection/glare (simplified)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            brightness = np.mean(hsv[:,:,2])
            
            liveness_checks = {
                'single_face': len(faces) == 1,
                'image_quality': blur_value > 100,  # Higher is less blurry
                'brightness_ok': 50 < brightness < 200,
                'face_size_ok': len(faces) > 0 and faces[0][2] > 100,  # Face width > 100px
            }
            
            is_live = all(liveness_checks.values())
            
            return {
                'is_live': is_live,
                'confidence': 'high' if is_live else 'low',
                'checks': liveness_checks,
                'details': {
                    'faces_detected': len(faces),
                    'blur_score': blur_value,
                    'brightness': brightness
                }
            }
            
        except Exception as e:
            logger.error(f"Liveness check failed: {str(e)}")
            return {
                'is_live': False,
                'confidence': 'unknown',
                'error': str(e)
            }
    
    async def perform_full_kyc_analysis(self, kyc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Perform complete KYC analysis"""
        try:
            # 1. Document authenticity
            doc_verification = await self.verify_document_authenticity(
                kyc_data['id_front_url'],
                kyc_data.get('id_back_url')
            )
            
            # 2. Face matching
            face_comparison = await self.compare_faces(
                kyc_data['id_front_url'],
                kyc_data['selfie_url']
            )
            
            # 3. Liveness check
            liveness_check = await self.check_liveness(kyc_data['selfie_url'])
            
            # 4. Risk assessment
            risk_score = self.calculate_risk_score(
                doc_verification,
                face_comparison,
                liveness_check,
                kyc_data
            )
            
            # 5. Final decision
            is_approved = (
                doc_verification.get('is_valid', False) and
                face_comparison.get('is_match', False) and
                liveness_check.get('is_live', False) and
                risk_score <= 0.5  # Low risk
            )
            
            return {
                'document_verification': doc_verification,
                'face_comparison': face_comparison,
                'liveness_check': liveness_check,
                'risk_score': risk_score,
                'is_approved': is_approved,
                'overall_confidence': self.calculate_confidence(
                    doc_verification,
                    face_comparison,
                    liveness_check
                ),
                'recommendations': self.generate_recommendations(
                    doc_verification,
                    face_comparison,
                    liveness_check,
                    is_approved
                )
            }
            
        except Exception as e:
            logger.error(f"Full KYC analysis failed: {str(e)}")
            return {
                'error': str(e),
                'is_approved': False,
                'risk_score': 1.0  # High risk due to error
            }
    
    def calculate_risk_score(self, doc_verification: Dict, face_comparison: Dict, 
                           liveness_check: Dict, kyc_data: Dict) -> float:
        """Calculate risk score (0-1)"""
        risk_factors = []
        
        # Document risk
        if not doc_verification.get('is_valid'):
            risk_factors.append(0.5)
        elif doc_verification.get('confidence', 0) < 70:
            risk_factors.append(0.3)
        
        # Face match risk
        if not face_comparison.get('is_match'):
            risk_factors.append(0.6)
        elif face_comparison.get('score', 0) < 0.8:
            risk_factors.append(0.2)
        
        # Liveness risk
        if not liveness_check.get('is_live'):
            risk_factors.append(0.7)
        
        # ID number pattern risk (simplified)
        id_number = kyc_data.get('id_number', '')
        if not id_number or len(id_number) < 6:
            risk_factors.append(0.4)
        
        # Calculate final risk (average of factors, or 0 if no factors)
        return np.mean(risk_factors) if risk_factors else 0.1
    
    def calculate_confidence(self, doc_verification: Dict, face_comparison: Dict, 
                           liveness_check: Dict) -> str:
        """Calculate overall confidence level"""
        scores = []
        
        if doc_verification.get('is_valid'):
            scores.append(doc_verification.get('confidence', 0) / 100)
        
        scores.append(face_comparison.get('score', 0))
        
        if liveness_check.get('is_live'):
            scores.append(0.9)  # High confidence for live selfie
        else:
            scores.append(0.3)  # Low confidence
        
        avg_score = np.mean(scores) if scores else 0
        
        if avg_score > 0.8:
            return 'high'
        elif avg_score > 0.6:
            return 'medium'
        else:
            return 'low'
    
    def generate_recommendations(self, doc_verification: Dict, face_comparison: Dict,
                               liveness_check: Dict, is_approved: bool) -> str:
        """Generate recommendations based on analysis"""
        recommendations = []
        
        if not doc_verification.get('is_valid'):
            recommendations.append("Document appears invalid. Please upload a clear photo of a valid government ID.")
        
        if not face_comparison.get('is_match'):
            recommendations.append("Face doesn't match ID photo. Please ensure you're using your own ID.")
        
        if not liveness_check.get('is_live'):
            recommendations.append("Selfie doesn't appear to be live. Please take a fresh selfie without glasses or masks.")
        
        if face_comparison.get('score', 0) < 0.7:
            recommendations.append("Low face match confidence. Try taking photos in better lighting.")
        
        if not recommendations and is_approved:
            return "All checks passed. Ready for approval."
        
        return "; ".join(recommendations)