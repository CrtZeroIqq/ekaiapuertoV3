"""
EKAIA Puerto - OCR Service v4
EasyOCR optimizado para patentes chilenas y bolivianas
"""
import re
import numpy as np
from typing import Optional, Tuple, List
import cv2
import logging

logger = logging.getLogger(__name__)

easyocr = None


class LicensePlateOCR:
    """OCR optimizado para patentes chilenas y bolivianas"""

    # Patentes chilenas: BBBB-00 (4 letras + 2 numeros)
    # Letras permitidas: B,C,D,F,G,H,J,K,L,P,R,S,T,V,W,X,Y,Z
    CHILE_VALID_LETTERS = set('BCDFGHJKLPRSTVWXYZ')
    
    # Patentes bolivianas: 0000-BBB (4 numeros + 3 letras)
    # Ejemplo: 1852PHD
    
    PATTERNS = [
        # Chile nuevo: LLLL00
        (r'^[BCDFGHJKLPRSTVWXYZ]{4}\d{2}$', 'chile_nuevo', 1.0),
        # Chile con cualquier letra: LLLL00
        (r'^[A-Z]{4}\d{2}$', 'chile_flex', 0.9),
        # Bolivia: 0000LLL
        (r'^\d{4}[A-Z]{3}$', 'bolivia', 1.0),
        # Bolivia alternativo: 000LLL
        (r'^\d{3}[A-Z]{3}$', 'bolivia_alt', 0.8),
        # Chile antiguo: LL0000
        (r'^[A-Z]{2}\d{4}$', 'chile_antiguo', 0.9),
    ]

    # Correcciones OCR
    LETTER_TO_LETTER = {
        '0': 'O', '1': 'I', '2': 'Z', '3': 'B',
        '4': 'A', '5': 'S', '6': 'G', '7': 'T',
        '8': 'B', '9': 'G',
    }
    
    NUMBER_TO_NUMBER = {
        'O': '0', 'Q': '0', 'D': '0',
        'I': '1', 'L': '1', 'J': '1',
        'Z': '2', 'E': '3', 'A': '4', 'H': '4',
        'S': '5', 'G': '6', 'C': '6',
        'T': '7', 'Y': '7', 'B': '8',
    }

    def __init__(self, use_gpu: bool = True):
        global easyocr
        if easyocr is None:
            import easyocr as _easyocr
            easyocr = _easyocr

        self.reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
        self.use_gpu = use_gpu
        logger.info(f"OCR v4 initialized (GPU={use_gpu}) - Chile + Bolivia support")

    def _preprocess_original(self, image: np.ndarray) -> np.ndarray:
        return self._resize(image)

    def _preprocess_grayscale(self, image: np.ndarray) -> np.ndarray:
        img = self._resize(image)
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        return clahe.apply(gray)

    def _preprocess_threshold(self, image: np.ndarray) -> np.ndarray:
        img = self._resize(image)
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        binary = cv2.adaptiveThreshold(
            denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        return binary

    def _preprocess_otsu(self, image: np.ndarray) -> np.ndarray:
        img = self._resize(image)
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    def _preprocess_invert(self, image: np.ndarray) -> np.ndarray:
        binary = self._preprocess_otsu(image)
        return cv2.bitwise_not(binary)

    def _preprocess_morph(self, image: np.ndarray) -> np.ndarray:
        binary = self._preprocess_otsu(image)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        return cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    def _preprocess_bilateral_clahe(self, image: np.ndarray) -> np.ndarray:
        """Bilateral filter + CLAHE para preservar bordes y mejorar contraste"""
        # Filtro bilateral para suavizar manteniendo bordes
        bilateral = cv2.bilateralFilter(image, 9, 75, 75)

        # CLAHE en canal L de LAB
        lab = cv2.cvtColor(bilateral, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l)
        lab_enhanced = cv2.merge([l_clahe, a, b])
        enhanced = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)

        # Convertir a grayscale
        return cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)

    def _preprocess_sharpen(self, image: np.ndarray) -> np.ndarray:
        """Sharpen para patentes borrosas"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Kernel de sharpening
        kernel_sharpen = np.array([[-1, -1, -1],
                                   [-1,  9, -1],
                                   [-1, -1, -1]])

        sharpened = cv2.filter2D(gray, -1, kernel_sharpen)
        return sharpened

    def _preprocess_adaptive_multi(self, image: np.ndarray) -> np.ndarray:
        """Threshold adaptativo con block size óptimo para patentes"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Probar con block size más pequeño (mejor para texto pequeño)
        adaptive = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11,  # Block size reducido
            2
        )

        return adaptive

    def _preprocess_denoise(self, image: np.ndarray) -> np.ndarray:
        """Denoise + threshold para imágenes con ruido"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Non-local means denoising
        denoised = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)

        # Threshold Otsu después del denoise
        _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return binary

    def _preprocess_tophat(self, image: np.ndarray) -> np.ndarray:
        """Top-hat morphology para resaltar texto en fondo oscuro"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Morphological top-hat
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
        tophat = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, kernel)

        # Threshold
        _, binary = cv2.threshold(tophat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        return binary

    def _preprocess_edge_enhanced(self, image: np.ndarray) -> np.ndarray:
        """Realce de bordes para patentes con bajo contraste"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Ecualización de histograma
        equalized = cv2.equalizeHist(gray)

        # Realce de bordes usando Sobel
        sobelx = cv2.Sobel(equalized, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(equalized, cv2.CV_64F, 0, 1, ksize=3)
        sobel = np.sqrt(sobelx**2 + sobely**2)
        sobel = np.uint8(sobel / sobel.max() * 255)

        # Combinar con imagen original
        combined = cv2.addWeighted(equalized, 0.7, sobel, 0.3, 0)

        return combined

    def _resize(self, image: np.ndarray, target_height: int = 80) -> np.ndarray:
        h, w = image.shape[:2]
        if h < 30:
            return image
        scale = target_height / h
        new_w = int(w * scale)
        interp = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        return cv2.resize(image, (new_w, target_height), interpolation=interp)

    def _clean_text(self, text: str) -> str:
        cleaned = re.sub(r'[^A-Za-z0-9]', '', text)
        return cleaned.upper()

    def _detect_plate_type(self, text: str) -> Tuple[str, float]:
        """Detectar tipo de patente y retornar score"""
        # Verificar longitud
        if len(text) == 6:
            # Puede ser Chile (LLLL00) o Bolivia (000LLL truncada)
            if text[:4].isalpha() and text[4:].isdigit():
                return 'chile', 1.0
        elif len(text) == 7:
            # Bolivia: 0000LLL
            if text[:4].isdigit() and text[4:].isalpha():
                return 'bolivia', 1.0
        
        return 'unknown', 0.5

    def _correct_chile_plate(self, text: str) -> str:
        """Corregir formato chileno LLLL00"""
        if len(text) != 6:
            return text
        
        corrected = list(text)
        
        # Primeros 4 = letras
        for i in range(4):
            if corrected[i].isdigit():
                corrected[i] = self.LETTER_TO_LETTER.get(corrected[i], corrected[i])
        
        # Ultimos 2 = numeros
        for i in range(4, 6):
            if corrected[i].isalpha():
                corrected[i] = self.NUMBER_TO_NUMBER.get(corrected[i], corrected[i])
        
        return ''.join(corrected)

    def _correct_bolivia_plate(self, text: str) -> str:
        """Corregir formato boliviano 0000LLL"""
        if len(text) != 7:
            return text
        
        corrected = list(text)
        
        # Primeros 4 = numeros
        for i in range(4):
            if corrected[i].isalpha():
                corrected[i] = self.NUMBER_TO_NUMBER.get(corrected[i], corrected[i])
        
        # Ultimos 3 = letras
        for i in range(4, 7):
            if corrected[i].isdigit():
                corrected[i] = self.LETTER_TO_LETTER.get(corrected[i], corrected[i])
        
        return ''.join(corrected)

    def _validate_plate(self, text: str) -> Tuple[bool, str, float]:
        """Validar patente contra patrones conocidos"""
        for pattern, plate_type, base_score in self.PATTERNS:
            if re.match(pattern, text):
                return True, plate_type, base_score
        return False, 'unknown', 0.3

    def _run_ocr(self, image: np.ndarray) -> List[Tuple[str, float]]:
        try:
            results = self.reader.readtext(image, detail=1)
            return [(text, conf) for (_, text, conf) in results]
        except Exception as e:
            logger.debug(f"OCR error: {e}")
            return []

    def extract_text(self, image: np.ndarray) -> Tuple[Optional[str], float]:
        if image is None or image.size == 0:
            return None, 0.0

        strategies = [
            # Estrategias básicas (rápidas)
            ("original", self._preprocess_original),
            ("grayscale", self._preprocess_grayscale),
            ("otsu", self._preprocess_otsu),

            # Estrategias avanzadas (mejores para casos difíciles)
            ("bilateral_clahe", self._preprocess_bilateral_clahe),
            ("sharpen", self._preprocess_sharpen),
            ("adaptive_multi", self._preprocess_adaptive_multi),

            # Estrategias adicionales
            ("threshold", self._preprocess_threshold),
            ("invert", self._preprocess_invert),
            ("morph", self._preprocess_morph),
            ("denoise", self._preprocess_denoise),
            ("tophat", self._preprocess_tophat),
            ("edge_enhanced", self._preprocess_edge_enhanced),
        ]

        candidates = []

        for name, preprocess_fn in strategies:
            try:
                processed = preprocess_fn(image)
                results = self._run_ocr(processed)
                
                for text, conf in results:
                    cleaned = self._clean_text(text)
                    
                    if len(cleaned) < 5 or len(cleaned) > 8:
                        continue
                    
                    # Detectar tipo y corregir
                    plate_type, type_score = self._detect_plate_type(cleaned)
                    
                    if plate_type == 'chile' and len(cleaned) == 6:
                        corrected = self._correct_chile_plate(cleaned)
                    elif plate_type == 'bolivia' and len(cleaned) == 7:
                        corrected = self._correct_bolivia_plate(cleaned)
                    else:
                        corrected = cleaned
                    
                    # Validar
                    is_valid, valid_type, validity_score = self._validate_plate(corrected)
                    
                    # Score final
                    final_score = conf * 0.4 + validity_score * 0.4 + type_score * 0.2
                    
                    if is_valid:
                        final_score += 0.15
                    
                    candidates.append({
                        'text': corrected,
                        'original': cleaned,
                        'confidence': conf,
                        'final_score': final_score,
                        'is_valid': is_valid,
                        'type': valid_type,
                        'method': name
                    })
                    
            except Exception as e:
                logger.debug(f"Strategy {name} failed: {e}")
                continue

        if not candidates:
            return None, 0.0

        # Votar
        vote_counts = {}
        vote_scores = {}
        
        for c in candidates:
            text = c['text']
            if text not in vote_counts:
                vote_counts[text] = 0
                vote_scores[text] = 0.0
            vote_counts[text] += 1
            vote_scores[text] = max(vote_scores[text], c['final_score'])

        best_text = None
        best_score = 0.0
        
        for text, count in vote_counts.items():
            score = vote_scores[text] + min(count * 0.1, 0.3)
            if score > best_score:
                best_score = score
                best_text = text

        if best_text and best_score >= 0.4:
            logger.info(f"OCR: {best_text} (score={best_score:.2f}, votes={vote_counts.get(best_text, 0)})")
            return best_text, min(best_score, 1.0)
        
        return None, 0.0

    def extract_from_bbox(self, frame: np.ndarray, bbox: list) -> Tuple[Optional[str], float]:
        x1, y1, x2, y2 = map(int, bbox)

        h, w = frame.shape[:2]
        box_w = x2 - x1
        box_h = y2 - y1
        
        pad_x = int(box_w * 0.15)
        pad_y = int(box_h * 0.15)

        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)

        plate_img = frame[y1:y2, x1:x2]

        if plate_img.size == 0:
            return None, 0.0

        return self.extract_text(plate_img)


_ocr_instance = None


def get_ocr_service(use_gpu: bool = True) -> LicensePlateOCR:
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = LicensePlateOCR(use_gpu=use_gpu)
    return _ocr_instance