"""
EKAIA Puerto - Detection Cooldown with Similarity Matching
Prevents duplicate registrations and handles OCR inconsistencies
"""
import time
from typing import Dict, Optional, Tuple, List
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def plates_are_similar(plate1: str, plate2: str, max_distance: int = 2) -> bool:
    """Check if two plates are similar (likely same vehicle with OCR errors)"""
    if not plate1 or not plate2:
        return False
    
    # Same plate
    if plate1 == plate2:
        return True
    
    # Different lengths = probably different plates
    if abs(len(plate1) - len(plate2)) > 1:
        return False
    
    # Calculate distance
    distance = levenshtein_distance(plate1, plate2)
    return distance <= max_distance


class SmartDetectionCooldown:
    """
    Intelligent cooldown that:
    1. Prevents duplicate registrations
    2. Groups similar plates (OCR errors)
    3. Requires confirmation before registering
    4. Tracks plate history for better accuracy
    """
    
    def __init__(
        self,
        cooldown_seconds: int = 60,
        similarity_threshold: int = 2,
        min_confirmations: int = 2,
        confirmation_window: int = 30
    ):
        self.cooldown_seconds = cooldown_seconds
        self.similarity_threshold = similarity_threshold
        self.min_confirmations = min_confirmations
        self.confirmation_window = confirmation_window
        
        # Registered plates with timestamp
        self.registered: Dict[str, Dict[str, float]] = {
            'entrada': {},
            'salida': {}
        }
        
        # Pending confirmations: camera -> plate -> list of (timestamp, confidence)
        self.pending: Dict[str, Dict[str, List[Tuple[float, float]]]] = {
            'entrada': defaultdict(list),
            'salida': defaultdict(list)
        }
        
        # Plate groups (similar plates mapped to canonical)
        self.plate_groups: Dict[str, str] = {}
    
    def _get_canonical_plate(self, plate: str, camera: str) -> str:
        """Get the canonical (most common) version of a plate"""
        # Check if we have a known mapping
        if plate in self.plate_groups:
            return self.plate_groups[plate]
        
        # Check similarity with recently registered plates
        for registered_plate in self.registered[camera]:
            if plates_are_similar(plate, registered_plate, self.similarity_threshold):
                self.plate_groups[plate] = registered_plate
                return registered_plate
        
        # Check similarity with pending plates
        for pending_plate in self.pending[camera]:
            if plates_are_similar(plate, pending_plate, self.similarity_threshold):
                # Use the one with more confirmations
                return pending_plate
        
        return plate
    
    def _cleanup_old_entries(self, camera: str):
        """Remove expired entries"""
        current_time = time.time()
        
        # Cleanup registered
        expired = [
            plate for plate, ts in self.registered[camera].items()
            if current_time - ts > self.cooldown_seconds
        ]
        for plate in expired:
            del self.registered[camera][plate]
        
        # Cleanup pending
        for plate in list(self.pending[camera].keys()):
            # Remove old confirmations
            self.pending[camera][plate] = [
                (ts, conf) for ts, conf in self.pending[camera][plate]
                if current_time - ts <= self.confirmation_window
            ]
            # Remove empty entries
            if not self.pending[camera][plate]:
                del self.pending[camera][plate]
    
    def add_detection(self, plate: str, camera: str, confidence: float) -> Tuple[bool, Optional[str]]:
        """
        Add a detection and check if it should be registered
        Returns: (should_register, canonical_plate)
        """
        if not plate or len(plate) < 4:
            return False, None
        
        current_time = time.time()
        self._cleanup_old_entries(camera)
        
        # Get canonical plate (handles OCR variations)
        canonical = self._get_canonical_plate(plate, camera)
        
        # Check if recently registered
        if canonical in self.registered[camera]:
            last_time = self.registered[camera][canonical]
            if current_time - last_time < self.cooldown_seconds:
                logger.debug(f"Plate {canonical} in cooldown ({current_time - last_time:.0f}s ago)")
                return False, canonical
        
        # Add to pending confirmations
        self.pending[camera][canonical].append((current_time, confidence))
        
        # Also track the variant
        if plate != canonical:
            self.plate_groups[plate] = canonical
        
        # Check if we have enough confirmations
        confirmations = self.pending[camera][canonical]
        
        if len(confirmations) >= self.min_confirmations:
            # Calculate average confidence
            avg_confidence = sum(c for _, c in confirmations) / len(confirmations)
            
            # Register
            self.registered[camera][canonical] = current_time
            del self.pending[camera][canonical]
            
            logger.info(f"Plate {canonical} confirmed ({len(confirmations)} readings, avg conf: {avg_confidence:.2f})")
            return True, canonical
        
        logger.debug(f"Plate {canonical} pending ({len(confirmations)}/{self.min_confirmations} confirmations)")
        return False, canonical
    
    def allow(self, plate: str, camera: str) -> bool:
        """Legacy method for compatibility - just checks cooldown"""
        if not plate:
            return False
        
        canonical = self._get_canonical_plate(plate, camera)
        current_time = time.time()
        
        self._cleanup_old_entries(camera)
        
        if canonical in self.registered[camera]:
            return False
        
        return True
    
    def force_register(self, plate: str, camera: str):
        """Force register a plate (bypass confirmation)"""
        canonical = self._get_canonical_plate(plate, camera)
        self.registered[camera][canonical] = time.time()
        
        # Clear pending
        if canonical in self.pending[camera]:
            del self.pending[camera][canonical]
    
    def get_stats(self) -> dict:
        """Get current cooldown stats"""
        return {
            'registered': {
                'entrada': list(self.registered['entrada'].keys()),
                'salida': list(self.registered['salida'].keys())
            },
            'pending': {
                'entrada': {p: len(c) for p, c in self.pending['entrada'].items()},
                'salida': {p: len(c) for p, c in self.pending['salida'].items()}
            },
            'plate_groups': dict(self.plate_groups)
        }


# Singleton
_cooldown_instance = None


def get_detection_cooldown() -> SmartDetectionCooldown:
    """Get or create cooldown singleton"""
    global _cooldown_instance
    if _cooldown_instance is None:
        _cooldown_instance = SmartDetectionCooldown(
            cooldown_seconds=120,      # 2 minutos entre registros del mismo vehiculo
            similarity_threshold=2,     # Max 2 caracteres diferentes = mismo vehiculo
            min_confirmations=3,        # Requiere 3 lecturas consistentes
            confirmation_window=30      # Dentro de 30 segundos
        )
    return _cooldown_instance