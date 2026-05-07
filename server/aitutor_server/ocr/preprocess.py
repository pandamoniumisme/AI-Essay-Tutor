"""OpenCV preprocessing for question and essay images.

Two profiles per the plan:

- normalize_question: printed text. Aggressive — page-detect → deskew →
  adaptive threshold. Optimized for clean printed exam papers.

- normalize_essay: handwritten text on lined paper. Gentler — page-detect →
  deskew → ruled-line suppression → CLAHE. **Does not binarize** because
  PP-OCRv5's recognizer prefers grayscale on handwriting.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)


# --- Public API ----------------------------------------------------------

def normalize_question(bgr: np.ndarray) -> np.ndarray:
    """Preprocess a printed-question photo. Returns a 1-channel uint8 grayscale image.

    Deliberately does NOT binarize. PSLE Chinese 看图作文 questions contain
    black-and-white illustrations alongside the printed text; adaptive thresholding
    turns illustration shading into binary blobs whose contours look like text to
    PaddleOCR's detector, producing junk OCR lines. Grayscale + CLAHE keeps text
    sharp without destroying illustration regions, and PaddleOCR's text detector
    is shape-based so it ignores non-text contours regardless.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    rectified = _rectify_page(gray)
    deskewed = _deskew(rectified)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(deskewed)
    return _resize_short_edge(enhanced, target=1280)


def normalize_essay(bgr: np.ndarray) -> np.ndarray:
    """Preprocess a handwritten-essay photo. Returns a 1-channel uint8 grayscale image
    (NOT binarized — recognizers do better on grayscale handwriting)."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    rectified = _rectify_page(gray)
    deskewed = _deskew(rectified)
    line_free = _suppress_horizontal_rules(deskewed)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(line_free)
    return _resize_short_edge(enhanced, target=1600)


# --- Helpers -------------------------------------------------------------

def _rectify_page(gray: np.ndarray) -> np.ndarray:
    """Find the largest 4-corner contour and warp to a rectangle. No-op if not found."""
    h, w = gray.shape
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray

    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.contourArea(approx) > (h * w) * 0.2:
            return _four_point_warp(gray, approx.reshape(4, 2))
    return gray


def _four_point_warp(gray: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Order four corners (TL, TR, BR, BL) and apply a perspective transform."""
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    src = np.array([tl, tr, br, bl], dtype="float32")

    width_top = np.linalg.norm(tr - tl)
    width_bot = np.linalg.norm(br - bl)
    height_left = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)
    out_w = int(max(width_top, width_bot))
    out_h = int(max(height_left, height_right))
    dst = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype="float32",
    )
    M = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, M, (out_w, out_h))


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Median-Hough deskew. ±15° max — anything beyond that is probably a misdetection."""
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=200,
                            minLineLength=gray.shape[1] // 4, maxLineGap=20)
    if lines is None or len(lines) == 0:
        return gray

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x1 == x2:
            continue
        ang = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Discard near-vertical lines; we want the dominant horizontal alignment.
        if abs(ang) < 30:
            angles.append(ang)
    if not angles:
        return gray
    angle = float(np.median(angles))
    if abs(angle) < 0.3 or abs(angle) > 15:
        return gray

    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


def _suppress_horizontal_rules(gray: np.ndarray) -> np.ndarray:
    """Remove ruled paper lines via morphological subtraction.

    1. Threshold to find dark pixels.
    2. Open with a wide horizontal kernel — keeps long horizontal runs (the rules)
       and discards everything else (text strokes are too short to survive).
    3. Subtract the rule mask from the inverted image, then re-invert.
    """
    _, dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    rules = cv2.morphologyEx(dark, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    # Add the rule mask back to the original gray (rules go from dark → background)
    return cv2.add(gray, rules)


def _resize_short_edge(img: np.ndarray, target: int) -> np.ndarray:
    """Resize so the SHORT edge is at least ``target`` and the LONG edge is
    capped at ``MAX_LONG_EDGE``. Phone photos are ~12 MP (4032x3024); without
    a long-edge cap, paddleocr ends up doing 4-9x more work than necessary on
    every call -- which can stretch a single OCR pass into minutes."""
    h, w = img.shape[:2]
    short = min(h, w)
    long_edge = max(h, w)

    scale = 1.0
    if short < target:
        scale = target / short
    # Apply long-edge cap (overrides upscale if both apply -- final long edge
    # never exceeds MAX_LONG_EDGE).
    if long_edge * scale > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_edge
    if abs(scale - 1.0) < 0.01:
        return img

    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


MAX_LONG_EDGE = 2400
"""Hard cap on the long edge after preprocessing. 2400px is plenty for PP-OCRv5
to read primary-school handwriting (each character is ~80-120px tall in a
2400px-tall page) and keeps inference time reasonable on Lunar Lake CPU."""
